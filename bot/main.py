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


async def sni_rotation_worker(deps, bot: Bot) -> None:
    """Background task: auto-rotate SNI for nodes when interval elapsed."""
    logger.info("SNI rotation worker started")
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            logger.debug("SNI rotation worker: checking nodes...")

            from datetime import datetime, timedelta

            nodes = await deps.node_service.list_nodes()
            rotated_count = 0
            now = datetime.utcnow()

            for node in nodes:
                if not node.sni_pool_encrypted or node.reality_domain:
                    continue  # No dynamic SNI or custom domain

                interval_h = node.sni_rotation_interval_h or 24
                last_rotation = node.last_sni_rotation_at

                if last_rotation:
                    next_rotation = last_rotation + timedelta(hours=interval_h)
                    if now >= next_rotation:
                        result = await deps.sni_rotation_service.rotate_sni(node.id, force=False)
                        if result.get("success"):
                            rotated_count += 1
                            logger.info(
                                "Auto-rotated SNI for node %d (%s): %s → %s",
                                node.id, node.name, result["old_sni"], result["new_sni"]
                            )
                        elif result.get("error"):
                            logger.warning(
                                "Auto-rotation failed for node %d: %s",
                                node.id, result["error"]
                            )
                else:
                    # Never rotated - rotate once to initialize
                    result = await deps.sni_rotation_service.rotate_sni(node.id, force=True)
                    if result.get("success"):
                        rotated_count += 1
                        logger.info(
                            "Initialized SNI for node %d (%s): %s",
                            node.id, node.name, result["new_sni"]
                        )

            if rotated_count > 0:
                logger.info("SNI rotation worker: %d nodes rotated", rotated_count)

        except asyncio.CancelledError:
            logger.info("SNI rotation worker stopped")
            break
        except Exception:
            logger.exception("SNI rotation worker error")


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

    # Start background SNI rotation worker
    sni_task = asyncio.create_task(sni_rotation_worker(dp.workflow_data["deps"], bot))

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sni_task.cancel()
        try:
            await sni_task
        except asyncio.CancelledError:
            pass
        await dp.workflow_data["deps"].sni_rotation_service.close()


if __name__ == "__main__":
    asyncio.run(main())
