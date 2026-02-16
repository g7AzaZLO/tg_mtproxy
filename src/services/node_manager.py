"""Сервис управления нодами — HTTP-клиент к Node Agent API.

Отправляет команды на добавление/удаление секретов
и проверяет состояние нод.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class NodeManagerService:
    """Управляет взаимодействием с API-агентами на нодах MTProxy.

    Каждая нода имеет свой agent_url и agent_api_key.
    """

    def __init__(self, timeout: float = 15.0) -> None:
        """Инициализирует сервис.

        Args:
            timeout: Таймаут HTTP-запросов к агентам (секунды).
        """
        self._timeout = timeout

    async def add_secret(
        self,
        *,
        agent_url: str,
        agent_api_key: str,
        secret: str,
        user_id: int,
        label: str = "",
    ) -> bool:
        """Добавляет секрет на ноду через Node Agent API.

        Args:
            agent_url: Базовый URL агента (например, http://1.2.3.4:9090).
            agent_api_key: API-ключ для авторизации на агенте.
            secret: DD-секрет для добавления.
            user_id: ID пользователя (для логирования на ноде).
            label: Метка пользователя.

        Returns:
            True при успешном добавлении, False при ошибке.
        """
        try:
            async with self._make_client(agent_url, agent_api_key) as client:
                response = await client.post(
                    "/secrets/add",
                    json={"secret": secret, "user_id": user_id, "label": label},
                )
                if response.status_code == 200:
                    logger.info("Секрет добавлен на ноду %s для user_id=%d", agent_url, user_id)
                    return True
                logger.error(
                    "Ошибка добавления секрета на %s: %d %s",
                    agent_url,
                    response.status_code,
                    response.text,
                )
                return False
        except httpx.HTTPError:
            logger.exception("HTTP ошибка при добавлении секрета на %s", agent_url)
            return False

    async def remove_secret(
        self,
        *,
        agent_url: str,
        agent_api_key: str,
        secret: str,
    ) -> bool:
        """Удаляет секрет с ноды через Node Agent API.

        Args:
            agent_url: Базовый URL агента.
            agent_api_key: API-ключ для авторизации.
            secret: DD-секрет для удаления.

        Returns:
            True при успешном удалении, False при ошибке.
        """
        try:
            async with self._make_client(agent_url, agent_api_key) as client:
                response = await client.post(
                    "/secrets/remove",
                    json={"secret": secret},
                )
                if response.status_code == 200:
                    logger.info("Секрет удалён с ноды %s", agent_url)
                    return True
                logger.error(
                    "Ошибка удаления секрета с %s: %d %s",
                    agent_url,
                    response.status_code,
                    response.text,
                )
                return False
        except httpx.HTTPError:
            logger.exception("HTTP ошибка при удалении секрета с %s", agent_url)
            return False

    async def add_socks5_user(
        self,
        *,
        agent_url: str,
        agent_api_key: str,
        username: str,
        password: str,
    ) -> bool:
        """Добавляет SOCKS5-пользователя на ноду через Node Agent API.

        Args:
            agent_url: Базовый URL агента.
            agent_api_key: API-ключ для авторизации.
            username: Логин SOCKS5.
            password: Пароль SOCKS5.

        Returns:
            True при успешном добавлении, False при ошибке.
        """
        try:
            async with self._make_client(agent_url, agent_api_key) as client:
                response = await client.post(
                    "/socks5/add",
                    json={"username": username, "password": password},
                )
                if response.status_code == 200:
                    logger.info("SOCKS5 user добавлен на ноду %s: %s", agent_url, username)
                    return True
                logger.error(
                    "Ошибка добавления SOCKS5 user на %s: %d %s",
                    agent_url, response.status_code, response.text,
                )
                return False
        except httpx.HTTPError:
            logger.exception("HTTP ошибка при добавлении SOCKS5 user на %s", agent_url)
            return False

    async def remove_socks5_user(
        self,
        *,
        agent_url: str,
        agent_api_key: str,
        username: str,
    ) -> bool:
        """Удаляет SOCKS5-пользователя с ноды через Node Agent API.

        Args:
            agent_url: Базовый URL агента.
            agent_api_key: API-ключ для авторизации.
            username: Логин SOCKS5 для удаления.

        Returns:
            True при успешном удалении, False при ошибке.
        """
        try:
            async with self._make_client(agent_url, agent_api_key) as client:
                response = await client.post(
                    "/socks5/remove",
                    json={"username": username},
                )
                if response.status_code == 200:
                    logger.info("SOCKS5 user удалён с ноды %s: %s", agent_url, username)
                    return True
                logger.error(
                    "Ошибка удаления SOCKS5 user с %s: %d %s",
                    agent_url, response.status_code, response.text,
                )
                return False
        except httpx.HTTPError:
            logger.exception("HTTP ошибка при удалении SOCKS5 user с %s", agent_url)
            return False

    async def health_check(
        self,
        *,
        agent_url: str,
        agent_api_key: str,
    ) -> dict[str, Any] | None:
        """Проверяет состояние ноды через Node Agent API.

        Args:
            agent_url: Базовый URL агента.
            agent_api_key: API-ключ для авторизации.

        Returns:
            Словарь с данными о состоянии или None при ошибке.
        """
        try:
            async with self._make_client(agent_url, agent_api_key) as client:
                response = await client.get("/health")
                if response.status_code == 200:
                    return response.json()
                return None
        except httpx.HTTPError:
            logger.warning("Нода %s недоступна", agent_url)
            return None

    def _make_client(
        self,
        agent_url: str,
        agent_api_key: str,
    ) -> httpx.AsyncClient:
        """Создаёт HTTP-клиент для запроса к конкретному агенту.

        Args:
            agent_url: Базовый URL агента.
            agent_api_key: API-ключ.

        Returns:
            Сконфигурированный AsyncClient.
        """
        return httpx.AsyncClient(
            base_url=agent_url,
            headers={"X-API-Key": agent_api_key},
            timeout=self._timeout,
        )
