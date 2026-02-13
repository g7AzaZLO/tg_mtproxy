"""Хэндлер команды /start и возврата в главное меню."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from src.bot.callbacks.factories import BackCallback
from src.bot.keyboards.menus import main_menu_keyboard

router = Router(name="start")

WELCOME_TEXT = (
    "Добро пожаловать в <b>MTProxy Store</b>!\n\n"
    "Здесь вы можете приобрести персональный MTProto-прокси "
    "для стабильного доступа к Telegram.\n\n"
    "Выберите действие:"
)


@router.message(CommandStart())
async def cmd_start(message: Message, db_user: dict) -> None:
    """Обработчик команды /start.

    Args:
        message: Входящее сообщение.
        db_user: Данные пользователя из БД (из middleware).
    """
    await message.answer(
        WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(BackCallback.filter(lambda cb: cb.to == "main"))
async def back_to_main(callback: CallbackQuery) -> None:
    """Возврат в главное меню по кнопке «Назад».

    Args:
        callback: Callback-запрос от inline-кнопки.
    """
    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
