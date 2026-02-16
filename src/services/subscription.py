"""Сервис подписок — создание, активация, продление и отключение.

Оркестрирует взаимодействие между репозиториями, Node Manager,
Marzban и сервисом генерации прокси.
"""

import logging
from datetime import datetime, timedelta, timezone

from src.db import repositories as repo
from src.db.pool import transaction
from src.services.marzban import MarzbanService
from src.services.node_manager import NodeManagerService
from src.services.proxy import create_proxy_credentials
from src.utils.crypto import build_proxy_link, build_proxy_link_https, generate_secret

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Управляет жизненным циклом подписок пользователей.

    Attributes:
        _node_manager: Сервис для взаимодействия с нодами (MTProto).
        _marzban: Сервис для взаимодействия с Marzban Panel (SOCKS5).
    """

    def __init__(
        self,
        node_manager: NodeManagerService,
        marzban: MarzbanService | None = None,
    ) -> None:
        """Инициализирует сервис подписок.

        Args:
            node_manager: Экземпляр NodeManagerService.
            marzban: Экземпляр MarzbanService (None если SOCKS5 не настроен).
        """
        self._node_manager = node_manager
        self._marzban = marzban

    # ------------------------------------------------------------------
    # Активация
    # ------------------------------------------------------------------

    async def activate_subscription(
        self,
        *,
        payment_id: int,
        user_id: int,
        plan_id: int,
        node_id: int,
        duration_days: int,
        is_trial: bool = False,
        access_type: str = "mtproto",
    ) -> dict | None:
        """Активирует подписку: создаёт доступ на ноде и сохраняет в БД.

        Args:
            payment_id: ID платежа.
            user_id: Внутренний ID пользователя.
            plan_id: ID тарифного плана.
            node_id: ID выбранной ноды.
            duration_days: Длительность подписки в днях.
            is_trial: Является ли подписка пробной.
            access_type: Тип доступа — ``mtproto`` или ``socks5``.

        Returns:
            Словарь с данными подписки и credentials, или None при ошибке.
        """
        if access_type == "socks5":
            return await self._activate_socks5(
                payment_id=payment_id,
                user_id=user_id,
                plan_id=plan_id,
                node_id=node_id,
                duration_days=duration_days,
                is_trial=is_trial,
            )
        return await self._activate_mtproto(
            payment_id=payment_id,
            user_id=user_id,
            plan_id=plan_id,
            node_id=node_id,
            duration_days=duration_days,
            is_trial=is_trial,
        )

    async def _activate_mtproto(
        self,
        *,
        payment_id: int,
        user_id: int,
        plan_id: int,
        node_id: int,
        duration_days: int,
        is_trial: bool,
    ) -> dict | None:
        """Активация MTProto-подписки (текущая логика).

        Args:
            payment_id: ID платежа.
            user_id: Внутренний ID пользователя.
            plan_id: ID тарифного плана.
            node_id: ID ноды.
            duration_days: Длительность в днях.
            is_trial: Пробная подписка.

        Returns:
            Словарь с данными подписки и ссылками, или None.
        """
        node = await repo.node.get_by_id(node_id)
        if not node:
            logger.error("Нода node_id=%d не найдена", node_id)
            return None

        credentials = create_proxy_credentials(node["host"], node["port"])

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

        async with transaction() as conn:
            subscription = await repo.subscription.create(
                conn,
                user_id=user_id,
                node_id=node_id,
                plan_id=plan_id,
                secret=credentials["secret"],
                duration_days=duration_days,
                is_trial=is_trial,
                access_type="mtproto",
            )
            await repo.payment.set_paid(
                payment_id, subscription_id=subscription["id"], conn=conn,
            )

        if is_trial:
            await repo.user.mark_trial_used(user_id)

        logger.info(
            "MTProto подписка #%d активирована для user_id=%d на ноде %s",
            subscription["id"], user_id, node["name"],
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

    async def _activate_socks5(
        self,
        *,
        payment_id: int,
        user_id: int,
        plan_id: int,
        node_id: int,
        duration_days: int,
        is_trial: bool,
    ) -> dict | None:
        """Активация SOCKS5-подписки через Marzban.

        Args:
            payment_id: ID платежа.
            user_id: Внутренний ID пользователя.
            plan_id: ID тарифного плана.
            node_id: ID ноды.
            duration_days: Длительность в днях.
            is_trial: Пробная подписка.

        Returns:
            Словарь с данными подписки и SOCKS5 credentials, или None.
        """
        if not self._marzban:
            logger.error("MarzbanService не настроен, SOCKS5 недоступен")
            return None

        node = await repo.node.get_by_id(node_id)
        if not node:
            logger.error("Нода node_id=%d не найдена", node_id)
            return None

        if not node.get("socks5_inbound_tag"):
            logger.error("Нода %s не имеет socks5_inbound_tag", node["name"])
            return None

        expire_ts = int(
            (datetime.now(timezone.utc) + timedelta(days=duration_days)).timestamp()
        )
        marzban_username = f"s5_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"

        try:
            await self._marzban.create_user(
                username=marzban_username,
                expire_timestamp=expire_ts,
                inbound_tag=node["socks5_inbound_tag"],
            )
        except Exception:
            logger.exception(
                "Не удалось создать SOCKS5 user '%s' в Marzban", marzban_username,
            )
            return None

        async with transaction() as conn:
            subscription = await repo.subscription.create(
                conn,
                user_id=user_id,
                node_id=node_id,
                plan_id=plan_id,
                secret="",
                duration_days=duration_days,
                is_trial=is_trial,
                access_type="socks5",
                marzban_username=marzban_username,
            )
            await repo.payment.set_paid(
                payment_id, subscription_id=subscription["id"], conn=conn,
            )

        if is_trial:
            await repo.user.mark_trial_used(user_id)

        creds = await self._marzban.get_socks5_credentials(marzban_username)

        logger.info(
            "SOCKS5 подписка #%d активирована для user_id=%d на ноде %s",
            subscription["id"], user_id, node["name"],
        )

        result = {
            **subscription,
            "node_name": node["name"],
            "country": node["country"],
            "country_flag": node["country_flag"],
        }
        if creds:
            result.update({
                "socks5_host": creds.host,
                "socks5_port": creds.port,
                "socks5_username": creds.username,
                "socks5_password": creds.password,
                "socks5_uri": creds.uri,
            })
        return result

    # ------------------------------------------------------------------
    # Деактивация
    # ------------------------------------------------------------------

    async def deactivate_subscription(self, subscription_id: int) -> bool:
        """Деактивирует подписку: удаляет доступ и обновляет статус.

        Args:
            subscription_id: ID подписки.

        Returns:
            True при успешной деактивации, False при ошибке.
        """
        sub = await repo.subscription.get_by_id(subscription_id)
        if not sub:
            logger.warning("Подписка #%d не найдена", subscription_id)
            return False

        if sub.get("access_type") == "socks5":
            await self._deactivate_socks5(sub)
        else:
            await self._deactivate_mtproto(sub, subscription_id)

        await repo.subscription.set_status(subscription_id, "expired")
        logger.info("Подписка #%d деактивирована", subscription_id)
        return True

    async def _deactivate_mtproto(self, sub: dict, subscription_id: int) -> None:
        """Удаляет MTProto-секрет с ноды.

        Args:
            sub: Данные подписки.
            subscription_id: ID подписки (для логирования).
        """
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
                    node["name"], subscription_id,
                )

    async def _deactivate_socks5(self, sub: dict) -> None:
        """Удаляет SOCKS5-пользователя из Marzban.

        Args:
            sub: Данные подписки.
        """
        if self._marzban and sub.get("marzban_username"):
            await self._marzban.delete_user(sub["marzban_username"])

    # ------------------------------------------------------------------
    # Ротация ключа
    # ------------------------------------------------------------------

    async def rotate_key(
        self,
        subscription_id: int,
        new_country: str,
    ) -> dict:
        """Меняет секрет/credentials подписки и опционально ноду.

        Args:
            subscription_id: ID подписки.
            new_country: Страна новой ноды.

        Returns:
            Словарь с результатом (status + данные).
        """
        sub = await repo.subscription.get_by_id(subscription_id)
        if not sub:
            return {"status": "error", "detail": "Подписка не найдена"}

        if sub.get("last_key_change"):
            cooldown_until = sub["last_key_change"] + timedelta(hours=24)
            if datetime.now(timezone.utc) < cooldown_until:
                return {"status": "cooldown"}

        if sub.get("access_type") == "socks5":
            return await self._rotate_socks5(sub, subscription_id, new_country)
        return await self._rotate_mtproto(sub, subscription_id, new_country)

    async def _rotate_mtproto(
        self, sub: dict, subscription_id: int, new_country: str,
    ) -> dict:
        """Ротация MTProto-ключа.

        Args:
            sub: Данные текущей подписки.
            subscription_id: ID подписки.
            new_country: Страна новой ноды.

        Returns:
            Словарь с результатом ротации.
        """
        new_node = await repo.node.get_least_loaded_node(new_country)
        if not new_node:
            return {"status": "no_slots"}

        old_node = await repo.node.get_by_id(sub["node_id"])
        if old_node:
            await self._node_manager.remove_secret(
                agent_url=old_node["agent_url"],
                agent_api_key=old_node["agent_api_key"],
                secret=sub["secret"],
            )

        new_secret = generate_secret()
        added = await self._node_manager.add_secret(
            agent_url=new_node["agent_url"],
            agent_api_key=new_node["agent_api_key"],
            secret=new_secret,
            user_id=sub["user_id"],
            label=str(sub["user_id"]),
        )
        if not added:
            logger.error(
                "Не удалось добавить секрет на ноду %s при ротации #%d",
                new_node["name"], subscription_id,
            )
            return {"status": "error", "detail": "Не удалось добавить секрет"}

        await repo.subscription.update_secret_and_node(
            subscription_id, new_secret=new_secret, new_node_id=new_node["id"],
        )

        logger.info(
            "MTProto ключ #%d заменён, нода: %s -> %s",
            subscription_id,
            old_node["name"] if old_node else "?",
            new_node["name"],
        )

        return {
            "status": "ok",
            "access_type": "mtproto",
            "host": new_node["host"],
            "port": new_node["port"],
            "node_name": new_node["name"],
            "country_flag": new_node["country_flag"],
            "tg_link": build_proxy_link(new_node["host"], new_node["port"], new_secret),
            "https_link": build_proxy_link_https(
                new_node["host"], new_node["port"], new_secret
            ),
        }

    async def _rotate_socks5(
        self, sub: dict, subscription_id: int, new_country: str,
    ) -> dict:
        """Ротация SOCKS5 — удаляет старого пользователя, создаёт нового.

        Args:
            sub: Данные текущей подписки.
            subscription_id: ID подписки.
            new_country: Страна новой ноды.

        Returns:
            Словарь с результатом ротации.
        """
        if not self._marzban:
            return {"status": "error", "detail": "SOCKS5 не настроен"}

        new_node = await repo.node.get_least_loaded_node(new_country)
        if not new_node or not new_node.get("socks5_inbound_tag"):
            return {"status": "no_slots"}

        # Удалить старого пользователя
        if sub.get("marzban_username"):
            await self._marzban.delete_user(sub["marzban_username"])

        # Создать нового
        expire_ts = int(sub["expires_at"].timestamp())
        new_username = f"s5_{sub['user_id']}_{int(datetime.now(timezone.utc).timestamp())}"

        try:
            await self._marzban.create_user(
                username=new_username,
                expire_timestamp=expire_ts,
                inbound_tag=new_node["socks5_inbound_tag"],
            )
        except Exception:
            logger.exception("Не удалось создать SOCKS5 user при ротации #%d", subscription_id)
            return {"status": "error", "detail": "Ошибка создания SOCKS5"}

        await repo.subscription.update_secret_and_node(
            subscription_id, new_secret="", new_node_id=new_node["id"],
        )
        # Обновить marzban_username в БД
        from src.db.pool import acquire

        async with acquire() as conn:
            await conn.execute(
                "UPDATE subscriptions SET marzban_username = $1 WHERE id = $2",
                new_username, subscription_id,
            )

        creds = await self._marzban.get_socks5_credentials(new_username)

        logger.info(
            "SOCKS5 ключ #%d заменён, нода: -> %s", subscription_id, new_node["name"],
        )

        result: dict = {
            "status": "ok",
            "access_type": "socks5",
            "node_name": new_node["name"],
            "country_flag": new_node["country_flag"],
        }
        if creds:
            result.update({
                "socks5_host": creds.host,
                "socks5_port": creds.port,
                "socks5_username": creds.username,
                "socks5_password": creds.password,
                "socks5_uri": creds.uri,
            })
        return result

    # ------------------------------------------------------------------
    # Список прокси пользователя
    # ------------------------------------------------------------------

    async def get_user_proxies(self, user_id: int) -> list[dict]:
        """Возвращает активные прокси пользователя с credentials.

        Args:
            user_id: Внутренний ID пользователя.

        Returns:
            Список подписок с данными для подключения.
        """
        subscriptions = await repo.subscription.get_active_by_user(user_id)
        for sub in subscriptions:
            if sub.get("access_type") == "socks5":
                await self._enrich_socks5(sub)
            else:
                sub["tg_link"] = build_proxy_link(
                    sub["host"], sub["port"], sub["secret"]
                )
                sub["https_link"] = build_proxy_link_https(
                    sub["host"], sub["port"], sub["secret"]
                )
        return subscriptions

    async def _enrich_socks5(self, sub: dict) -> None:
        """Дополняет подписку SOCKS5-credentials из Marzban.

        Args:
            sub: Словарь подписки (мутируется in-place).
        """
        if not self._marzban or not sub.get("marzban_username"):
            return
        creds = await self._marzban.get_socks5_credentials(sub["marzban_username"])
        if creds:
            sub["socks5_host"] = creds.host
            sub["socks5_port"] = creds.port
            sub["socks5_username"] = creds.username
            sub["socks5_password"] = creds.password
            sub["socks5_uri"] = creds.uri
