-- Поддержка SOCKS5 через Marzban

-- Тип доступа в подписке: mtproto или socks5
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS access_type VARCHAR(20) NOT NULL DEFAULT 'mtproto';

-- Username пользователя в Marzban (NULL для MTProto)
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS marzban_username VARCHAR(100);

-- Тип доступа в платеже (чтобы webhook знал какой тип активировать)
ALTER TABLE payments ADD COLUMN IF NOT EXISTS access_type VARCHAR(20) NOT NULL DEFAULT 'mtproto';

-- Тег SOCKS5 inbound в Marzban для ноды (NULL если SOCKS5 не настроен)
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS socks5_inbound_tag VARCHAR(100);

-- Порт SOCKS5 на ноде
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS socks5_port INTEGER DEFAULT 1080;
