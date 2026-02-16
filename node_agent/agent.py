"""Node Agent — легковесный FastAPI-сервер на каждой ноде MTProxy.

Управляет конфигом mtprotoproxy: добавление/удаление секретов,
а также 3proxy: добавление/удаление SOCKS5-пользователей.

Запуск:
    uvicorn node_agent.agent:app --host 127.0.0.1 --port 9090
"""

from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from config_manager import ConfigManager
from socks5_manager import Socks5Manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# === Конфигурация ===

AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "change-me-to-secret-key")
MTPROXY_CONFIG_PATH = os.environ.get("MTPROXY_CONFIG_PATH", "/opt/mtprotoproxy/config.py")
MTPROXY_PID_FILE = os.environ.get("MTPROXY_PID_FILE", "/opt/mtprotoproxy/mtprotoproxy.pid")
SOCKS5_PASSWD_PATH = os.environ.get("SOCKS5_PASSWD_PATH", "/opt/3proxy/passwd")
SOCKS5_CONFIG_PATH = os.environ.get("SOCKS5_CONFIG_PATH", "/opt/3proxy/3proxy.cfg")

# === Зависимости ===

api_key_header = APIKeyHeader(name="X-API-Key")
config_manager = ConfigManager(
    config_path=MTPROXY_CONFIG_PATH,
    proxy_pid_file=MTPROXY_PID_FILE,
)
socks5_manager = Socks5Manager(
    passwd_path=SOCKS5_PASSWD_PATH,
    config_path=SOCKS5_CONFIG_PATH,
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


class AddSocks5UserRequest(BaseModel):
    """Запрос на добавление SOCKS5-пользователя."""

    username: str
    password: str


class RemoveSocks5UserRequest(BaseModel):
    """Запрос на удаление SOCKS5-пользователя."""

    username: str


# === Приложение ===

app = FastAPI(title="MTProxy Node Agent", docs_url=None, redoc_url=None)


# --- MTProto секреты ---

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
        return {"ok": True, "added": True, "reloaded": reloaded}
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
        return {"ok": True, "removed": removed, "reloaded": reloaded}
    except Exception as exc:
        logger.exception("Ошибка удаления секрета")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- SOCKS5 пользователи ---

@app.post("/socks5/add")
async def add_socks5_user(
    body: AddSocks5UserRequest,
    _: str = Depends(verify_api_key),
) -> dict:
    """Добавляет SOCKS5-пользователя в 3proxy и перезагружает.

    Args:
        body: Логин и пароль.

    Returns:
        Результат операции.
    """
    try:
        socks5_manager.add_user(body.username, body.password)
        reloaded = socks5_manager.reload_proxy()
        return {"ok": True, "added": True, "reloaded": reloaded}
    except Exception as exc:
        logger.exception("Ошибка добавления SOCKS5 пользователя")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/socks5/remove")
async def remove_socks5_user(
    body: RemoveSocks5UserRequest,
    _: str = Depends(verify_api_key),
) -> dict:
    """Удаляет SOCKS5-пользователя из 3proxy и перезагружает.

    Args:
        body: Логин для удаления.

    Returns:
        Результат операции.
    """
    try:
        removed = socks5_manager.remove_user(body.username)
        reloaded = False
        if removed:
            reloaded = socks5_manager.reload_proxy()
        return {"ok": True, "removed": removed, "reloaded": reloaded}
    except Exception as exc:
        logger.exception("Ошибка удаления SOCKS5 пользователя")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- Общее ---

@app.get("/health")
async def health_check(_: str = Depends(verify_api_key)) -> dict:
    """Проверяет состояние агента, mtprotoproxy и 3proxy.

    Returns:
        Словарь со статусом и статистикой.
    """
    mt_stats = config_manager.get_stats()
    s5_stats = socks5_manager.get_stats()
    return {
        "status": "ok",
        "proxy_running": mt_stats["proxy_running"],
        "proxy_pid": mt_stats["proxy_pid"],
        "secrets_count": mt_stats["secrets_count"],
        **s5_stats,
    }


@app.get("/stats")
async def get_stats(_: str = Depends(verify_api_key)) -> dict:
    """Возвращает статистику ноды.

    Returns:
        Словарь со списком секретов и SOCKS5-пользователей.
    """
    mt_stats = config_manager.get_stats()
    secrets = config_manager.get_secrets()
    s5_stats = socks5_manager.get_stats()
    s5_users = socks5_manager.get_users()
    return {
        **mt_stats,
        "secret_names": list(secrets.keys()),
        **s5_stats,
        "socks5_usernames": list(s5_users.keys()),
    }
