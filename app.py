import os
import sys
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from functools import wraps

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False

    CORS(app, origins=os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(','))

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[os.getenv('RATE_LIMIT', '100 per hour')]
    )

    db_params = {
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT", 5432)),
        "database": os.getenv("DB_DATABASE"),
    }

    API_KEYS = set(os.getenv('API_KEYS', '').split(','))

    def require_api_key(f):
        """Декоратор для проверки API ключа"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            api_key = request.headers.get('X-API-Key')
            if not api_key or api_key not in API_KEYS:
                logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
                return jsonify({"error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated_function

    def validate_agents_decorator(max_agents=300, allow_empty=False):
        """Декоратор для валидации списка агентов с параметрами"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if not request.is_json:
                    return jsonify({"error": "Content-Type must be application/json"}), 400
                data = request.get_json()
                if not data or 'agents' not in data:
                    return jsonify({"error": "Missing 'agents' in request body"}), 400
                agents = data['agents']
                if not isinstance(agents, list):
                    return jsonify({"error": "Agents must be a list"}), 400
                if len(agents) > max_agents:
                    return jsonify({"error": f"Too many agents, maximum {max_agents}"}), 400
                if not all(isinstance(agent, str) for agent in agents):
                    return jsonify({"error": "All agents must be strings"}), 400
                if not allow_empty and any(agent.strip() == '' for agent in agents):
                    return jsonify({"error": "Agent names cannot be empty"}), 400
                return f(*args, **kwargs)
            return decorated_function
        return decorator

    def get_pg_connection():
        return psycopg2.connect(**db_params)

    @app.route('/health', methods=['GET'])
    def health_check():
        try:
            return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({"status": "unhealthy", "error": str(e)}), 500

    @app.route('/api/managers', methods=['POST'])
    @require_api_key
    @validate_agents_decorator(max_agents=300, allow_empty=False)
    def get_managers():
        """
        Получение менеджеров по списку агентов
        Body: {"agents": ["agent1", "agent2", ...]}
        """

        try:
            data = request.get_json()
            agents = data['agents']

            agent_count = len(agents) # Определяем количество агентов
            placeholder_list = ['%s'] * agent_count # Создаем список плейсхолдеров - по одному на каждого агента
            placeholders = ', '.join(placeholder_list) # Объединяем плейсхолдеры через запятую для SQL запроса

            # Результат: для 3 агентов -> '%s, %s, %s', это сделано для того, чтобы предотвратить SQL-инъекции..

            query = f"""
                SELECT DISTINCT
                    pau.username AS agent,
                    pau2.email AS manager
                FROM public.app_users pau
                LEFT JOIN public.user_managers pum on pum.user_id = pau.id
                LEFT JOIN public.app_users pau2 on pau2.id = pum.manager_id
                WHERE pau.username IN ({placeholders})
            """

            with get_pg_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, agents)
                    result = cur.fetchall()

            response_data = {agent: None for agent in agents}
            
            agent_managers = {}
            for row in result:
                agent = row['agent']
                manager = row['manager']
                
                if manager:
                    if agent not in agent_managers:
                        agent_managers[agent] = set()  # Используем set для уникальности
                    agent_managers[agent].add(manager)
    
            # Обновляем ответ для агентов, у которых есть менеджеры
            for agent, managers_set in agent_managers.items():
                if managers_set:
                    response_data[agent] = ", ".join(sorted(managers_set))

            logger.info(f"Successfully processed request for {len(agents)} agents from {request.remote_addr}")
            return jsonify({"managers": response_data})

        except psycopg2.Error as e:
            logger.error(f"Database error: {e}")
            return jsonify({"error": "Database error"}), 500
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({
            "error": "Rate limit exceeded",
            "message": "Too many requests"
        }), 429

    @app.errorhandler(404)
    def not_found_handler(e):
        return jsonify({"error": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error_handler(e):
        return jsonify({"error": "Internal server error"}), 500

    return app

app = create_app()

if __name__ == '__main__':
    required_env_vars = ['DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_DATABASE', 'API_KEYS']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'

    logger.info(f"Starting development server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
