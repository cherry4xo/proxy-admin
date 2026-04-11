import logging
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.deps import Deps
from bot.keyboards.main_menu import back_keyboard, confirm_keyboard

logger = logging.getLogger(__name__)
router = Router()


class CreateExitNodeFSM(StatesGroup):
    name = State()
    region = State()
    size = State()


class CreateBridgeNodeFSM(StatesGroup):
    name = State()
    exit_node_id = State()


class DeleteNodeFSM(StatesGroup):
    node_id = State()


class LinkNodeFSM(StatesGroup):
    bridge_id = State()
    exit_id = State()


class ImportNodeFSM(StatesGroup):
    server_index = State()
    role = State()


class RedeployNodeFSM(StatesGroup):
    node_id = State()


class SetX25519FSM(StatesGroup):
    node_id = State()
    private_key = State()
    public_key = State()
    reality_sni = State()


class SetupNodeFSM(StatesGroup):
    node_id = State()


@router.callback_query(F.data == "node:list_db")
async def cb_list_db_nodes(callback: CallbackQuery, deps: Deps) -> None:
    nodes = await deps.node_service.list_nodes()

    if not nodes:
        await callback.message.edit_text("Нод в базе нет.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        await callback.answer()
        return

    lines = ["<b>Ноды в БД:</b>\n"]
    for n in nodes:
        icon = "🟢" if n.status == "active" else ("🔴" if n.status == "blocked" else "🟡")
        role_label = "Exit" if n.role == "exit" else "Bridge"
        lines.append(
            f"{icon} [{n.id}] <b>{n.name}</b> ({role_label}, {n.provider})\n"
            f"   IP: <code>{n.ip or '—'}</code> | Status: {n.status}"
        )

    await callback.message.edit_text("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "node:list_bitlaunch")
async def cb_list_bitlaunch(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer("Загружаем данные BitLaunch...")
    try:
        servers = await deps.bitlaunch.list_servers()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка BitLaunch API:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
        return

    if not servers:
        await callback.message.edit_text("Нет серверов на BitLaunch.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        return

    lines = ["<b>BitLaunch серверы (live):</b>\n"]
    for s in servers:
        ip = s.get("ipv4") or s.get("ip") or "—"
        lines.append(
            f"🌐 <b>{s.get('name', '?')}</b> (ID: {s.get('id', '?')})\n"
            f"   IP: <code>{ip}</code> | {s.get('status', '?')} | {s.get('regionID', '?')} | {s.get('sizeID', '?')}"
        )

    await callback.message.edit_text("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]


@router.callback_query(F.data == "node:list_yandex")
async def cb_list_yandex(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer("Загружаем данные Yandex Cloud...")
    try:
        instances = await deps.yandex.list_instances()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка YC API:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
        return

    if not instances:
        await callback.message.edit_text("Нет ВМ в Yandex Cloud.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        return

    lines = ["<b>Yandex Cloud ВМ (live):</b>\n"]
    for inst in instances:
        ip = deps.yandex.extract_ip(inst) or "—"
        lines.append(
            f"🌐 <b>{inst.get('name', '?')}</b> (ID: {inst.get('id', '?')})\n"
            f"   IP: <code>{ip}</code> | {inst.get('status', '?')} | {inst.get('zoneId', '?')}"
        )

    await callback.message.edit_text("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]


@router.callback_query(F.data == "node:status")
async def cb_node_status_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID ноды из БД:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(DeleteNodeFSM.node_id)
    await state.update_data(action="status")
    await callback.answer()


@router.callback_query(F.data == "node:create_exit")
async def cb_create_exit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите имя для Exit Node (например: <code>exit-lon-01</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateExitNodeFSM.name)
    await callback.answer()


@router.message(CreateExitNodeFSM.name)
async def fsm_exit_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await message.answer(
        "Введите регион BitLaunch (напр. <code>lon1</code>, <code>ams3</code>, <code>fra1</code>, <code>sgp1</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateExitNodeFSM.region)


@router.message(CreateExitNodeFSM.region)
async def fsm_exit_region(message: Message, state: FSMContext) -> None:
    await state.update_data(region=message.text)
    await message.answer(
        "Введите тариф BitLaunch (напр. <code>nibble-1024</code>, <code>nibble-2048</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateExitNodeFSM.size)


@router.message(CreateExitNodeFSM.size)
async def fsm_exit_size(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    name = data["name"]
    region = data["region"]
    size = message.text or ""
    await state.clear()

    await message.answer(
        f"Создаю Exit Node...\n"
        f"Имя: <b>{name}</b> | Регион: <b>{region}</b> | Тариф: <b>{size}</b>\n\n"
        "Это займёт 1-2 минуты.",
        parse_mode="HTML",
    )

    try:
        node = await deps.node_service.create_exit_node(
            name=name,
            image_id="10000",
            size_id=size,
            region_id=region,
        )
        await message.answer(
            f"Exit Node создана!\n"
            f"ID в БД: <b>{node.id}</b>\n"
            f"IP: <code>{node.ip}</code>\n"
            f"Public key (X25519): <code>{node.x25519_public}</code>\n"
            f"Short ID: <code>{node.short_id}</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to create exit node")
        await message.answer(f"Ошибка создания Exit Node:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "node:create_bridge")
async def cb_create_bridge_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите имя для Bridge Node (например: <code>bridge-msk-01</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateBridgeNodeFSM.name)
    await callback.answer()


@router.message(CreateBridgeNodeFSM.name)
async def fsm_bridge_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await message.answer("Введите ID Exit Node (из БД), к которой привязать Bridge:", reply_markup=back_keyboard())
    await state.set_state(CreateBridgeNodeFSM.exit_node_id)


@router.message(CreateBridgeNodeFSM.exit_node_id)
async def fsm_bridge_exit_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        exit_node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID ноды:")
        return

    data = await state.get_data()
    name = data["name"]
    await state.clear()

    await message.answer(f"Создаю Bridge Node <b>{name}</b> → Exit #{exit_node_id}...", parse_mode="HTML")

    try:
        node = await deps.node_service.create_bridge_node(name=name, exit_node_id=exit_node_id)
        await message.answer(
            f"Bridge Node создана!\n"
            f"ID в БД: <b>{node.id}</b>\n"
            f"IP: <code>{node.ip}</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to create bridge node")
        await message.answer(f"Ошибка создания Bridge Node:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "node:delete")
async def cb_delete_node_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID ноды для удаления (из БД):", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(DeleteNodeFSM.node_id)
    await state.update_data(action="delete")
    await callback.answer()


@router.message(DeleteNodeFSM.node_id)
async def fsm_node_id_input(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID ноды:")
        return

    data = await state.get_data()
    action = data.get("action", "delete")
    await state.clear()

    if action == "status":
        node = await deps.node_service.get_node(node_id)
        if not node:
            await message.answer("Нода не найдена.", reply_markup=back_keyboard())
            return
        await message.answer(
            f"<b>Нода #{node.id}</b>\n"
            f"Имя: {node.name}\n"
            f"Роль: {node.role}\n"
            f"Провайдер: {node.provider}\n"
            f"IP: <code>{node.ip or '—'}</code>\n"
            f"Статус: {node.status}\n"
            f"Создана: {node.created_at.strftime('%Y-%m-%d %H:%M')}",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
        return

    if action == "recreate":
        await message.answer(f"Пересоздаю Bridge Node #{node_id}...")
        try:
            node = await deps.node_service.recreate_bridge_node(node_id)
            await message.answer(
                f"Bridge пересоздан!\nНовый ID: <b>{node.id}</b> | IP: <code>{node.ip}</code>",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")
        return

    await message.answer(
        f"Удалить ноду #{node_id}? Это действие необратимо!",
        reply_markup=confirm_keyboard(f"delete_node:{node_id}"),
    )


@router.callback_query(F.data.startswith("confirm:delete_node:"))
async def cb_confirm_delete_node(callback: CallbackQuery, deps: Deps) -> None:
    node_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    await callback.message.edit_text(f"Удаляю ноду #{node_id}...")  # type: ignore[union-attr]

    try:
        await deps.node_service.delete_node(node_id)
        await callback.message.edit_text(f"Нода #{node_id} удалена.", reply_markup=back_keyboard())  # type: ignore[union-attr]
    except Exception as e:
        logger.exception("Failed to delete node %d", node_id)
        await callback.message.edit_text(f"Ошибка удаления:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]

    await callback.answer()


@router.callback_query(F.data == "node:recreate_bridge")
async def cb_recreate_bridge_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID Bridge Node для пересоздания (из БД):", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(DeleteNodeFSM.node_id)
    await state.update_data(action="recreate")
    await callback.answer()


@router.callback_query(F.data == "node:link")
async def cb_link_nodes_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID Bridge Node (из БД):", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(LinkNodeFSM.bridge_id)
    await callback.answer()


@router.message(LinkNodeFSM.bridge_id)
async def fsm_link_bridge_id(message: Message, state: FSMContext) -> None:
    try:
        bridge_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return
    await state.update_data(bridge_id=bridge_id)
    await message.answer("Введите ID Exit Node (из БД):", reply_markup=back_keyboard())
    await state.set_state(LinkNodeFSM.exit_id)


@router.message(LinkNodeFSM.exit_id)
async def fsm_link_exit_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        exit_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    data = await state.get_data()
    bridge_id = data["bridge_id"]
    await state.clear()

    try:
        await deps.node_service.link_nodes(bridge_id, exit_id)
        await message.answer(f"Связь Bridge #{bridge_id} → Exit #{exit_id} создана.", reply_markup=back_keyboard())
    except Exception as e:
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


def _build_import_provider_keyboard() -> Any:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🌐 BitLaunch", callback_data="import:bitlaunch"),
        InlineKeyboardButton(text="🌐 Yandex Cloud", callback_data="import:yandex"),
    )
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="menu:main"))
    return builder.as_markup()


def _build_server_list_keyboard(items: list[dict], existing_ids: set[str]) -> Any:
    builder = InlineKeyboardBuilder()
    for i, item in enumerate(items):
        if item["provider_id"] not in existing_ids:
            builder.row(InlineKeyboardButton(
                text=f"[{i}] {item['name']} ({item['ip'] or '—'})",
                callback_data=f"import_node:{i}",
            ))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="menu:main"))
    return builder.as_markup()


def _build_role_keyboard() -> Any:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Exit Node (зарубеж)", callback_data="import_role:exit"),
        InlineKeyboardButton(text="Bridge Node (RU)", callback_data="import_role:bridge"),
    )
    builder.row(InlineKeyboardButton(text="« Отмена", callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "node:import")
async def cb_import_start(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Выбери провайдера для импорта нод:", reply_markup=_build_import_provider_keyboard())  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("import:"))
async def cb_import_provider(callback: CallbackQuery, state: FSMContext, deps: Deps) -> None:
    provider = callback.data.split(":")[1]  # type: ignore[union-attr]
    await callback.answer("Загружаю список серверов...")

    try:
        if provider == "bitlaunch":
            servers = await deps.bitlaunch.list_servers()
            items = [
                {
                    "provider": "bitlaunch",
                    "provider_id": str(s.get("id", "")),
                    "name": s.get("name", "noname"),
                    "ip": s.get("ipv4") or s.get("ip") or "",
                    "status": s.get("status", "active"),
                    "info": f"{s.get('regionID', '?')} / {s.get('sizeID', '?')}",
                }
                for s in servers
            ]
        else:
            instances = await deps.yandex.list_instances()
            items = [
                {
                    "provider": "yandex",
                    "provider_id": inst.get("id", ""),
                    "name": inst.get("name", "noname"),
                    "ip": deps.yandex.extract_ip(inst) or "",
                    "status": inst.get("status", "RUNNING"),
                    "info": inst.get("zoneId", "?"),
                }
                for inst in instances
            ]
    except Exception as e:
        await callback.message.edit_text(f"Ошибка получения списка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
        return

    if not items:
        await callback.message.edit_text("Нет серверов у провайдера.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        return

    existing_nodes = await deps.node_service.list_nodes()
    existing_ids = {n.provider_id for n in existing_nodes}

    lines = [f"<b>Серверы {provider} — выбери для импорта:</b>\n"]
    for i, item in enumerate(items):
        in_db = " ✅ в БД" if item["provider_id"] in existing_ids else ""
        lines.append(
            f"[{i}] <b>{item['name']}</b>{in_db}\n"
            f"    IP: <code>{item['ip'] or '—'}</code> | {item['info']}"
        )

    await state.update_data(items=items)
    await state.set_state(ImportNodeFSM.server_index)
    await callback.message.edit_text(  # type: ignore[union-attr]
        "\n".join(lines),
        reply_markup=_build_server_list_keyboard(items, existing_ids),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("import_node:"), ImportNodeFSM.server_index)
async def cb_import_select_server(callback: CallbackQuery, state: FSMContext) -> None:
    idx = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    data = await state.get_data()
    item = data["items"][idx]
    await state.update_data(selected=item)
    await state.set_state(ImportNodeFSM.role)

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"Сервер: <b>{item['name']}</b> (<code>{item['ip']}</code>)\n\n"
        "Какую роль назначить этой ноде?",
        reply_markup=_build_role_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("import_role:"), ImportNodeFSM.role)
async def cb_import_set_role(callback: CallbackQuery, state: FSMContext, deps: Deps) -> None:
    role = callback.data.split(":")[1]  # type: ignore[union-attr]
    data = await state.get_data()
    item = data["selected"]
    await state.clear()

    node = await deps.node_service.import_node(
        provider=item["provider"],
        provider_id=item["provider_id"],
        name=item["name"],
        ip=item["ip"] or None,
        role=role,
    )

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"Нода импортирована!\n\n"
        f"ID в БД: <b>{node.id}</b>\n"
        f"Имя: <b>{node.name}</b>\n"
        f"Роль: <b>{role}</b>\n"
        f"IP: <code>{node.ip or '—'}</code>",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "node:redeploy")
async def cb_redeploy_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID ноды для передеплоя конфига:",
        reply_markup=back_keyboard(),
    )
    await state.set_state(RedeployNodeFSM.node_id)
    await callback.answer()


@router.message(RedeployNodeFSM.node_id)
async def fsm_redeploy_node_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID ноды:")
        return

    await state.clear()
    node = await deps.node_service.get_node(node_id)
    if not node:
        await message.answer("Нода не найдена.", reply_markup=back_keyboard())
        return

    await message.answer(
        f"Деплою конфиг на ноду <b>{node.name}</b> ({node.role}, <code>{node.ip}</code>)...",
        parse_mode="HTML",
    )
    try:
        await deps.node_service.redeploy_node(node_id)
        await message.answer(
            f"Конфиг на ноде <b>{node.name}</b> обновлён.",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to redeploy node %d", node_id)
        await message.answer(f"Ошибка деплоя:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "node:redeploy_all")
async def cb_redeploy_all(callback: CallbackQuery, deps: Deps) -> None:
    await callback.message.edit_text("Деплою конфиг на все активные ноды...")  # type: ignore[union-attr]
    await callback.answer()

    results = await deps.node_service.redeploy_all_nodes()

    lines = ["<b>Результат деплоя:</b>\n"]
    for node_id, name, error in results:
        if error is None:
            lines.append(f"✅ [{node_id}] {name}")
        else:
            lines.append(f"❌ [{node_id}] {name}: <code>{error}</code>")

    await callback.message.edit_text(  # type: ignore[union-attr]
        "\n".join(lines),
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "node:set_x25519")
async def cb_set_x25519_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID Exit Node (из БД) для которой хотите задать X25519 ключи:",
        reply_markup=back_keyboard(),
    )
    await state.set_state(SetX25519FSM.node_id)
    await callback.answer()


@router.message(SetX25519FSM.node_id)
async def fsm_set_x25519_node_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    node = await deps.node_service.get_node(node_id)
    if not node or node.role != "exit":
        await message.answer("Exit нода не найдена.", reply_markup=back_keyboard())
        await state.clear()
        return

    await state.update_data(node_id=node_id)
    await message.answer(
        f"Нода: <b>{node.name}</b> (<code>{node.ip}</code>)\n\n"
        "Введите <b>X25519 Private Key</b> (base64url, из Xray или xray x25519):\n\n"
        "<i>Получить: на сервере выполни</i>\n"
        "<code>xray x25519</code>\n"
        "<i>или</i>\n"
        "<code>docker run --rm teddysun/xray xray x25519</code>",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(SetX25519FSM.private_key)


@router.message(SetX25519FSM.private_key)
async def fsm_set_x25519_private(message: Message, state: FSMContext) -> None:
    await state.update_data(private_key=message.text)
    await message.answer(
        "Введите <b>X25519 Public Key</b> (base64url):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(SetX25519FSM.public_key)


@router.message(SetX25519FSM.public_key)
async def fsm_set_x25519_public(message: Message, state: FSMContext) -> None:
    await state.update_data(public_key=message.text)
    await message.answer(
        "Введите SNI домен для REALITY (напр. <code>www.microsoft.com</code> или <code>google.com</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(SetX25519FSM.reality_sni)


@router.message(SetX25519FSM.reality_sni)
async def fsm_set_x25519_sni(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    node_id = data["node_id"]
    private_key = data["private_key"]
    public_key = data["public_key"]
    reality_sni = message.text or ""
    await state.clear()

    try:
        node = await deps.node_service.set_node_x25519(
            node_id=node_id,
            x25519_private=private_key,
            x25519_public=public_key,
            reality_sni=reality_sni,
        )
        await message.answer(
            f"Ключи сохранены для ноды <b>{node.name}</b>.\n\n"
            "Теперь можешь нажать 🔁 Передеплоить конфиг.",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to set x25519 for node %d", node_id)
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "node:bot_pubkey")
async def cb_bot_pubkey(callback: CallbackQuery, deps: Deps) -> None:
    try:
        pubkey = await deps.node_service.get_bot_public_key()
        await callback.message.edit_text(  # type: ignore[union-attr]
            "Публичный SSH-ключ бота:\n\n"
            f"<code>{pubkey}</code>\n\n"
            "Добавь его на ноду:\n"
            "<code>echo 'PUBKEY' >> ~/.ssh/authorized_keys</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        await callback.message.edit_text(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "node:setup")
async def cb_setup_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите ID ноды для установки Xray:\n\n"
        "<b>Предварительно</b> добавь публичный ключ бота в <code>~/.ssh/authorized_keys</code> на сервере.\n"
        "Получить ключ: кнопка 🔐 Публичный ключ бота",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(SetupNodeFSM.node_id)
    await callback.answer()


@router.message(SetupNodeFSM.node_id)
async def fsm_setup_node_id(message: Message, state: FSMContext, deps: Deps) -> None:
    try:
        node_id = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой ID:")
        return

    await state.clear()
    node = await deps.node_service.get_node(node_id)
    if not node:
        await message.answer("Нода не найдена.", reply_markup=back_keyboard())
        return

    await message.answer(
        f"Запускаю сетап на ноде <b>{node.name}</b> (<code>{node.ip}</code>)...\n\n"
        "Это займёт 1-2 минуты.",
        parse_mode="HTML",
    )
    try:
        result_node = await deps.node_service.setup_node(node_id)
        if result_node.role == "exit" and result_node.x25519_public:
            await message.answer(
                f"Xray установлен на <b>{result_node.name}</b>!\n\n"
                f"X25519 ключи сгенерированы автоматически:\n"
                f"Public key: <code>{result_node.x25519_public}</code>\n\n"
                "Следующий шаг:\n"
                "Нажми 🔁 Передеплоить конфиг",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"Xray установлен на <b>{result_node.name}</b>!\n\n"
                "Следующий шаг:\n"
                "Нажми 🔁 Передеплоить конфиг",
                reply_markup=back_keyboard(),
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("Failed to setup node %d", node_id)
        await message.answer(
            f"Ошибка сетапа:\n<code>{e}</code>\n\n"
            "Убедись что публичный ключ бота добавлен в authorized_keys.",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
