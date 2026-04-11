import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.deps import Deps
from bot.keyboards.main_menu import back_keyboard

logger = logging.getLogger(__name__)
router = Router()


class CreateLBFSM(StatesGroup):
    name = State()
    listener_port = State()
    tg_id = State()


class DeleteLBFSM(StatesGroup):
    lb_id = State()


class TargetStatesFSM(StatesGroup):
    lb_id = State()
    tg_id = State()


class AddTargetFSM(StatesGroup):
    tg_id = State()
    address = State()
    subnet_id = State()


class RemoveTargetFSM(StatesGroup):
    tg_id = State()
    address = State()


def _lb_status_icon(status: str) -> str:
    return {"ACTIVE": "🟢", "CREATING": "🟡", "DELETING": "🔴", "INACTIVE": "⚫"}.get(status, "❓")


def _target_status_icon(status: str) -> str:
    return {"HEALTHY": "🟢", "UNHEALTHY": "🔴", "INITIAL": "🟡"}.get(status, "❓")


@router.callback_query(F.data == "nlb:list")
async def cb_nlb_list(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer("Загружаю список LB...")
    try:
        balancers = await deps.nlb.list_load_balancers()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка NLB API:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
        return

    if not balancers:
        await callback.message.edit_text("Балансировщиков нет.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        return

    lines = ["<b>Network Load Balancers:</b>\n"]
    for lb in balancers:
        icon = _lb_status_icon(lb.get("status", ""))
        listeners = lb.get("listeners", [])
        listener_info = ""
        if listeners:
            lst = listeners[0]
            addr = lst.get("address", "—")
            port = lst.get("port", "—")
            listener_info = f" | <code>{addr}:{port}</code>"

        tg_count = len(lb.get("attachedTargetGroups", []))
        lines.append(
            f"{icon} <b>{lb.get('name', '?')}</b> (ID: <code>{lb.get('id', '?')}</code>)\n"
            f"   Статус: {lb.get('status', '?')}{listener_info} | TG: {tg_count}"
        )

    await callback.message.edit_text("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]


@router.callback_query(F.data == "nlb:tg_list")
async def cb_nlb_tg_list(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer("Загружаю target groups...")
    try:
        groups = await deps.nlb.list_target_groups()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка NLB API:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
        return

    if not groups:
        await callback.message.edit_text("Target groups не найдены.", reply_markup=back_keyboard())  # type: ignore[union-attr]
        return

    lines = ["<b>Target Groups:</b>\n"]
    for tg in groups:
        targets = tg.get("targets", [])
        lines.append(
            f"📦 <b>{tg.get('name', '?')}</b> (ID: <code>{tg.get('id', '?')}</code>)\n"
            f"   Бэкендов: {len(targets)}"
        )
        for t in targets:
            lines.append(f"   • <code>{t.get('address', '?')}</code> subnet: {t.get('subnetId', '?')[:8]}...")

    await callback.message.edit_text("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]


@router.callback_query(F.data == "nlb:target_states")
async def cb_target_states_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID балансировщика:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(TargetStatesFSM.lb_id)
    await callback.answer()


@router.message(TargetStatesFSM.lb_id)
async def fsm_target_states_lb(message: Message, state: FSMContext) -> None:
    await state.update_data(lb_id=message.text)
    await message.answer("Введите ID target group:", reply_markup=back_keyboard())
    await state.set_state(TargetStatesFSM.tg_id)


@router.message(TargetStatesFSM.tg_id)
async def fsm_target_states_tg(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    lb_id = data["lb_id"]
    tg_id = message.text or ""
    await state.clear()

    try:
        states = await deps.nlb.get_target_states(lb_id, tg_id)
    except Exception as e:
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")
        return

    if not states:
        await message.answer("Нет данных о состоянии бэкендов.", reply_markup=back_keyboard())
        return

    lines = ["<b>Состояние бэкендов:</b>\n"]
    for s in states:
        icon = _target_status_icon(s.get("status", ""))
        lines.append(
            f"{icon} <code>{s.get('address', '?')}</code>\n"
            f"   Зона: {s.get('zoneId', '?')} | Статус: {s.get('status', '?')}"
        )

    await message.answer("\n".join(lines), reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "nlb:create")
async def cb_nlb_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(  # type: ignore[union-attr]
        "Введите имя для Load Balancer (напр. <code>proxy-lb-01</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateLBFSM.name)
    await callback.answer()


@router.message(CreateLBFSM.name)
async def fsm_nlb_create_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await message.answer(
        "Введите порт listener (напр. <code>443</code>):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateLBFSM.listener_port)


@router.message(CreateLBFSM.listener_port)
async def fsm_nlb_create_port(message: Message, state: FSMContext) -> None:
    try:
        port = int(message.text or "")
    except ValueError:
        await message.answer("Введите числовой порт:")
        return
    await state.update_data(listener_port=port)
    await message.answer(
        "Введите ID target group для привязки (или <code>-</code> чтобы создать без TG):",
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CreateLBFSM.tg_id)


@router.message(CreateLBFSM.tg_id)
async def fsm_nlb_create_tg(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    name = data["name"]
    port = data["listener_port"]
    tg_id = "" if message.text == "-" else (message.text or "")
    await state.clear()

    await message.answer(f"Создаю Load Balancer <b>{name}</b>...", parse_mode="HTML")
    try:
        op = await deps.nlb.create_load_balancer(
            name=name,
            listener_port=port,
            target_group_id=tg_id,
        )
        await message.answer(
            f"LB создаётся!\nOperation ID: <code>{op.get('id', '?')}</code>",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to create LB")
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "nlb:delete")
async def cb_nlb_delete_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID балансировщика для удаления:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(DeleteLBFSM.lb_id)
    await callback.answer()


@router.message(DeleteLBFSM.lb_id)
async def fsm_nlb_delete(message: Message, state: FSMContext, deps: Deps) -> None:
    lb_id = message.text or ""
    await state.clear()

    try:
        await deps.nlb.delete_load_balancer(lb_id)
        await message.answer(f"LB <code>{lb_id}</code> удаляется.", reply_markup=back_keyboard(), parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "nlb:add_target")
async def cb_add_target_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID target group:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(AddTargetFSM.tg_id)
    await callback.answer()


@router.message(AddTargetFSM.tg_id)
async def fsm_add_target_tg(message: Message, state: FSMContext) -> None:
    await state.update_data(tg_id=message.text)
    await message.answer("Введите внутренний IP-адрес ВМ:", reply_markup=back_keyboard())
    await state.set_state(AddTargetFSM.address)


@router.message(AddTargetFSM.address)
async def fsm_add_target_address(message: Message, state: FSMContext) -> None:
    await state.update_data(address=message.text)
    await message.answer("Введите subnet ID ВМ:", reply_markup=back_keyboard())
    await state.set_state(AddTargetFSM.subnet_id)


@router.message(AddTargetFSM.subnet_id)
async def fsm_add_target_subnet(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    tg_id = data["tg_id"]
    address = data["address"]
    subnet_id = message.text or ""
    await state.clear()

    try:
        await deps.nlb.add_targets(tg_id, [{"address": address, "subnetId": subnet_id}])
        await message.answer(
            f"ВМ <code>{address}</code> добавлена в target group.",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "nlb:remove_target")
async def cb_remove_target_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите ID target group:", reply_markup=back_keyboard())  # type: ignore[union-attr]
    await state.set_state(RemoveTargetFSM.tg_id)
    await callback.answer()


@router.message(RemoveTargetFSM.tg_id)
async def fsm_remove_target_tg(message: Message, state: FSMContext) -> None:
    await state.update_data(tg_id=message.text)
    await message.answer("Введите IP-адрес ВМ для удаления:", reply_markup=back_keyboard())
    await state.set_state(RemoveTargetFSM.address)


@router.message(RemoveTargetFSM.address)
async def fsm_remove_target_address(message: Message, state: FSMContext, deps: Deps) -> None:
    data = await state.get_data()
    tg_id = data["tg_id"]
    address = message.text or ""
    await state.clear()

    try:
        tg = await deps.nlb.get_target_group(tg_id)
        targets = [t for t in tg.get("targets", []) if t.get("address") == address]
        if not targets:
            await message.answer(f"IP <code>{address}</code> не найден в target group.", reply_markup=back_keyboard(), parse_mode="HTML")
            return
        await deps.nlb.remove_targets(tg_id, targets)
        await message.answer(
            f"ВМ <code>{address}</code> удалена из target group.",
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"Ошибка:\n<code>{e}</code>", reply_markup=back_keyboard(), parse_mode="HTML")
