"""Хэндлеры админ-команд в боте.

Доступны только пользователям, чей telegram_id указан в ADMIN_IDS.
"""

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.db import repositories as repo

logger = logging.getLogger(__name__)

router = Router(name="admin")

# Список telegram_id администраторов (можно вынести в конфиг)
ADMIN_IDS: set[int] = set()


def set_admin_ids(ids: set[int]) -> None:
    """Устанавливает список администраторов бота.

    Args:
        ids: Множество telegram_id администраторов.
    """
    global ADMIN_IDS  # noqa: PLW0603
    ADMIN_IDS = ids


def _is_admin(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь администратором.

    Args:
        telegram_id: Telegram ID пользователя.

    Returns:
        True, если пользователь — администратор.
    """
    return telegram_id in ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Показывает список доступных админ-команд.

    Args:
        message: Входящее сообщение.
    """
    if not _is_admin(message.from_user.id):
        return

    text = (
        "<b>Админ-панель</b>\n\n"
        "/stats — Статистика сервиса\n"
        "/nodes — Список нод\n"
        "/ban &lt;telegram_id&gt; — Заблокировать пользователя\n"
        "/unban &lt;telegram_id&gt; — Разблокировать пользователя\n"
        "/user &lt;telegram_id&gt; — Информация о пользователе\n"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Показывает статистику сервиса.

    Args:
        message: Входящее сообщение.
    """
    if not _is_admin(message.from_user.id):
        return

    users_count = await repo.user.count()
    active_subs = await repo.subscription.count_active()
    revenue = await repo.payment.get_revenue_stats()

    text = (
        "<b>Статистика сервиса</b>\n\n"
        f"Пользователей: {users_count}\n"
        f"Активных подписок: {active_subs}\n\n"
        f"Доход сегодня: ${revenue['today_revenue']}\n"
        f"Доход за неделю: ${revenue['week_revenue']}\n"
        f"Доход за месяц: ${revenue['month_revenue']}\n"
        f"Доход всего: ${revenue['total_revenue']}\n"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("nodes"))
async def cmd_nodes(message: Message) -> None:
    """Показывает список нод с загрузкой.

    Args:
        message: Входящее сообщение.
    """
    if not _is_admin(message.from_user.id):
        return

    nodes = await repo.node.get_nodes_with_load()
    if not nodes:
        await message.answer("Нет зарегистрированных нод.")
        return

    parts = ["<b>Ноды:</b>\n"]
    for node in nodes:
        status = "🟢" if node["is_active"] else "🔴"
        parts.append(
            f"{status} <b>{node['name']}</b> ({node['country_flag']} {node['country']})\n"
            f"   {node['host']}:{node['port']}\n"
            f"   Пользователей: {node['current_users']}/{node['max_users']}\n"
        )
    await message.answer("\n".join(parts), parse_mode="HTML")


@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    """Блокирует пользователя по telegram_id.

    Args:
        message: Входящее сообщение.
    """
    if not _is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Использование: /ban &lt;telegram_id&gt;", parse_mode="HTML")
        return

    telegram_id = int(args[1].strip())
    user = await repo.user.get_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    await repo.user.set_banned(user["id"], is_banned=True)
    await message.answer(
        f"Пользователь {telegram_id} (@{user.get('username', '—')}) заблокирован."
    )


@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    """Разблокирует пользователя по telegram_id.

    Args:
        message: Входящее сообщение.
    """
    if not _is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Использование: /unban &lt;telegram_id&gt;", parse_mode="HTML")
        return

    telegram_id = int(args[1].strip())
    user = await repo.user.get_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    await repo.user.set_banned(user["id"], is_banned=False)
    await message.answer(
        f"Пользователь {telegram_id} (@{user.get('username', '—')}) разблокирован."
    )


@router.message(Command("user"))
async def cmd_user_info(message: Message) -> None:
    """Показывает информацию о пользователе.

    Args:
        message: Входящее сообщение.
    """
    if not _is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Использование: /user &lt;telegram_id&gt;", parse_mode="HTML")
        return

    telegram_id = int(args[1].strip())
    user = await repo.user.get_by_telegram_id(telegram_id)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    subs = await repo.subscription.get_active_by_user(user["id"])
    payments = await repo.payment.get_user_payments(user["id"], limit=5)

    text = (
        f"<b>Пользователь #{user['id']}</b>\n"
        f"Telegram: {telegram_id} (@{user.get('username', '—')})\n"
        f"Имя: {user.get('first_name', '—')}\n"
        f"Бан: {'да' if user['is_banned'] else 'нет'}\n"
        f"Trial: {'использован' if user['used_trial'] else 'доступен'}\n"
        f"Активных подписок: {len(subs)}\n"
        f"Регистрация: {user['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
    )

    if payments:
        text += "\n<b>Последние платежи:</b>\n"
        for p in payments:
            text += (
                f"  • ${p['amount_usd']} — {p.get('plan_name', '—')} "
                f"[{p['status']}] {p['created_at'].strftime('%d.%m')}\n"
            )

    await message.answer(text, parse_mode="HTML")
