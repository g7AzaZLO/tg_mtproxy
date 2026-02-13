"""Node Agent — легковесный FastAPI-сервер на каждой ноде MTProxy.

Управляет конфигом mtprotoproxy: добавление/удаление секретов,
перезагрузка конфига через SIGHUP, health-check.

Запуск:
    uvicorn node_agent.agent:app --host 127.0.0.1 --port 9090
"""

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from node_agent.config_manager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# === Конфигурация ===

AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "change-me-to-secret-key")
MTPROXY_CONFIG_PATH = os.environ.get("MTPROXY_CONFIG_PATH", "/opt/mtprotoproxy/config.py")
MTPROXY_PID_FILE = os.environ.get("MTPROXY_PID_FILE", "/opt/mtprotoproxy/mtprotoproxy.pid")

# === Зависимости ===

api_key_header = APIKeyHeader(name="X-API-Key")
config_manager = ConfigManager(
    config_path=MTPROXY_CONFIG_PATH,
    proxy_pid_file=MTPROXY_PID_FILE,
)


def verify_api_key(key: str = Security(api_key_header)) -> str:
    """Проверяет API-ключ из заголовка X-API-Key.

    Args:
        key: Значение из заголовка.

    Returns:
        API-ключ при успешной проверке.

    Raises:
        HTTPException: При невалидном ключе.
    """
    if key != AGENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return key


# === Модели ===

class AddSecretRequest(BaseModel):
    """Запрос на добавление секрета."""

    secret: str
    user_id: int
    label: str = ""


class RemoveSecretRequest(BaseModel):
    """Запрос на удаление секрета."""

    secret: str


# === Приложение ===

app = FastAPI(title="MTProxy Node Agent", docs_url=None, redoc_url=None)


@app.post("/secrets/add")
async def add_secret(
    body: AddSecretRequest,
    _: str = Depends(verify_api_key),
) -> dict:
    """Добавляет секрет в конфиг mtprotoproxy и перезагружает.

    Args:
        body: Параметры секрета.

    Returns:
        Результат операции.
    """
    name = body.label or f"user_{body.user_id}"
    try:
        config_manager.add_secret(name, body.secret)
        reloaded = config_manager.reload_proxy()
        return {
            "ok": True,
            "added": True,
            "reloaded": reloaded,
        }
    except Exception as exc:
        logger.exception("Ошибка добавления секрета")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/secrets/remove")
async def remove_secret(
    body: RemoveSecretRequest,
    _: str = Depends(verify_api_key),
) -> dict:
    """Удаляет секрет из конфига mtprotoproxy и перезагружает.

    Args:
        body: Параметры секрета.

    Returns:
        Результат операции.
    """
    try:
        removed = config_manager.remove_secret(body.secret)
        reloaded = False
        if removed:
            reloaded = config_manager.reload_proxy()
        return {
            "ok": True,
            "removed": removed,
            "reloaded": reloaded,
        }
    except Exception as exc:
        logger.exception("Ошибка удаления секрета")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
async def health_check(_: str = Depends(verify_api_key)) -> dict:
    """Проверяет состояние агента и mtprotoproxy.

    Returns:
        Словарь со статусом и статистикой.
    """
    stats = config_manager.get_stats()
    return {
        "status": "ok",
        "proxy_running": stats["proxy_running"],
        "proxy_pid": stats["proxy_pid"],
        "secrets_count": stats["secrets_count"],
    }


@app.get("/stats")
async def get_stats(_: str = Depends(verify_api_key)) -> dict:
    """Возвращает статистику ноды.

    Returns:
        Словарь со списком секретов (без значений) и статусом.
    """
    stats = config_manager.get_stats()
    secrets = config_manager.get_secrets()
    return {
        **stats,
        "secret_names": list(secrets.keys()),
    }
