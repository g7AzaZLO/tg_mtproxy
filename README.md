# MTProxy Store

Коммерческий сервис продажи MTProto-прокси для Telegram через Telegram-бота.

## Стек

- **Python 3.12+**
- **aiogram 3** — Telegram-бот
- **FastAPI** — Web API (webhook-и, admin API)
- **asyncpg** — PostgreSQL (чистый SQL, без ORM)
- **APScheduler** — фоновые задачи
- **mtprotoproxy** — MTProto proxy на нодах
- **CryptoCloud** — оплата криптовалютой

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -e ".[dev]"
```

### 2. Настройка окружения

```bash
cp .env.example .env
# Отредактируйте .env — заполните BOT_TOKEN, DB_PASSWORD, CRYPTOCLOUD_API_KEY и т.д.
```

### 3. Запуск PostgreSQL (dev)

```bash
docker compose up -d
```

### 4. Применение миграций

```bash
python -m migrations.run
```

### 5. Запуск приложения

```bash
python -m src.main
```

## Node Agent

На каждой ноде с MTProxy устанавливается легковесный API-агент:

```bash
cd node_agent
pip install -e .
AGENT_API_KEY=secret uvicorn node_agent.agent:app --host 127.0.0.1 --port 9090
```

## Структура проекта

```
src/
├── config.py         — Настройки (pydantic-settings)
├── main.py           — Точка входа
├── bot/              — Telegram-бот (aiogram 3)
│   ├── handlers/     — Обработчики команд и кнопок
│   ├── keyboards/    — Inline-клавиатуры
│   ├── middlewares/  — Throttle, регистрация, бан-чек
│   └── callbacks/    — CallbackData factories
├── web/              — FastAPI (webhook, admin API)
├── services/         — Бизнес-логика
├── db/               — asyncpg pool + репозитории (raw SQL)
└── utils/            — Генерация секретов, ссылки

node_agent/           — API-агент для нод MTProxy
migrations/           — SQL-миграции
deploy/               — systemd, nginx конфиги
```
