"""Хэндлер раздела «Мои прокси» — просмотр активных подписок."""

from aiogram import Router
from aiogram.types import CallbackQuery

from src.bot.callbacks.factories import MyProxiesCallback
from src.bot.keyboards.menus import main_menu_keyboard, my_proxies_keyboard
from src.services.subscription import SubscriptionService

router = Router(name="my_proxies")


@router.callback_query(MyProxiesCallback.filter(lambda cb: cb.action == "list"))
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
