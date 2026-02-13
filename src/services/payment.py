"""Сервис оплаты — интеграция с CryptoCloud API v2.

Создание инвойсов и обработка webhook-ов (postback).
Документация: https://docs.cryptocloud.plus/ru/api-reference-v2/
"""

import logging
from typing import Any

import httpx

from src.config import CryptoCloudSettings

logger = logging.getLogger(__name__)


class PaymentService:
    """Клиент для работы с CryptoCloud API v2.

    Attributes:
        _settings: Настройки CryptoCloud.
        _client: Async HTTP клиент.
    """

    def __init__(self, settings: CryptoCloudSettings) -> None:
        """Инициализирует сервис оплаты.

        Args:
            settings: Настройки CryptoCloud (api_key, shop_id, base_url).
        """
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers={
                "Authorization": f"Token {settings.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def create_invoice(
        self,
        *,
        amount: float,
        order_id: str,
        currency: str | None = None,
    ) -> dict[str, Any]:
        """Создаёт инвойс (счёт на оплату) в CryptoCloud.

        Args:
            amount: Сумма платежа.
            order_id: Уникальный идентификатор заказа в нашей системе (payment.id).
            currency: Валюта (по умолчанию из настроек).

        Returns:
            Словарь с полями uuid и link из ответа CryptoCloud.

        Raises:
            PaymentError: При ошибке создания инвойса.
        """
        payload = {
            "shop_id": self._settings.shop_id,
            "amount": amount,
            "currency": currency or self._settings.currency,
            "order_id": order_id,
        }

        try:
            response = await self._client.post("/invoice/create", json=payload)
            data = response.json()

            if response.status_code != 200 or data.get("status") != "success":
                error_detail = data.get("result", data)
                logger.error("Ошибка создания инвойса CryptoCloud: %s", error_detail)
                raise PaymentError(f"Ошибка CryptoCloud: {error_detail}")

            result = data["result"]
            logger.info(
                "Инвойс создан: uuid=%s, amount=%s %s",
                result["uuid"],
                amount,
                currency or self._settings.currency,
            )
            return {
                "uuid": result["uuid"],
                "link": result["link"],
            }

        except httpx.HTTPError as exc:
            logger.exception("HTTP ошибка при создании инвойса")
            raise PaymentError(f"Ошибка соединения с CryptoCloud: {exc}") from exc

    async def close(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()


class PaymentError(Exception):
    """Ошибка при работе с платёжной системой."""
