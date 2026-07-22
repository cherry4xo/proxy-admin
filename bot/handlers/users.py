import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.deps import Deps
from bot.keyboards.main_menu import back_keyboard

logger = logging.getLogger(__name__)
router = Router()


class CreateUserFSM(StatesGroup):
    name = State()
    exit_node_id = State()
    extra_nodes = State()


class UserActionFSM(StatesGroup):
    user_id = State()


class GetConfigFSM(StatesGroup):
    user_id = State()


class GetBridgeConfigFSM(StatesGroup):
    user_id = State()


class SubscriptionFSM(StatesGroup):
    user_id = State()


class RotateSubFSM(StatesGroup):
    user_id = State()


class SubscriptionNodesFSM(StatesGroup):
    user_id = State()
    add_node_id = State()
    remove_node_id = State()
    primary_node_id = State()


async def _extra_nodes_keyboard(deps: Deps, primary_id: int, selected: set[int]):
    """Клавиатура мульти-выбора доп. exit-нод (галочки) + Готово."""
    nodes = [n for n in await deps.node_service.list_nodes() if n.role == "exit" and n.id != primary_id]
    builder = InlineKeyboardBuilder()
    for n in nodes:
        mark = "☑️" if n.id in selected else "⬜"
        builder.row(InlineKeyboardButton(text=f"{mark} [{n.id}] {n.name}", callback_data=f"usernode:{n.id}"))
    builder.row(InlineKeyboardButton(text="✅ Готово (создать)", callback_data="usernode:done"))
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="menu:main"))
    return builder.as_markup()


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
    telegram_id = message.from_user.id if message.from_user else None
    await state.update_data(name=message.text, telegram_id=telegram_id)
    await message.answer("Введите ID первичной Exit Node (из БД) для этого пользователя:", reply_markup=back_keyboard())
    await state.set_state(CreateUserFSM.exit_node_id)


@router.message(CreateUserFSM.exit_node_id)
async def fsm_user_exit_node(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        exit_node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    await state.update_data(exit_node_id=exit_node_id, extra=[])
    await message.answer(
        "Выберите дополнительные Exit-ноды для подписки (необязательно).\n"
        "Подписка соберёт ссылки по всем выбранным нодам. Нажмите «Готово», когда закончите.",
        reply_markup=await _extra_nodes_keyboard(deps, exit_node_id, set()),
    )
    await state.set_state(CreateUserFSM.extra_nodes)


@router.callback_query(CreateUserFSM.extra_nodes, F.data.startswith("usernode:"))
async def cb_user_extra_node(callback: CallbackQuery, state: FSMContext, deps: Deps) -> None:
    arg = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    primary_id = data["exit_node_id"]
    selected = set(data.get("extra", []))

    if arg == "done":
        await callback.answer()
        await _finalize_user_creation(callback.message, state, deps)  # type: ignore[arg-type]
        return

    node_id = int(arg)
    if node_id in selected:
        selected.discard(node_id)
    else:
        selected.add(node_id)
    await state.update_data(extra=list(selected))
    await callback.message.edit_reply_markup(  # type: ignore[union-attr]
        reply_markup=await _extra_nodes_keyboard(deps, primary_id, selected)
    )
    await callback.answer()


async def _finalize_user_creation(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    name = data["name"]
    exit_node_id = data["exit_node_id"]
    extra = data.get("extra", [])
    telegram_id = data.get("telegram_id")
    await state.clear()

    await message.answer(f"Создаю пользователя <b>{name}</b>...", parse_mode="HTML")

    try:
        user, vless_url, qr_bytes, bridge_url, bridge_qr = await deps.user_service.create_user(
            name=name,
            exit_node_id=exit_node_id,
            telegram_id=telegram_id,
            extra_exit_ids=extra,
        )
        sub_url = await deps.user_service.ensure_subscription(user.id)
        await message.answer(
            f"Пользователь <b>{user.name}</b> создан!\n\n"
            f"UUID: <code>{user.uuid}</code>\n"
            f"Exit-ноды: {', '.join(str(i) for i in [exit_node_id, *extra])}\n\n"
            f"🔗 Subscription (рекомендуется):\n<code>{sub_url}</code>\n\n"
            f"🔗 Прямая (Exit):\n<code>{vless_url}</code>",
            parse_mode="HTML",
        )
        sub_qr = deps.user_service._generate_qr_code(sub_url)
        await message.answer_photo(
            photo=BufferedInputFile(sub_qr, filename="qrcode-sub.png"),
            caption=f"QR подписки для {user.name}",
        )
        await message.answer_photo(
            photo=BufferedInputFile(qr_bytes, filename="qrcode-exit.png"),
            caption=f"QR (прямой → Exit) для {user.name}",
            reply_markup=None if bridge_url else back_keyboard(),
        )
        if bridge_url and bridge_qr:
            await message.answer(
                f"🌉 Через Bridge (RU):\n<code>{bridge_url}</code>",
                parse_mode="HTML",
            )
            await message.answer_photo(
                photo=BufferedInputFile(bridge_qr, filename="qrcode-bridge.png"),
                caption=f"QR (через Bridge) для {user.name}",
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


@router.callback_query(F.data == "user:get_config")
async def cb_get_config_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID пользователя:",
        reply_markup=back_keyboard(),
    )
    await state.set_state(GetConfigFSM.user_id)
    await callback.answer()


@router.message(GetConfigFSM.user_id)
async def fsm_get_config_user_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        user_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    await state.clear()

    try:
        vless_url, qr_bytes = await deps.user_service.get_user_config(user_id)
        await message.answer(
            f"VLESS-ссылка пользователя #{user_id}:\n\n"
            f"<code>{vless_url}</code>",
            parse_mode="HTML",
        )
        await message.answer_photo(
            photo=BufferedInputFile(qr_bytes, filename="qrcode.png"),
            caption=f"QR-код пользователя #{user_id}",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.exception("Failed to get config for user %d", user_id)
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "user:get_bridge_config")
async def cb_get_bridge_config_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID пользователя (конфиг через Bridge):",
        reply_markup=back_keyboard(),
    )
    await state.set_state(GetBridgeConfigFSM.user_id)
    await callback.answer()


@router.message(GetBridgeConfigFSM.user_id)
async def fsm_get_bridge_config_user_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        user_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    await state.clear()

    try:
        vless_url, qr_bytes = await deps.user_service.get_user_bridge_config(user_id)
        await message.answer(
            f"🌉 VLESS через Bridge (пользователь #{user_id}):\n\n"
            f"<code>{vless_url}</code>",
            parse_mode="HTML",
        )
        await message.answer_photo(
            photo=BufferedInputFile(qr_bytes, filename="qrcode-bridge.png"),
            caption=f"QR (через Bridge) #{user_id}",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.exception("Failed to get bridge config for user %d", user_id)
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "user:subscription")
async def cb_subscription_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID пользователя (subscription-ссылка):",
        reply_markup=back_keyboard(),
    )
    await state.set_state(SubscriptionFSM.user_id)
    await callback.answer()


@router.message(SubscriptionFSM.user_id)
async def fsm_subscription_user_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        user_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return
    await state.clear()
    try:
        sub_url = await deps.user_service.ensure_subscription(user_id)
        qr = deps.user_service._generate_qr_code(sub_url)
        await message.answer(
            f"🔗 Subscription пользователя #{user_id}:\n\n<code>{sub_url}</code>\n\n"
            "Импортируй в v2RayTun / Hiddify / Happ — клиент подтянет все ноды и будет авто-обновляться.",
            parse_mode="HTML",
        )
        await message.answer_photo(
            photo=BufferedInputFile(qr, filename="qrcode-sub.png"),
            caption=f"QR подписки #{user_id}",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.exception("Failed to get subscription for user %d", user_id)
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "user:rotate_sub")
async def cb_rotate_sub_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID пользователя для перевыпуска подписки (старый URL перестанет работать):",
        reply_markup=back_keyboard(),
    )
    await state.set_state(RotateSubFSM.user_id)
    await callback.answer()


@router.message(RotateSubFSM.user_id)
async def fsm_rotate_sub_user_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        user_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return
    await state.clear()
    try:
        sub_url = await deps.user_service.rotate_subscription(user_id)
        qr = deps.user_service._generate_qr_code(sub_url)
        await message.answer(
            f"♻️ Подписка #{user_id} перевыпущена. Старый URL больше не работает.\n\n"
            f"<code>{sub_url}</code>",
            parse_mode="HTML",
        )
        await message.answer_photo(
            photo=BufferedInputFile(qr, filename="qrcode-sub.png"),
            caption=f"Новый QR подписки #{user_id}",
            reply_markup=back_keyboard(),
        )
    except Exception as e:
        logger.exception("Failed to rotate subscription for user %d", user_id)
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


# ==================== Subscription Node Management ====================

@router.callback_query(F.data == "user:subscription_nodes")
async def cb_sub_nodes_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start managing subscription nodes for a user."""
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID пользователя для управления узлами в подписке:",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(SubscriptionNodesFSM.user_id)
    await callback.answer()


@router.message(SubscriptionNodesFSM.user_id)
async def fsm_sub_nodes_user_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        user_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    # Get user and their subscription nodes
    async with deps.session_factory() as session:
        from bot.database.models import User
        from sqlalchemy import select
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    if not user:
        await message.answer(f"Пользователь {user_id} не найден.", reply_markup=back_keyboard())
        await state.clear()
        return

    # Get user's subscription nodes
    nodes = await deps.user_service.get_subscription_nodes(user_id)

    # Build menu
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить узел", callback_data=f"subnode:add:{user_id}"))
    if len(nodes) > 1:
        builder.row(InlineKeyboardButton(text="➖ Удалить узел", callback_data=f"subnode:remove:{user_id}"))
        builder.row(InlineKeyboardButton(text="🎯 Сменить основной", callback_data=f"subnode:primary:{user_id}"))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="menu:main"))

    node_list = "\n".join([
        f"  {'🎯' if n.id == user.exit_node_id else '  '} [{n.id}] {n.name} ({n.ip or 'no IP'})"
        for n in nodes
    ]) or "  Нет узлов"

    await message.answer(
        f"<b>Подписка пользователя #{user_id} ({user.name})</b>\n\n"
        f"Узлы в подписке ({len(nodes)}):\n{node_list}\n\n"
        f"Основной узел: #{user.exit_node_id}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("subnode:add:"))
async def cb_subnode_add(callback: CallbackQuery, deps: Deps) -> None:
    """Add node to subscription."""
    user_id = int(callback.data.split(":")[2])

    # Get available exit nodes (not in subscription yet)
    async with deps.session_factory() as session:
        from bot.database.models import User, UserNode, Node
        from sqlalchemy import select

        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        # Get nodes already in subscription
        sub_nodes = (await session.execute(
            select(UserNode.exit_node_id).where(UserNode.user_id == user_id)
        )).scalars().all()

        # Get available exit nodes
        available_nodes = (await session.execute(
            select(Node).where(Node.role == "exit", Node.id.notin_(sub_nodes))
        )).scalars().all()

    if not available_nodes:
        await callback.answer("Нет доступных узлов для добавления", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for n in available_nodes:
        builder.row(InlineKeyboardButton(
            text=f"[{n.id}] {n.name}",
            callback_data=f"subnode:add_confirm:{user_id}:{n.id}"
        ))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="user:subscription_nodes"))

    await callback.message.edit_text(
        f"Выберите узел для добавления к подписке #{user_id} ({user.name}):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("subnode:add_confirm:"))
async def cb_subnode_add_confirm(callback: CallbackQuery, deps: Deps) -> None:
    """Confirm adding node to subscription."""
    parts = callback.data.split(":")
    user_id = int(parts[2])
    node_id = int(parts[3])

    result = await deps.user_service.add_node_to_subscription(user_id, node_id)

    if result["success"]:
        await callback.message.edit_text(
            f"✅ Узел <b>{result['node_name']}</b> добавлен в подписку пользователя #{user_id}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"❌ Ошибка: {result['error']}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("subnode:remove:"))
async def cb_subnode_remove(callback: CallbackQuery, deps: Deps) -> None:
    """Remove node from subscription."""
    user_id = int(callback.data.split(":")[2])

    # Get user's subscription nodes (excluding primary)
    async with deps.session_factory() as session:
        from bot.database.models import User, UserNode, Node
        from sqlalchemy import select

        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        # Get nodes in subscription (excluding primary)
        sub_nodes = (await session.execute(
            select(Node)
            .join(UserNode, UserNode.exit_node_id == Node.id)
            .where(UserNode.user_id == user_id, Node.id != user.exit_node_id)
        )).scalars().all()

    if not sub_nodes:
        await callback.answer("Нет узлов для удаления (кроме основного)", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for n in sub_nodes:
        builder.row(InlineKeyboardButton(
            text=f"[{n.id}] {n.name}",
            callback_data=f"subnode:remove_confirm:{user_id}:{n.id}"
        ))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="user:subscription_nodes"))

    await callback.message.edit_text(
        f"Выберите узел для удаления из подписки #{user_id} ({user.name}):\n"
        f"(Основной узел #{user.exit_node_id} нельзя удалить)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("subnode:remove_confirm:"))
async def cb_subnode_remove_confirm(callback: CallbackQuery, deps: Deps) -> None:
    """Confirm removing node from subscription."""
    parts = callback.data.split(":")
    user_id = int(parts[2])
    node_id = int(parts[3])

    result = await deps.user_service.remove_node_from_subscription(user_id, node_id)

    if result["success"]:
        await callback.message.edit_text(
            f"✅ Узел <b>{result['node_name']}</b> удалён из подписки пользователя #{user_id}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"❌ Ошибка: {result['error']}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("subnode:primary:"))
async def cb_subnode_primary(callback: CallbackQuery, deps: Deps) -> None:
    """Change primary exit node."""
    user_id = int(callback.data.split(":")[2])

    # Get user's subscription nodes
    nodes = await deps.user_service.get_subscription_nodes(user_id)

    if len(nodes) <= 1:
        await callback.answer("Нельзя сменить основной узел — в подписке только один узел", show_alert=True)
        return

    async with deps.session_factory() as session:
        from bot.database.models import User
        from sqlalchemy import select
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        current_primary = user.exit_node_id if user else None

    builder = InlineKeyboardBuilder()
    for n in nodes:
        mark = "🎯 " if n.id == current_primary else ""
        builder.row(InlineKeyboardButton(
            text=f"{mark}[{n.id}] {n.name}",
            callback_data=f"subnode:primary_confirm:{user_id}:{n.id}"
        ))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="user:subscription_nodes"))

    await callback.message.edit_text(
        f"Выберите основной узел для подписки #{user_id} ({user.name if user else 'unknown'}):\n"
        f"Текущий основной: #{current_primary}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("subnode:primary_confirm:"))
async def cb_subnode_primary_confirm(callback: CallbackQuery, deps: Deps) -> None:
    """Confirm changing primary exit node."""
    parts = callback.data.split(":")
    user_id = int(parts[2])
    node_id = int(parts[3])

    result = await deps.user_service.set_primary_exit_node(user_id, node_id)

    if result["success"]:
        await callback.message.edit_text(
            f"✅ Основной узел изменён на <b>{result['node_name']}</b> для пользователя #{user_id}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"❌ Ошибка: {result['error']}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()
