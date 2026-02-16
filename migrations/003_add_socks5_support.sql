-- Поддержка SOCKS5 через 3proxy

-- Тип доступа в подписке: mtproto или socks5
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS access_type VARCHAR(20) NOT NULL DEFAULT 'mtproto';

-- Пароль SOCKS5 (переиспользуем поле marzban_username для хранения пароля)
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS marzban_username VARCHAR(100);

-- Тип доступа в платеже (чтобы webhook знал какой тип активировать)
ALTER TABLE payments ADD COLUMN IF NOT EXISTS access_type VARCHAR(20) NOT NULL DEFAULT 'mtproto';

-- Порт SOCKS5 на ноде (по умолчанию 1080)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS socks5_port INTEGER DEFAULT 1080;
