
# VRH Managers API

Небольшой REST‑сервис на **Flask** для получения e‑mail менеджеров по списку логинов агентов. Подключается к PostgreSQL, защищён по API‑ключу и ограничивает частоту запросов.

## Стек
- Python 3.12
- Flask, Flask-Limiter, Flask-CORS
- psycopg2-binary
- Gunicorn
- Docker / Docker Compose

## Быстрый старт (локально, без Docker)
1) Установите зависимости:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
2) Создайте файл `.env` (см. пример ниже).
3) Запустите приложение для разработки:
```bash
export FLASK_ENV=development
python app.py
```
Приложение поднимется на `http://0.0.0.0:5000` (порт и хост можно поменять переменными `HOST`, `PORT`).

## Запуск через Gunicorn (prod)
```bash
gunicorn --bind 0.0.0.0:5000 --workers 2 wsgi:app
```

## Docker
### Сборка образа из Dockerfile
> **Важно:** текущий `Dockerfile` использует базовый образ `python:3.12.12-slim` (Debian), но ставит пакеты через `apk` (Alpine), что не совместимо. Либо смените базовый образ на Alpine (`python:3.12-alpine`), либо используйте `apt-get` вместо `apk`. Ниже — пример варианта на Debian:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

USER root
EXPOSE 5000

HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "wsgi:app"]
```

Сборка и запуск:
```bash
docker build -t vrh-managers-api:latest .
docker run --env-file .env -p 5000:5000 --restart unless-stopped vrh-managers-api:latest
```

### Docker Compose
В репозитории есть `docker-compose.yml`, который использует готовый образ:
```yaml
services:
  vrh-managers-api:
    image: malolet/vrh-managers-api:latest
    env_file: .env
    ports: ["5000:5000"]
    restart: unless-stopped
```
Запуск:
```bash
docker compose up -d
```

## Переменные окружения
Обязательные:
- `DB_USER` — пользователь БД
- `DB_PASSWORD` — пароль БД
- `DB_HOST` — хост БД
- `DB_PORT` — порт БД (по умолчанию 5432)
- `DB_DATABASE` — имя базы
- `API_KEYS` — список допустимых API‑ключей (через запятую), сравнивается с заголовком `X-API-Key`

Опциональные/поведенческие:
- `ALLOWED_ORIGINS` — разрешённые origin'ы для CORS, через запятую (по умолчанию `http://localhost:3000`)
- `RATE_LIMIT` — общий лимит запросов приложения (по умолчанию `100 per hour`)
- `HOST` — хост для запуска дев‑сервера Flask (по умолчанию `0.0.0.0`)
- `PORT` — порт (по умолчанию `5000`)
- `DEBUG` — `true`/`false` для включения debug в дев‑сервере

### Пример `.env`
```dotenv
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=127.0.0.1
DB_PORT=5432
DB_DATABASE=vrh
API_KEYS=supersecret1,supersecret2
ALLOWED_ORIGINS=http://localhost:3000,https://example.com
RATE_LIMIT=100 per hour
HOST=0.0.0.0
PORT=5000
DEBUG=false
```

## Точки API
### `GET /health`
Проверка живости сервиса.
```bash
curl -s http://localhost:5000/health
```
Ответ:
```json
{"status": "healthy", "timestamp": "2025-11-05T12:00:00.000000"}
```

### `POST /api/managers`  _(требуется API‑ключ, лимит 5/час)_
Получение e‑mail менеджера для каждого запрошенного агента.
Заголовки:
- `Content-Type: application/json`
- `X-API-Key: <ваш ключ из API_KEYS>`

Тело запроса:
```json
{"agents": ["agent_login_1", "agent_login_2"]}
```
Пример запроса:
```bash
curl -s -X POST http://localhost:5000/api/managers \
  -H "Content-Type: application/json" \
  -H "X-API-Key: supersecret1" \
  -d '{"agents":["agent1","agent2"]}'
```
Успешный ответ:
```json
{"managers": {"agent1": "manager1@example.com", "agent2": null}}
```

#### Ошибки
- `400` — неверный формат (нет JSON, нет поля `agents`, не список, пустые элементы, слишком много элементов)
- `401` — нет/неверный `X-API-Key`
- `404` — неизвестный эндпоинт
- `429` — превышен лимит частоты
- `500` — внутренняя ошибка (в т.ч. БД)

## Поведение и внутренности
- CORS: разрешённые origin'ы задаются `ALLOWED_ORIGINS` (через запятую).
- Rate limiting: общий лимит — переменная `RATE_LIMIT` на всё приложение; для `POST /api/managers` дополнительно пер‑эндпоинтовый лимит `5 per hour`.
- База: подключение к PostgreSQL через `psycopg2` и курсор `RealDictCursor`.
- Запрос к БД выбирает уникальные пары «агент → менеджер» из схемы `public` с таблицами:
  - `app_users` (агенты и менеджеры)
  - `user_managers` (сопоставление user → manager)
  - `orders_paid_operations` (фильтр только по пользователям с оплатами)
- Логирование: стандартный `logging` в stdout.

## Структура
```
├─ app.py          # приложение Flask, эндпоинты, CORS, лимиты, БД
├─ wsgi.py         # точка входа для Gunicorn
├─ requirements.txt
├─ Dockerfile
└─ docker-compose.yml
```

## Лицензия
MIT (или укажите свою).
