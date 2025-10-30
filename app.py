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

    def validate_api_key():
        """Проверка API ключа"""
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key not in API_KEYS:
            return False
        return True

    def validate_agents(agents):
        """Валидация списка агентов"""
        if not isinstance(agents, list):
            return False, "Agents must be a list"

        if len(agents) > 100:
            return False, "Too many agents, maximum 100"

        for agent in agents:
            if not re.match(r'^[a-zA-Z0-9_]+$', str(agent)):
                return False, f"Invalid agent format: {agent}"

        return True, "Valid"

    def get_pg_connection():
        return psycopg2.connect(**db_params)

    @app.route('/health', methods=['GET'])
    def health_check():
        try:
            with get_pg_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT 1')
            return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({"status": "unhealthy", "error": str(e)}), 500

    @app.route('/api/managers', methods=['POST'])
    @limiter.limit("5 per hour")
    def get_managers():
        """
        Получение менеджеров по списку агентов
        Body: {"agents": ["agent1", "agent2", ...]}
        """

        if not validate_api_key():
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        data = request.get_json()
        if not data or 'agents' not in data:
            return jsonify({"error": "Missing 'agents' in request body"}), 400

        agents = data['agents']
        is_valid, message = validate_agents(agents)
        if not is_valid:
            return jsonify({"error": message}), 400

        try:
            placeholders = ','.join(['%s'] * len(agents))
            query = f"""
                SELECT DISTINCT
                    pau.username AS agent,
                    pau2.email AS manager
                FROM public.app_users pau
                LEFT JOIN public.user_managers pum on pum.user_id = pau.id
                LEFT JOIN public.app_users pau2 on pau2.id = pum.manager_id
                INNER JOIN public.orders_paid_operations popo ON popo.user_id = pau.id
                WHERE popo.paid_operation_id = 227 
                AND popo.is_owner = true
                AND pau.username IN ({placeholders})
            """

            with get_pg_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, agents)
                    result = cur.fetchall()

            managers_map = {row['agent']: row['manager'] for row in result}

            response_data = {}
            for agent in agents:
                response_data[agent] = managers_map.get(agent)

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