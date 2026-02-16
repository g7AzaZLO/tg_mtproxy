"""Точка входа приложения.

Запускает параллельно:
1. Telegram-бот (aiogram, long polling)
2. FastAPI веб-сервер (uvicorn, для webhook-ов и админки)
3. APScheduler (фоновые задачи)

Запуск:
    python -m src.main
"""

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers import admin, buy, my_proxies, start
from src.bot.handlers.admin import set_admin_ids
from src.bot.middlewares.throttle import BanCheckMiddleware, ThrottleMiddleware, UserMiddleware
from src.config import get_settings
from src.db.pool import close_pool, init_pool
from src.services.marzban import MarzbanService
from src.services.node_manager import NodeManagerService
from src.services.payment import PaymentService
from src.services.scheduler import create_scheduler
from src.services.subscription import SubscriptionService
from src.web.app import create_app
from src.web.routes.admin_api import set_settings as set_admin_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Инициализирует все компоненты и запускает приложение."""
    settings = get_settings()

    # === Инициализация БД ===
    await init_pool(settings.db)
    logger.info("БД подключена")

    # === Админы бота ===
    set_admin_ids(settings.service.admin_ids_set)
    logger.info("Админы бота: %s", settings.service.admin_ids_set)

    # === Сервисы ===
    node_manager = NodeManagerService()
    payment_service = PaymentService(settings.cryptocloud)
    marzban_service = (
        MarzbanService(settings.marzban)
        if settings.marzban.admin_password
        else None
    )
    subscription_service = SubscriptionService(node_manager, marzban=marzban_service)

    # === Telegram Bot ===
    bot = Bot(
        token=settings.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware (порядок важен: throttle -> user -> ban)
    dp.message.middleware(ThrottleMiddleware(rate_limit=0.5))
    dp.message.middleware(UserMiddleware())
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(ThrottleMiddleware(rate_limit=0.3))
    dp.callback_query.middleware(UserMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())

    # Хэндлеры
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(my_proxies.router)
    dp.include_router(admin.router)

    # Внедрение зависимостей для хэндлеров через workflow_data
    dp.workflow_data.update({
        "payment_service": payment_service,
        "subscription_service": subscription_service,
    })

    # === FastAPI ===
    web_app = create_app()
    set_admin_settings(settings)

    # Сохраняем ссылки на сервисы в app.state для доступа из route-ов
    web_app.state.bot = bot
    web_app.state.subscription_service = subscription_service
    web_app.state.payment_service = payment_service
    web_app.state.settings = settings

    # === Scheduler ===
    scheduler = create_scheduler(
        bot=bot,
        subscription_service=subscription_service,
        node_manager=node_manager,
    )

    # === Запуск ===
    try:
        scheduler.start()
        logger.info("Планировщик запущен")

        # Запускаем FastAPI и бот параллельно
        uvicorn_config = uvicorn.Config(
            app=web_app,
            host=settings.web.host,
            port=settings.web.port,
            log_level="info",
        )
        server = uvicorn.Server(uvicorn_config)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(dp.start_polling(bot), name="bot-polling")
            tg.create_task(server.serve(), name="web-server")

    finally:
        scheduler.shutdown(wait=False)
        await payment_service.close()
        if marzban_service:
            await marzban_service.close()
        await close_pool()
        await bot.session.close()
        logger.info("Приложение остановлено")


if __name__ == "__main__":
    asyncio.run(main())
