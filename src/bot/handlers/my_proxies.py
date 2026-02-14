"""Хэндлер раздела «Мои прокси» — просмотр, ротация ключа и смена локации."""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.bot.callbacks.factories import MyProxiesCallback, RotateCallback
from src.bot.keyboards.menus import (
    main_menu_keyboard,
    my_proxies_keyboard,
    proxy_link_keyboard,
    rotate_locations_keyboard,
)
from src.db import repositories as repo
from src.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

router = Router(name="my_proxies")


@router.callback_query(MyProxiesCallback.filter(F.action == "list"))
async def list_proxies(
    callback: CallbackQuery,
    db_user: dict,
    subscription_service: SubscriptionService,
) -> None:
    """Показывает список активных прокси пользователя.

    Args:
        callback: Callback-запрос.
        db_user: Данные пользователя из БД.
        subscription_service: Сервис подписок.
    """
    subscriptions = await subscription_service.get_user_proxies(db_user["id"])

    if not subscriptions:
        await callback.message.edit_text(
            "У вас нет активных прокси.\n\n"
            "Нажмите «Купить прокси» для приобретения.",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    text_parts = ["<b>Ваши активные прокси:</b>\n"]
    for i, sub in enumerate(subscriptions, start=1):
        expires = sub["expires_at"].strftime("%d.%m.%Y %H:%M")
        text_parts.append(
            f"{i}. {sub.get('country_flag', '')} <b>{sub.get('node_name', 'Сервер')}</b>\n"
            f"   Тариф: {sub.get('plan_name', '—')}\n"
            f"   До: {expires}\n"
            f"   <code>{sub['https_link']}</code>\n"
        )

    text_parts.append("\nНажмите кнопку сервера для подключения прокси:")

    await callback.message.edit_text(
        "\n".join(text_parts),
        reply_markup=my_proxies_keyboard(subscriptions),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MyProxiesCallback.filter(F.action == "rotate"))
async def start_rotate(
    callback: CallbackQuery,
    callback_data: MyProxiesCallback,
) -> None:
    """Начало ротации ключа — показывает выбор страны.

    Args:
        callback: Callback-запрос.
        callback_data: Данные callback с subscription_id.
    """
    sub = await repo.subscription.get_by_id(callback_data.subscription_id)
    if not sub or sub["status"] not in ("active", "expiring"):
        await callback.answer("Подписка не найдена или неактивна.", show_alert=True)
        return

    node = await repo.node.get_by_id(sub["node_id"])
    current_country = node["country"] if node else ""

    countries = await repo.node.get_available_countries()
    if not countries:
        await callback.answer("Нет доступных локаций.", show_alert=True)
        return

    await callback.message.edit_text(
        "🔄 <b>Смена ключа</b>\n\n"
        "Выберите локацию для нового ключа.\n"
        "Можно выбрать текущую (отмечена ✓) или другую страну.\n\n"
        "⚠️ Доступно 1 раз в сутки.",
        reply_markup=rotate_locations_keyboard(
            countries,
            callback_data.subscription_id,
            current_country,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(RotateCallback.filter())
async def do_rotate(
    callback: CallbackQuery,
    callback_data: RotateCallback,
    subscription_service: SubscriptionService,
) -> None:
    """Выполняет ротацию ключа после выбора страны.

    Args:
        callback: Callback-запрос.
        callback_data: Данные callback с subscription_id и country.
        subscription_service: Сервис подписок.
    """
    result = await subscription_service.rotate_key(
        callback_data.subscription_id,
        callback_data.country,
    )

    match result["status"]:
        case "cooldown":
            await callback.answer(
                "Смена ключа доступна раз в 24 часа. Попробуйте позже.",
                show_alert=True,
            )
        case "no_slots":
            await callback.answer(
                "В выбранной локации нет свободных мест. "
                "Попробуйте другую страну.",
                show_alert=True,
            )
        case "error":
            await callback.answer(
                f"Ошибка: {result.get('detail', 'неизвестная ошибка')}",
                show_alert=True,
            )
        case "ok":
            await callback.message.edit_text(
                "✅ <b>Ключ успешно заменён!</b>\n\n"
                f"Сервер: {result['country_flag']} {result['node_name']}\n\n"
                f"Новая ссылка:\n<code>{result['https_link']}</code>\n\n"
                "Нажмите кнопку ниже для подключения:",
                reply_markup=proxy_link_keyboard(result["https_link"]),
                parse_mode="HTML",
            )
            await callback.answer()
        case _:
            logger.error("Неизвестный статус ротации: %s", result)
            await callback.answer("Произошла ошибка.", show_alert=True)
