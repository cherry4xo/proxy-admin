"""Subscription HTTP-сервер (отдельный docker-контейнер).

Read-only: отдаёт base64-подписку (список VLESS-ссылок юзера) по секретному токену.
Запуск: python -m bot.web.subscription
Наружу публикуется только через nginx/поддомен (внутри слушает SUB_HTTP_HOST:SUB_HTTP_PORT).
"""
import asyncio
import logging

from aiohttp import web

from bot.config import settings
from bot.database.base import async_session_factory, init_db
from bot.services.user_service import UserService

logger = logging.getLogger(__name__)


def build_sub_app() -> web.Application:
    app = web.Application()
    # node_service не нужен — подписка только читает (build_user_links без redeploy).
    user_service = UserService(session_factory=async_session_factory)

    async def handle_sub(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        result = await user_service.get_subscription_payload(token)
        if result is None:
            # Не логируем сам токен — только факт промаха.
            logger.info("subscription 404 (unknown/inactive token)")
            raise web.HTTPNotFound()
        body_b64, headers = result
        return web.Response(text=body_b64, headers=headers, content_type="text/plain")

    async def handle_health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/sub/{token}", handle_sub)
    app.router.add_get("/healthz", handle_health)
    return app


async def main() -> None:
    await init_db()
    app = build_sub_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.SUB_HTTP_HOST, settings.SUB_HTTP_PORT)
    await site.start()
    logger.info(
        "Subscription server listening on %s:%s",
        settings.SUB_HTTP_HOST,
        settings.SUB_HTTP_PORT,
    )
    await asyncio.Event().wait()  # держим процесс живым


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
