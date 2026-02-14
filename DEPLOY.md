# Руководство по развёртыванию MTProxy Store

## Архитектура

```
ОСНОВНОЙ СЕРВЕР (отдельный VPS):
├── Docker контейнер: PostgreSQL (порт 5432)
├── Systemd: mtproxy-bot (бот + FastAPI + scheduler, порт 8080)
└── Nginx: reverse proxy (443 -> 8080)

НОДА (каждая, отдельный VPS в нужной стране):
├── Systemd: mtprotoproxy (порт 443, слушает пользователей)
└── Systemd: node-agent (порт 9090, слушает основной сервер)
```

---

## Часть 1: Основной сервер

### 1.1. Подготовка

```bash
apt update && apt upgrade -y
apt install -y docker.io docker-compose-v2 python3.12 python3.12-venv nginx certbot python3-certbot-nginx git
```

### 1.2. Клонирование проекта

```bash
cd /opt
git clone https://github.com/g7AzaZLO/tg_mtproxy.git
cd /opt/tg_mtproxy
```

### 1.3. Настройка .env

```bash
cp .env.example .env
nano .env
```

Заполнить все поля:

```
# Telegram Bot
BOT_TOKEN=токен_от_BotFather

# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mtproxy
DB_USER=mtproxy
DB_PASSWORD="надёжный_пароль_бд"

# CryptoCloud (из личного кабинета https://app.cryptocloud.plus)
CRYPTOCLOUD_API_KEY="ваш_api_key"
CRYPTOCLOUD_SHOP_ID="ваш_shop_id"
CRYPTOCLOUD_SECRET_KEY="ваш_secret_key"

# Web Server
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_BASE_URL=https://ваш_домен.com

# Админка
ADMIN_USERNAME=ваш_логин
ADMIN_PASSWORD="ваш_пароль"

# JWT (сгенерировать: python3 -c "import secrets; print(secrets.token_hex(32))")
JWT_SECRET="сгенерированная_строка"

# Сервис
TRIAL_DURATION_DAYS=2
NOTIFY_BEFORE_DAYS=3,1
```

> Значения со спецсимволами (@, $, !, #) оборачивать в двойные кавычки.

### 1.4. Пароль БД в docker-compose.yml

Пароль должен совпадать с `DB_PASSWORD` в `.env`:

```bash
nano docker-compose.yml
# Изменить POSTGRES_PASSWORD на тот же пароль (без кавычек)
```

### 1.5. Запуск PostgreSQL

```bash
docker compose up -d

# Проверка (должен быть running + порт 5432)
docker compose ps

# Проверка логов (ждём "database system is ready")
docker compose logs postgres
```

Миграция `001_initial.sql` применяется автоматически при первом запуске.

### 1.6. Python-окружение

```bash
cd /opt/tg_mtproxy
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 1.7. Проверка запуска

```bash
python -m src.main
```

Отправить боту `/start` в Telegram. Если ответил — всё работает. Остановить: Ctrl+C.

### 1.8. Systemd-сервис

```bash
cat > /etc/systemd/system/mtproxy-bot.service << 'EOF'
[Unit]
Description=MTProxy Telegram Bot + Web API
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/tg_mtproxy
EnvironmentFile=/opt/tg_mtproxy/.env
ExecStart=/opt/tg_mtproxy/.venv/bin/python -m src.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mtproxy-bot

# Проверка
systemctl status mtproxy-bot

# Логи в реальном времени
journalctl -u mtproxy-bot -f
```

### 1.9. SSL-сертификат

```bash
# Если nginx уже запущен — через webroot
certbot certonly --webroot -w /var/www/html -d ваш_домен.com

# Если nginx не запущен — через standalone
certbot certonly --standalone -d ваш_домен.com
```

### 1.10. Nginx

```bash
cp deploy/nginx.conf /etc/nginx/sites-available/mtproxy

# Заменить домен
sed -i 's/yourdomain.com/ваш_домен.com/g' /etc/nginx/sites-available/mtproxy

# Активировать
ln -sf /etc/nginx/sites-available/mtproxy /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Проверить и применить
nginx -t && systemctl reload nginx
```

### 1.11. Webhook CryptoCloud

В личном кабинете CryptoCloud -> настройки проекта -> Postback URL:

```
https://ваш_домен.com/webhooks/cryptocloud
```

### 1.12. Настройка тарифов

По умолчанию созданы тарифы:

| План | Дней | Цена |
|------|------|------|
| Пробный | 3 | $0.00 |
| 7 дней | 7 | $1.50 |
| 30 дней | 30 | $3.00 |
| 90 дней | 90 | $7.00 |

Изменить цены:

```bash
docker compose exec postgres psql -U mtproxy -d mtproxy
```

```sql
-- Посмотреть текущие
SELECT * FROM plans;

-- Изменить цены
UPDATE plans SET price_usd = 2.00 WHERE duration_days = 7;
UPDATE plans SET price_usd = 5.00 WHERE duration_days = 30;
UPDATE plans SET price_usd = 12.00 WHERE duration_days = 90;

-- Добавить новый тариф
INSERT INTO plans (name, duration_days, price_usd, is_trial)
VALUES ('180 дней', 180, 20.00, FALSE);

-- Отключить тариф
UPDATE plans SET is_active = FALSE WHERE duration_days = 7;

\q
```

Изменения применяются мгновенно, рестарт не нужен.

---

## Часть 2: Нода (прокси-сервер)

Повторяется для каждого нового VPS. Основной сервер не перезапускается.

### 2.1. Подготовка

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv wget
```

### 2.2. mtprotoproxy

```bash
mkdir -p /opt/mtprotoproxy
cd /opt/mtprotoproxy

wget https://raw.githubusercontent.com/alexbers/mtprotoproxy/master/mtprotoproxy.py

cat > config.py << 'PYEOF'
PORT = 443
USERS = {
}

# Домен-маскировка для fake-TLS (не оставляйте www.google.com!)
TLS_DOMAIN = "ya.ru"

# Отключить IPv6 (если IPv6 не работает — вызывает таймаут первого подключения)
PREFER_IPV6 = False

# Увеличенные буферы (для серверов с >= 1GB RAM)
TO_CLT_BUFSIZE = 524288
TO_TG_BUFSIZE = 524288

# Держать соединение клиента 1 час (меньше переподключений)
CLIENT_KEEPALIVE = 3600

MODES = {
    "classic": False,
    "secure": True,
    "tls": True,
}
PYEOF

cat > /etc/systemd/system/mtprotoproxy.service << 'EOF'
[Unit]
Description=MTProto Proxy
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/mtprotoproxy
ExecStart=/usr/bin/python3 /opt/mtprotoproxy/mtprotoproxy.py
ExecReload=/bin/kill -HUP $MAINPID
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mtprotoproxy
systemctl status mtprotoproxy
```

### 2.3. Node Agent

```bash
mkdir -p /opt/node_agent
cd /opt/node_agent

# Копируем файлы с основного сервера (нужны только agent.py и config_manager.py)
scp root@IP_ОСНОВНОГО:/opt/tg_mtproxy/node_agent/agent.py ./
scp root@IP_ОСНОВНОГО:/opt/tg_mtproxy/node_agent/config_manager.py ./

# Python-окружение
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi "uvicorn[standard]"
```

### 2.4. Настройка агента

```bash
# Генерируем уникальный API-ключ для этой ноды (ЗАПОМНИТЬ!)
python3 -c "import secrets; print(secrets.token_hex(32))"

# Создаём .env
cat > /opt/node_agent/.env << 'EOF'
AGENT_API_KEY=сгенерированный_ключ_выше
MTPROXY_CONFIG_PATH=/opt/mtprotoproxy/config.py
MTPROXY_PID_FILE=/opt/mtprotoproxy/mtprotoproxy.pid
EOF
```

### 2.5. Systemd для агента

```bash
cat > /etc/systemd/system/node-agent.service << 'EOF'
[Unit]
Description=MTProxy Node Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/node_agent
EnvironmentFile=/opt/node_agent/.env
ExecStart=/opt/node_agent/.venv/bin/uvicorn agent:app --host 0.0.0.0 --port 9090
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now node-agent
systemctl status node-agent
```

### 2.6. Файрвол

```bash
# MTProxy — открыт всем
ufw allow 443/tcp

# Agent API — ТОЛЬКО для основного сервера
ufw allow from IP_ОСНОВНОГО_СЕРВЕРА to any port 9090

# SSH
ufw allow 22/tcp

ufw enable
```

---

## Часть 3: Регистрация ноды в системе

Выполняется один раз. Нода появляется в боте мгновенно.

### 3.1. Получить JWT-токен

```bash
TOKEN=$(curl -s -X POST https://ваш_домен.com/api/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"ваш_логин","password":"ваш_пароль"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN
```

### 3.2. Добавить ноду

```bash
curl -X POST https://ваш_домен.com/api/admin/nodes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "DE-1",
    "host": "IP_НОДЫ",
    "port": 443,
    "country": "Германия",
    "country_flag": "🇩🇪",
    "agent_url": "http://IP_НОДЫ:9090",
    "agent_api_key": "AGENT_API_KEY_ИЗ_ENV_НОДЫ",
    "max_users": 500
  }'
```

Флаги стран для удобства:
- 🇩🇪 Германия
- 🇳🇱 Нидерланды
- 🇫🇮 Финляндия
- 🇺🇸 США
- 🇬🇧 Великобритания
- 🇫🇷 Франция
- 🇸🇬 Сингапур
- 🇯🇵 Япония

### 3.3. Проверка

Отправить боту `/start` -> «Купить прокси» — должна появиться новая локация.

---

## Часть 4: Альтернативный способ — через psql

Если нет желания работать с API, ноду можно добавить напрямую в БД на основном сервере:

```bash
docker compose exec postgres psql -U mtproxy -d mtproxy -c "
INSERT INTO nodes (name, host, port, country, country_flag, agent_url, agent_api_key, max_users)
VALUES ('DE-1', 'IP_НОДЫ', 443, 'Германия', '🇩🇪', 'http://IP_НОДЫ:9090', 'AGENT_API_KEY', 500);
"
```

---

## Управление

### Команды бота (для админов)

```
/admin    — список админ-команд
/stats    — статистика (пользователи, подписки, доход)
/nodes    — список нод с загрузкой
/ban <telegram_id>   — заблокировать пользователя
/unban <telegram_id> — разблокировать
/user <telegram_id>  — информация о пользователе
```

### Swagger API документация

```
https://ваш_домен.com/api/docs
```

### Перезапуск сервисов

```bash
# Основной сервер
systemctl restart mtproxy-bot
journalctl -u mtproxy-bot -f

# PostgreSQL
docker compose restart

# Нода — mtprotoproxy
systemctl restart mtprotoproxy

# Нода — агент
systemctl restart node-agent
```

### Логи

```bash
# Бот
journalctl -u mtproxy-bot -f

# PostgreSQL
docker compose logs -f postgres

# Нода — mtprotoproxy
journalctl -u mtprotoproxy -f

# Нода — агент
journalctl -u node-agent -f
```

### Отключение ноды (горячее)

```bash
docker compose exec postgres psql -U mtproxy -d mtproxy -c "
UPDATE nodes SET is_active = FALSE WHERE host = 'IP_НОДЫ';
"
```

Нода мгновенно пропадает из бота. Существующие подписки продолжают работать.

### Включение ноды обратно

```bash
docker compose exec postgres psql -U mtproxy -d mtproxy -c "
UPDATE nodes SET is_active = TRUE WHERE host = 'IP_НОДЫ';
"
```

---

## Рекомендации по нагрузке

Для VPS с 2 vCPU / 4 GB RAM / 1 Gbit/s:

| Стратегия | max_users | Комментарий |
|-----------|-----------|-------------|
| Консервативная | 300-500 | Гарантированно комфортно |
| Умеренная | 500-800 | Оптимальный баланс |
| Агрессивная | 800-1500 | Возможны просадки в пиках |

Мониторинг сети на ноде:

```bash
apt install -y vnstat
vnstat -l        # реальное время
vnstat -d        # по дням
vnstat -m        # по месяцам
```

Если пиковая загрузка сети стабильно выше 60-70% — добавлять ноду.

---

## Обновление кода

На основном сервере:

```bash
cd /opt/tg_mtproxy
git pull
source .venv/bin/activate
pip install -e .
systemctl restart mtproxy-bot
```

На нодах (если обновился agent.py или config_manager.py):

```bash
cd /opt/node_agent
scp root@IP_ОСНОВНОГО:/opt/tg_mtproxy/node_agent/agent.py ./
scp root@IP_ОСНОВНОГО:/opt/tg_mtproxy/node_agent/config_manager.py ./
systemctl restart node-agent
```

## Сборка питона 3.12

# 1) Зависимости для сборки
```bash
apt update
apt install -y \
  build-essential wget curl ca-certificates \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
  libffi-dev libncursesw5-dev xz-utils tk-dev libgdbm-dev libnss3-dev \
  liblzma-dev uuid-dev
```

# 2) Сборка и установка Python 3.12 (не ломает системный python)
```bash
cd /usr/src
wget -q https://www.python.org/ftp/python/3.12.8/Python-3.12.8.tgz
tar -xzf Python-3.12.8.tgz
cd Python-3.12.8
./configure --enable-optimizations --with-ensurepip=install
make -j"$(nproc)"
make altinstall
```

# 3) Проверка
```bash
python3.12 --version
```

# 4) Пересоздание venv для node-agent
```bash
cd /opt/node_agent
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
```

# 5) Установка зависимостей
```bash
pip install -U pip setuptools wheel
pip install fastapi "uvicorn[standard]"
```

# 6) Перезапуск сервиса и проверка
```bash
systemctl restart node-agent
systemctl status node-agent --no-pager -l
journalctl -u node-agent -n 80 --no-pager
```


## Замена TLS_DOMAIN
Проверка пингов
```bash
curl -so /dev/null -w "%{time_total}s\n" https://www.cloudflare.com
curl -so /dev/null -w "%{time_total}s\n" https://cdn.jsdelivr.net
curl -so /dev/null -w "%{time_total}s\n" https://www.microsoft.com
```

```bash
cat >> /opt/mtprotoproxy/config.py << 'EOF'

TLS_DOMAIN = "ya.ru"
EOF

systemctl restart mtprotoproxy
journalctl -u mtprotoproxy -n 20 --no-pager
```