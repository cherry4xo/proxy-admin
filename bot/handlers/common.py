from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🛡 <b>Proxy Infrastructure Bot</b>\n\n"
        "Управление прокси-инфраструктурой на базе Xray-core.\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(lambda c: c.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery) -> None:
    try:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "Главное меню:",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        await callback.message.answer(  # type: ignore[union-attr]
            "Главное меню:",
            reply_markup=main_menu_keyboard(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
