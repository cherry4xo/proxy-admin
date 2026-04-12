from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # --- Ноды: управление ---
    builder.row(InlineKeyboardButton(text="--- Ноды: управление ---", callback_data="noop"))
    builder.row(
        InlineKeyboardButton(text="➕ Создать Exit Node (BitLaunch)", callback_data="node:create_exit"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Создать Bridge Node (Yandex Cloud)", callback_data="node:create_bridge"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Привязать Bridge → Exit", callback_data="node:link"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Пересоздать Bridge (смена IP)", callback_data="node:recreate_bridge"),
        InlineKeyboardButton(text="❌ Удалить ноду", callback_data="node:delete"),
    )
    builder.row(
        InlineKeyboardButton(text="🔁 Передеплоить конфиг", callback_data="node:redeploy"),
        InlineKeyboardButton(text="🔁 Передеплоить все", callback_data="node:redeploy_all"),
    )
    builder.row(
        InlineKeyboardButton(text="🔑 Задать X25519 ключи", callback_data="node:set_x25519"),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Сетап ноды (установить Xray)", callback_data="node:setup"),
        InlineKeyboardButton(text="🔐 Публичный ключ бота", callback_data="node:bot_pubkey"),
    )
    builder.row(
        InlineKeyboardButton(text="📄 Загрузить свой конфиг", callback_data="node:upload_config"),
    )

    # --- Ноды: мониторинг ---
    builder.row(InlineKeyboardButton(text="--- Ноды: мониторинг ---", callback_data="noop"))
    builder.row(
        InlineKeyboardButton(text="📋 Мои ноды (БД)", callback_data="node:list_db"),
        InlineKeyboardButton(text="📊 Статус ноды", callback_data="node:status"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статус Xray на ноде", callback_data="node:xray_status"),
    )
    builder.row(
        InlineKeyboardButton(text="🌐 BitLaunch (live)", callback_data="node:list_bitlaunch"),
        InlineKeyboardButton(text="🌐 Yandex Cloud (live)", callback_data="node:list_yandex"),
    )
    builder.row(
        InlineKeyboardButton(text="📥 Импортировать ноду в БД", callback_data="node:import"),
    )

    # --- Load Balancer ---
    builder.row(InlineKeyboardButton(text="--- Load Balancer (YC NLB) ---", callback_data="noop"))
    builder.row(
        InlineKeyboardButton(text="📋 Список LB", callback_data="nlb:list"),
        InlineKeyboardButton(text="📋 Target Groups", callback_data="nlb:tg_list"),
    )
    builder.row(
        InlineKeyboardButton(text="💚 Состояние бэкендов", callback_data="nlb:target_states"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Создать LB", callback_data="nlb:create"),
        InlineKeyboardButton(text="❌ Удалить LB", callback_data="nlb:delete"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ ВМ в target group", callback_data="nlb:add_target"),
        InlineKeyboardButton(text="❌ ВМ из target group", callback_data="nlb:remove_target"),
    )

    # --- Пользователи ---
    builder.row(InlineKeyboardButton(text="--- Пользователи ---", callback_data="noop"))
    builder.row(
        InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="user:create"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Список пользователей", callback_data="user:list"),
    )
    builder.row(
        InlineKeyboardButton(text="🔒 Заблокировать", callback_data="user:block"),
        InlineKeyboardButton(text="❌ Удалить", callback_data="user:delete"),
    )
    builder.row(
        InlineKeyboardButton(text="📲 Получить конфиг пользователя", callback_data="user:get_config"),
    )

    return builder.as_markup()


def back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="menu:main"))
    return builder.as_markup()


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{action}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main"),
    )
    return builder.as_markup()
