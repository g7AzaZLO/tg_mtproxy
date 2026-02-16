"""Хэндлер раздела «Мои прокси» — просмотр, ротация ключа и смена локации."""

import logging
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.bot.callbacks.factories import MyProxiesCallback, RotateCallback
from src.bot.keyboards.menus import (
    main_menu_keyboard,
    my_proxies_keyboard,
    proxy_link_keyboard,
    rotate_locations_keyboard,
    socks5_credentials_keyboard,
)
from src.db import repositories as repo
from src.services.proxy import build_socks5_link
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
        access_type = sub.get("access_type", "mtproto")

        if access_type == "socks5":
            text_parts.append(
                f"{i}. 🧦 {sub.get('country_flag', '')} "
                f"<b>{sub.get('node_name', 'Сервер')}</b> (SOCKS5)\n"
                f"   Тариф: {sub.get('plan_name', '—')}\n"
                f"   До: {expires}\n"
            )
        else:
            text_parts.append(
                f"{i}. 🔒 {sub.get('country_flag', '')} "
                f"<b>{sub.get('node_name', 'Сервер')}</b> (MTProto)\n"
                f"   Тариф: {sub.get('plan_name', '—')}\n"
                f"   До: {expires}\n"
                f"   <code>{escape(sub['https_link'])}</code>\n"
            )

    text_parts.append("\nНажмите кнопку сервера для подключения прокси:")

    await callback.message.edit_text(
        "\n".join(text_parts),
        reply_markup=my_proxies_keyboard(subscriptions),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MyProxiesCallback.filter(F.action == "detail_socks5"))
async def detail_socks5(
    callback: CallbackQuery,
    callback_data: MyProxiesCallback,
    db_user: dict,
) -> None:
    """Показывает SOCKS5-credentials для конкретной подписки.

    Args:
        callback: Callback-запрос.
        callback_data: Данные callback с subscription_id.
        db_user: Данные пользователя из БД.
    """
    sub = await repo.subscription.get_by_id(callback_data.subscription_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    if sub.get("access_type") != "socks5":
        await callback.answer("Данные недоступны.", show_alert=True)
        return

    node = await repo.node.get_by_id(sub["node_id"])
    flag = node["country_flag"] if node else ""
    name = node["name"] if node else "Сервер"
    host = node["host"] if node else ""
    socks5_port = (node.get("socks5_port") or 1080) if node else 1080
    expires = sub["expires_at"].strftime("%d.%m.%Y %H:%M")

    # username хранится в secret, password в marzban_username
    username = sub["secret"]
    password = sub.get("marzban_username", "")

    socks5_link = build_socks5_link(host, socks5_port, username, password)
    text = (
        f"🧦 <b>SOCKS5 — {flag} {name}</b>\n"
        f"До: <b>{expires}</b>\n\n"
        f"<b>Данные для подключения:</b>\n"
        f"Хост: <code>{escape(host)}</code>\n"
        f"Порт: <code>{socks5_port}</code>\n"
        f"Логин: <code>{escape(username)}</code>\n"
        f"Пароль: <code>{escape(password)}</code>\n\n"
        "Нажмите кнопку ниже для автоматического подключения, "
        "или скопируйте ссылку:\n"
        f"<code>{escape(socks5_link)}</code>\n\n"
        "<i>Скопируйте данные и добавьте в настройки прокси "
        "Telegram (Настройки → Данные и память → Прокси).</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=socks5_credentials_keyboard(socks5_link),
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
        "⚠️ <b>Перед заменой отключите текущее прокси-соединение</b> "
        "в настройках Telegram, иначе связь оборвётся.\n\n"
        "Выберите локацию для нового ключа.\n"
        "Можно выбрать текущую (отмечена ✓) или другую страну.\n\n"
        "Доступно 1 раз в сутки.",
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
            await _show_rotate_success(callback, result)
            await callback.answer()
        case _:
            logger.error("Неизвестный статус ротации: %s", result)
            await callback.answer("Произошла ошибка.", show_alert=True)


async def _show_rotate_success(callback: CallbackQuery, result: dict) -> None:
    """Отправляет сообщение об успешной ротации.

    Args:
        callback: Callback-запрос.
        result: Результат ротации из SubscriptionService.
    """
    access_type = result.get("access_type", "mtproto")

    if access_type == "socks5" and result.get("socks5_host"):
        socks5_link = result.get("socks5_link") or build_socks5_link(
            result["socks5_host"],
            result["socks5_port"],
            result["socks5_username"],
            result["socks5_password"],
        )
        text = (
            "✅ <b>SOCKS5 ключ успешно заменён!</b>\n\n"
            f"Сервер: {result['country_flag']} {result['node_name']}\n\n"
            f"<b>Новые данные:</b>\n"
            f"Хост: <code>{escape(result['socks5_host'])}</code>\n"
            f"Порт: <code>{result['socks5_port']}</code>\n"
            f"Логин: <code>{escape(result['socks5_username'])}</code>\n"
            f"Пароль: <code>{escape(result['socks5_password'])}</code>\n\n"
            "Нажмите кнопку ниже для автоматического подключения, "
            "или скопируйте ссылку:\n"
            f"<code>{escape(socks5_link)}</code>"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=socks5_credentials_keyboard(socks5_link),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Не удалось обновить сообщение после ротации SOCKS5")
            await callback.answer("Ключ заменён! Откройте Мои прокси.", show_alert=True)
    else:
        text = (
            "✅ <b>Ключ успешно заменён!</b>\n\n"
            f"Сервер: {result['country_flag']} {result['node_name']}\n\n"
            f"Новая ссылка:\n<code>{escape(result['https_link'])}</code>\n\n"
            "Нажмите кнопку ниже для подключения:"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=proxy_link_keyboard(result["https_link"]),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Не удалось обновить сообщение после ротации MTProto")
            await callback.answer("Ключ заменён! Откройте Мои прокси.", show_alert=True)
