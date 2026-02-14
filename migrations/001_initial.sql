-- Начальная миграция: создание всех таблиц, индексов и начальных данных.
-- Применяется автоматически при первом запуске PostgreSQL через docker-compose.

BEGIN;

-- ============================================================
-- Таблица пользователей
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT NOT NULL UNIQUE,
    username        VARCHAR(255),
    first_name      VARCHAR(255),
    is_banned       BOOLEAN NOT NULL DEFAULT FALSE,
    used_trial      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users (telegram_id);

-- ============================================================
-- Тарифные планы
-- ============================================================
CREATE TABLE IF NOT EXISTS plans (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    duration_days   INTEGER NOT NULL,
    price_usd       NUMERIC(10, 2) NOT NULL,
    is_trial        BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- ============================================================
-- Серверные ноды с MTProxy
-- ============================================================
CREATE TABLE IF NOT EXISTS nodes (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    host            VARCHAR(255) NOT NULL,
    port            INTEGER NOT NULL DEFAULT 443,
    country         VARCHAR(100) NOT NULL,
    country_flag    VARCHAR(10) NOT NULL DEFAULT '',
    agent_url       VARCHAR(500) NOT NULL,
    agent_api_key   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    max_users       INTEGER NOT NULL DEFAULT 500
);

-- ============================================================
-- Подписки пользователей
-- ============================================================
CREATE TYPE subscription_status AS ENUM (
    'pending',
    'active',
    'expiring',
    'expired',
    'cancelled'
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id         INTEGER NOT NULL REFERENCES nodes(id) ON DELETE RESTRICT,
    plan_id         INTEGER NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
    secret          VARCHAR(66) NOT NULL,
    starts_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    status          subscription_status NOT NULL DEFAULT 'pending',
    notified_3d     BOOLEAN NOT NULL DEFAULT FALSE,
    notified_1d     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_node_id ON subscriptions (node_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions (status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_expires_at ON subscriptions (expires_at);
CREATE INDEX IF NOT EXISTS idx_subscriptions_secret ON subscriptions (secret);

-- ============================================================
-- Платежи
-- ============================================================
CREATE TYPE payment_status AS ENUM (
    'created',
    'success',
    'paid',
    'expired',
    'cancelled'
);

CREATE TABLE IF NOT EXISTS payments (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id     BIGINT REFERENCES subscriptions(id) ON DELETE SET NULL,
    plan_id             INTEGER NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
    node_id             INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    amount_usd          NUMERIC(10, 2) NOT NULL,
    cryptocloud_uuid    VARCHAR(100),
    cryptocloud_link    VARCHAR(500),
    status              payment_status NOT NULL DEFAULT 'created',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);
CREATE INDEX IF NOT EXISTS idx_payments_cryptocloud_uuid ON payments (cryptocloud_uuid);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);

-- ============================================================
-- Таблица применённых миграций
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(100) PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Начальные тарифные планы
-- ============================================================
INSERT INTO plans (name, duration_days, price_usd, is_trial) VALUES
    ('Пробный (3 дня)',  3,  0.00, TRUE),
    ('7 дней',           7,  1.50, FALSE),
    ('30 дней',          30, 3.00, FALSE),
    ('90 дней',          90, 7.00, FALSE)
ON CONFLICT DO NOTHING;

-- Отметка о применении миграции
INSERT INTO schema_migrations (version) VALUES ('001_initial')
ON CONFLICT DO NOTHING;

COMMIT;
