"""FastAPI приложение — webhook-и, admin API."""

from fastapi import FastAPI

from src.web.routes.admin_api import router as admin_router
from src.web.routes.webhooks import router as webhook_router


def create_app() -> FastAPI:
    """Создаёт и конфигурирует FastAPI приложение.

    Returns:
        Сконфигурированный экземпляр FastAPI.
    """
    app = FastAPI(
        title="MTProxy Service API",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    return app
