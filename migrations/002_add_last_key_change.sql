-- Поле для трекинга последней смены ключа (лимит: 1 раз в сутки)
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS last_key_change TIMESTAMPTZ;
