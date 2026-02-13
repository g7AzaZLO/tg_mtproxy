"""Конфигурация приложения через переменные окружения.

Все настройки загружаются из .env файла с помощью pydantic-settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Настройки Telegram-бота."""

    model_config = SettingsConfigDict(env_prefix="BOT_")

    token: str = Field(description="Токен Telegram-бота от @BotFather")


class DatabaseSettings(BaseSettings):
    """Настройки подключения к PostgreSQL."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = Field(default="localhost", description="Хост PostgreSQL")
    port: int = Field(default=5432, description="Порт PostgreSQL")
    name: str = Field(default="mtproxy", description="Имя базы данных")
    user: str = Field(default="mtproxy", description="Пользователь БД")
    password: str = Field(description="Пароль БД")
    min_pool_size: int = Field(default=5, description="Минимальный размер пула соединений")
    max_pool_size: int = Field(default=20, description="Максимальный размер пула соединений")

    @property
    def dsn(self) -> str:
        """Строка подключения PostgreSQL DSN."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class CryptoCloudSettings(BaseSettings):
    """Настройки платёжной системы CryptoCloud."""

    model_config = SettingsConfigDict(env_prefix="CRYPTOCLOUD_")

    api_key: str = Field(description="API-ключ CryptoCloud")
    shop_id: str = Field(description="Идентификатор магазина в CryptoCloud")
    secret_key: str = Field(
        description="SECRET KEY проекта CryptoCloud (для верификации JWT в postback)"
    )
    base_url: str = Field(
        default="https://api.cryptocloud.plus/v2",
        description="Базовый URL API CryptoCloud",
    )
    currency: str = Field(default="USD", description="Валюта по умолчанию")


class WebSettings(BaseSettings):
    """Настройки веб-сервера (FastAPI)."""

    model_config = SettingsConfigDict(env_prefix="WEB_")

    host: str = Field(default="0.0.0.0", description="Хост веб-сервера")
    port: int = Field(default=8080, description="Порт веб-сервера")
    base_url: str = Field(description="Публичный URL для webhook-ов")


class AdminSettings(BaseSettings):
    """Настройки админ-панели."""

    model_config = SettingsConfigDict(env_prefix="ADMIN_")

    username: str = Field(default="admin", description="Логин администратора")
    password: str = Field(description="Пароль администратора")


class JWTSettings(BaseSettings):
    """Настройки JWT-токенов."""

    model_config = SettingsConfigDict(env_prefix="JWT_")

    secret: str = Field(description="Секретный ключ для подписи JWT")
    algorithm: str = Field(default="HS256", description="Алгоритм подписи JWT")
    expire_minutes: int = Field(default=1440, description="Время жизни токена в минутах (24ч)")


class ServiceSettings(BaseSettings):
    """Настройки бизнес-логики сервиса."""

    trial_duration_days: int = Field(default=2, description="Длительность пробного периода")
    notify_before_days: str = Field(
        default="3,1",
        description="Дни до окончания подписки для отправки напоминаний (через запятую)",
    )

    @property
    def notify_days_list(self) -> list[int]:
        """Список дней для отправки напоминаний."""
        return [int(d.strip()) for d in self.notify_before_days.split(",")]


class Settings(BaseSettings):
    """Корневой объект конфигурации, объединяющий все настройки."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot: BotSettings = Field(default_factory=BotSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    cryptocloud: CryptoCloudSettings = Field(default_factory=CryptoCloudSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    service: ServiceSettings = Field(default_factory=ServiceSettings)


def get_settings() -> Settings:
    """Создаёт и возвращает объект настроек.

    Returns:
        Объект Settings, заполненный из переменных окружения и .env файла.
    """
    return Settings()
