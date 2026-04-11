import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.deps import Deps
from bot.keyboards.main_menu import back_keyboard

logger = logging.getLogger(__name__)
router = Router()


class CreateUserFSM(StatesGroup):
    name = State()
    exit_node_id = State()


class UserActionFSM(StatesGroup):
    user_id = State()


@router.callback_query(F.data == "user:list")
async def cb_user_list(callback: CallbackQuery, deps: Deps) -> None:
    users = await deps.user_service.list_users()

    if not users:
        await callback.message.edit_text("Пользователей нет.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        await callback.answer()
        return

    lines = ["<b>Пользователи:</b>\n"]
    for u in users:
        status = "🟢 активен" if u.is_active else "🔴 заблокирован"
        tg = f"TG: {u.telegram_id}" if u.telegram_id else "без TG"
        lines.append(
            f"[{u.id}] <b>{u.name}</b> ({tg}) — {status}\n"
            f"   UUID: <code>{u.uuid}</code>\n"
            f"   Exit Node: #{u.exit_node_id}"
        )

    await callback.message.edit_text("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "user:create")
async def cb_user_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите имя пользователя (напр. <code>alice</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateUserFSM.name)
    await callback.answer()


@router.message(CreateUserFSM.name)
async def fsm_user_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await message.answer("Введите ID Exit Node (из БД) для этого пользователя:", reply_markup=back_keyboard())
    await state.set_state(CreateUserFSM.exit_node_id)


@router.message(CreateUserFSM.exit_node_id)
async def fsm_user_exit_node(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        exit_node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    data = await state.get_data()
    name = data["name"]
    await state.clear()

    await message.answer(f"Создаю пользователя <b>{name}</b>...", parse_mode="HTML")

    try:
        telegram_id = message.from_user.id if message.from_user else None
        user, vless_url, qr_bytes = await deps.user_service.create_user(
            name=name,
            exit_node_id=exit_node_id,
            telegram_id=telegram_id,
        )
        await message.answer(
            f"Пользователь <b>{user.name}</b> создан!\n\n"
            f"UUID: <code>{user.uuid}</code>\n\n"
            f"VLESS-ссылка:\n<code>{vless_url}</code>",
            parse_mode="HTML",
        )
        await message.answer_photo(
            photo=BufferedInputFile(qr_bytes, filename="qrcode.png"),
            caption=f"QR-код для {user.name}",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.exception("Failed to create user")
        await message.answer(f"Ошибка создания пользователя:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "user:block")
async def cb_user_block_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID пользователя для блокировки:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(UserActionFSM.user_id)
    await state.update_data(action="block")
    await callback.answer()


@router.callback_query(F.data == "user:delete")
async def cb_user_delete_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID пользователя для удаления:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(UserActionFSM.user_id)
    await state.update_data(action="delete")
    await callback.answer()


@router.message(UserActionFSM.user_id)
async def fsm_user_action_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        user_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    data = await state.get_data()
    action = data.get("action", "block")
    await state.clear()

    delete_from_db = action == "delete"
    action_label = "удалён" if delete_from_db else "заблокирован"

    try:
        await deps.user_service.deactivate_user(user_id, delete_from_db=delete_from_db)
        await message.answer(f"Пользователь #{user_id} {action_label}.", reply_markup=back_keyboard())
    except Exception as e:
        logger.exception("Failed to %s user %d", action, user_id)
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")
