"""FastAPI приложение — webhook-и, admin API и админ-статика."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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

    admin_dir = Path("src/web/admin_panel")
    if admin_dir.exists():
        app.mount("/admin", StaticFiles(directory=admin_dir, html=True), name="admin")

    return app
