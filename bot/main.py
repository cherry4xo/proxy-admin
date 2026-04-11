import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from bot.config import settings
from bot.database.base import init_db
from bot.deps import build_deps
from bot.handlers import common, nlb, nodes, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class AdminMiddleware:
    async def __call__(self, handler, event: Update, data: dict) -> None:
        user = None
        if event.message:
            user = event.message.from_user
        elif event.callback_query:
            user = event.callback_query.from_user

        if user is None or user.id not in settings.ADMIN_IDS:
            if event.message:
                await event.message.answer("⛔ Доступ запрещён.")
            elif event.callback_query:
                await event.callback_query.answer("⛔ Доступ запрещён.", show_alert=True)
            return

        return await handler(event, data)


async def main() -> None:
    logger.info("Initializing database...")
    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.outer_middleware(AdminMiddleware())
    dp.workflow_data["deps"] = build_deps()

    dp.include_router(common.router)
    dp.include_router(nodes.router)
    dp.include_router(nlb.router)
    dp.include_router(users.router)

    logger.info("Starting bot polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
