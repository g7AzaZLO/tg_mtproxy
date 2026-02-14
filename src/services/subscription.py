"""Сервис подписок — создание, активация, продление и отключение.

Оркестрирует взаимодействие между репозиториями, Node Manager
и сервисом генерации прокси.
"""

import logging

from src.db import repositories as repo
from src.db.pool import transaction
from src.services.node_manager import NodeManagerService
from src.services.proxy import create_proxy_credentials
from src.utils.crypto import build_proxy_link, build_proxy_link_https

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Управляет жизненным циклом подписок пользователей.

    Attributes:
        _node_manager: Сервис для взаимодействия с нодами.
    """

    def __init__(self, node_manager: NodeManagerService) -> None:
        """Инициализирует сервис подписок.

        Args:
            node_manager: Экземпляр NodeManagerService.
        """
        self._node_manager = node_manager

    async def activate_subscription(
        self,
        *,
        payment_id: int,
        user_id: int,
        plan_id: int,
        node_id: int,
        duration_days: int,
        is_trial: bool = False,
    ) -> dict | None:
        """Активирует подписку: генерирует секрет, добавляет на ноду, сохраняет в БД.

        Args:
            payment_id: ID платежа.
            user_id: Внутренний ID пользователя.
            plan_id: ID тарифного плана.
            node_id: ID выбранной ноды.
            duration_days: Длительность подписки в днях.
            is_trial: Является ли подписка пробной.

        Returns:
            Словарь с данными подписки и ссылками, или None при ошибке.
        """
        node = await repo.node.get_by_id(node_id)
        if not node:
            logger.error("Нода node_id=%d не найдена", node_id)
            return None

        credentials = create_proxy_credentials(node["host"], node["port"])

        # Добавляем секрет на ноду
        added = await self._node_manager.add_secret(
            agent_url=node["agent_url"],
            agent_api_key=node["agent_api_key"],
            secret=credentials["secret"],
            user_id=user_id,
            label=str(user_id),
        )
        if not added:
            logger.error("Не удалось добавить секрет на ноду %s", node["name"])
            return None

        # Создаём подписку и обновляем платёж в одной транзакции
        async with transaction() as conn:
            subscription = await repo.subscription.create(
                conn,
                user_id=user_id,
                node_id=node_id,
                plan_id=plan_id,
                secret=credentials["secret"],
                duration_days=duration_days,
                is_trial=is_trial,
            )
            await repo.payment.set_paid(
                payment_id,
                subscription_id=subscription["id"],
                conn=conn,
            )

        # Если пробная — помечаем
        if is_trial:
            await repo.user.mark_trial_used(user_id)

        logger.info(
            "Подписка #%d активирована для user_id=%d на ноде %s",
            subscription["id"],
            user_id,
            node["name"],
        )

        return {
            **subscription,
            "host": node["host"],
            "port": node["port"],
            "node_name": node["name"],
            "country": node["country"],
            "country_flag": node["country_flag"],
            "tg_link": credentials["tg_link"],
            "https_link": credentials["https_link"],
        }

    async def deactivate_subscription(self, subscription_id: int) -> bool:
        """Деактивирует подписку: удаляет секрет с ноды и обновляет статус.

        Args:
            subscription_id: ID подписки.

        Returns:
            True при успешной деактивации, False при ошибке.
        """
        sub = await repo.subscription.get_by_id(subscription_id)
        if not sub:
            logger.warning("Подписка #%d не найдена", subscription_id)
            return False

        node = await repo.node.get_by_id(sub["node_id"])
        if node:
            removed = await self._node_manager.remove_secret(
                agent_url=node["agent_url"],
                agent_api_key=node["agent_api_key"],
                secret=sub["secret"],
            )
            if not removed:
                logger.warning(
                    "Не удалось удалить секрет с ноды %s для подписки #%d",
                    node["name"],
                    subscription_id,
                )
                # Продолжаем — статус всё равно ставим expired

        await repo.subscription.set_status(subscription_id, "expired")
        logger.info("Подписка #%d деактивирована", subscription_id)
        return True

    async def get_user_proxies(self, user_id: int) -> list[dict]:
        """Возвращает активные прокси пользователя с ссылками.

        Args:
            user_id: Внутренний ID пользователя.

        Returns:
            Список подписок с добавленными полями tg_link и https_link.
        """
        subscriptions = await repo.subscription.get_active_by_user(user_id)
        for sub in subscriptions:
            sub["tg_link"] = build_proxy_link(sub["host"], sub["port"], sub["secret"])
            sub["https_link"] = build_proxy_link_https(sub["host"], sub["port"], sub["secret"])
        return subscriptions
