"""Клиент Marzban Panel API для управления SOCKS5-пользователями.

Обеспечивает аутентификацию, создание / удаление / получение пользователей,
а также парсинг SOCKS5-ссылок из ответа Marzban.
"""

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from src.config import MarzbanSettings

logger = logging.getLogger(__name__)

TOKEN_REFRESH_MARGIN = 60  # секунд до истечения для обновления


@dataclass
class Socks5Credentials:
    """Данные для подключения к SOCKS5-прокси.

    Attributes:
        host: IP-адрес или домен сервера.
        port: Порт SOCKS5.
        username: Логин.
        password: Пароль.
    """

    host: str
    port: int
    username: str
    password: str

    @property
    def uri(self) -> str:
        """Строка подключения ``socks5://user:pass@host:port``."""
        return f"socks5://{self.username}:{self.password}@{self.host}:{self.port}"


class MarzbanService:
    """HTTP-клиент для Marzban Panel REST API.

    Attributes:
        _base_url: Базовый URL панели.
        _admin_username: Логин администратора.
        _admin_password: Пароль администратора.
        _client: Асинхронный HTTP-клиент.
        _token: Текущий access_token.
        _token_expires_at: Время истечения токена (unix timestamp).
    """

    def __init__(self, settings: MarzbanSettings) -> None:
        """Инициализирует клиент Marzban API.

        Args:
            settings: Настройки подключения к Marzban Panel.
        """
        self._base_url = settings.base_url.rstrip("/")
        self._admin_username = settings.admin_username
        self._admin_password = settings.admin_password
        self._client = httpx.AsyncClient(timeout=15.0)
        self._token: str | None = None
        self._token_expires_at: float = 0

    async def close(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def _ensure_token(self) -> str:
        """Получает или обновляет access_token.

        Returns:
            Актуальный access_token.

        Raises:
            httpx.HTTPStatusError: При ошибке аутентификации.
        """
        if self._token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN:
            return self._token

        resp = await self._client.post(
            f"{self._base_url}/api/admin/token",
            data={
                "username": self._admin_username,
                "password": self._admin_password,
                "grant_type": "password",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Marzban токены живут ~24ч; ставим 23ч для безопасности
        self._token_expires_at = time.time() + 23 * 3600
        logger.info("Marzban token обновлён")
        return self._token

    async def _headers(self) -> dict[str, str]:
        """Возвращает заголовки авторизации.

        Returns:
            Словарь с ``Authorization: Bearer ...``.
        """
        token = await self._ensure_token()
        return {"Authorization": f"Bearer {token}"}

    async def create_user(
        self,
        username: str,
        expire_timestamp: int,
        inbound_tag: str,
    ) -> dict:
        """Создаёт SOCKS5-пользователя в Marzban.

        Args:
            username: Уникальное имя пользователя (3-32 символа).
            expire_timestamp: UTC timestamp истечения (0 = бессрочно).
            inbound_tag: Тег inbound для привязки к конкретной ноде.

        Returns:
            Полный ответ Marzban API (включая links, proxies, и т.д.).

        Raises:
            httpx.HTTPStatusError: При ошибке создания.
        """
        headers = await self._headers()
        body = {
            "username": username,
            "proxies": {"socks5": {}},
            "inbounds": {"socks5": [inbound_tag]},
            "expire": expire_timestamp,
            "data_limit": 0,
            "status": "active",
        }
        resp = await self._client.post(
            f"{self._base_url}/api/user",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        logger.info("Marzban user '%s' создан (inbound=%s)", username, inbound_tag)
        return resp.json()

    async def get_user(self, username: str) -> dict | None:
        """Получает данные пользователя из Marzban.

        Args:
            username: Имя пользователя в Marzban.

        Returns:
            Словарь с данными пользователя или None если не найден.
        """
        headers = await self._headers()
        resp = await self._client.get(
            f"{self._base_url}/api/user/{username}",
            headers=headers,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def delete_user(self, username: str) -> bool:
        """Удаляет пользователя из Marzban.

        Args:
            username: Имя пользователя в Marzban.

        Returns:
            True при успешном удалении.
        """
        headers = await self._headers()
        resp = await self._client.delete(
            f"{self._base_url}/api/user/{username}",
            headers=headers,
        )
        if resp.status_code == 404:
            logger.warning("Marzban user '%s' не найден при удалении", username)
            return False
        resp.raise_for_status()
        logger.info("Marzban user '%s' удалён", username)
        return True

    async def disable_user(self, username: str) -> bool:
        """Отключает пользователя в Marzban (status=disabled).

        Args:
            username: Имя пользователя в Marzban.

        Returns:
            True при успешном отключении.
        """
        headers = await self._headers()
        resp = await self._client.put(
            f"{self._base_url}/api/user/{username}",
            json={"status": "disabled"},
            headers=headers,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        logger.info("Marzban user '%s' отключён", username)
        return True

    async def get_socks5_credentials(self, username: str) -> Socks5Credentials | None:
        """Получает SOCKS5-credentials пользователя.

        Парсит первую socks5-ссылку из поля ``links`` в ответе Marzban API.

        Args:
            username: Имя пользователя в Marzban.

        Returns:
            Socks5Credentials или None если пользователь не найден.
        """
        user_data = await self.get_user(username)
        if not user_data:
            return None

        for link in user_data.get("links", []):
            creds = parse_socks5_link(link)
            if creds:
                return creds

        logger.warning("Не найдена SOCKS5 ссылка для user '%s'", username)
        return None


def parse_socks5_link(link: str) -> Socks5Credentials | None:
    """Парсит строку ``socks5://user:pass@host:port`` в credentials.

    Args:
        link: Строка SOCKS5-ссылки.

    Returns:
        Socks5Credentials или None при невалидном формате.
    """
    if not link.startswith("socks"):
        return None
    try:
        parsed = urlparse(link)
        if not all([parsed.hostname, parsed.port, parsed.username, parsed.password]):
            return None
        return Socks5Credentials(
            host=parsed.hostname,
            port=parsed.port,
            username=parsed.username,
            password=parsed.password,
        )
    except Exception:
        logger.debug("Не удалось распарсить SOCKS5 link: %s", link)
        return None
