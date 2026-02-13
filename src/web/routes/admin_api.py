"""REST API для веб-админки.

Все эндпоинты защищены JWT-аутентификацией.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import bcrypt
from pydantic import BaseModel

from src.config import Settings
from src.db import repositories as repo

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()

# Глобальные настройки — устанавливаются из main.py
_settings: Settings | None = None


def set_settings(settings: Settings) -> None:
    """Устанавливает глобальные настройки для admin API.

    Args:
        settings: Объект настроек приложения.
    """
    global _settings  # noqa: PLW0603
    _settings = settings


def _get_settings() -> Settings:
    """Возвращает настройки или бросает исключение.

    Returns:
        Объект Settings.

    Raises:
        RuntimeError: Если настройки не инициализированы.
    """
    if _settings is None:
        raise RuntimeError("Admin API settings not initialized")
    return _settings


def _verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> str:
    """Проверяет JWT-токен из заголовка Authorization.

    Args:
        credentials: Данные авторизации (Bearer token).

    Returns:
        Username из payload токена.

    Raises:
        HTTPException: При невалидном или истекшем токене.
    """
    settings = _get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt.secret,
            algorithms=[settings.jwt.algorithm],
        )
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# === Auth ===

class LoginRequest(BaseModel):
    """Запрос на авторизацию."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Ответ с JWT-токеном."""

    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def admin_login(body: LoginRequest) -> TokenResponse:
    """Авторизация администратора.

    Args:
        body: Логин и пароль.

    Returns:
        JWT access-токен.

    Raises:
        HTTPException: При неверных учётных данных.
    """
    settings = _get_settings()
    if body.username != settings.admin.username or body.password != settings.admin.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt.expire_minutes)
    payload = {"sub": body.username, "exp": expire}
    token = jwt.encode(payload, settings.jwt.secret, algorithm=settings.jwt.algorithm)
    return TokenResponse(access_token=token)


# === Users ===

@router.get("/users")
async def list_users(
    _: Annotated[str, Depends(_verify_token)],
    limit: int = 50,
    offset: int = 0,
    search: str = "",
) -> dict:
    """Список пользователей с пагинацией и поиском.

    Args:
        limit: Максимальное количество записей.
        offset: Смещение.
        search: Подстрока для поиска по username.

    Returns:
        Словарь с users и total.
    """
    if search:
        users = await repo.user.search_by_username(search, limit=limit)
        return {"users": users, "total": len(users)}
    users = await repo.user.get_all(limit=limit, offset=offset)
    total = await repo.user.count()
    return {"users": users, "total": total}


# === Nodes ===

@router.get("/nodes")
async def list_nodes(_: Annotated[str, Depends(_verify_token)]) -> dict:
    """Список нод с загрузкой.

    Returns:
        Словарь с nodes.
    """
    nodes = await repo.node.get_nodes_with_load()
    return {"nodes": nodes}


class CreateNodeRequest(BaseModel):
    """Запрос на создание ноды."""

    name: str
    host: str
    port: int = 443
    country: str
    country_flag: str
    agent_url: str
    agent_api_key: str
    max_users: int = 500


@router.post("/nodes")
async def create_node(
    _: Annotated[str, Depends(_verify_token)],
    body: CreateNodeRequest,
) -> dict:
    """Создаёт новую ноду.

    Args:
        body: Параметры ноды.

    Returns:
        Данные созданной ноды.
    """
    node = await repo.node.create(
        name=body.name,
        host=body.host,
        port=body.port,
        country=body.country,
        country_flag=body.country_flag,
        agent_url=body.agent_url,
        agent_api_key=body.agent_api_key,
        max_users=body.max_users,
    )
    return {"node": node}


# === Subscriptions ===

@router.get("/subscriptions")
async def list_subscriptions(
    _: Annotated[str, Depends(_verify_token)],
    limit: int = 50,
    offset: int = 0,
    status_filter: str = "",
) -> dict:
    """Список подписок с фильтрацией.

    Args:
        limit: Максимальное количество записей.
        offset: Смещение.
        status_filter: Фильтр по статусу.

    Returns:
        Словарь с subscriptions.
    """
    subscriptions = await repo.subscription.get_all(
        limit=limit,
        offset=offset,
        status=status_filter or None,
    )
    return {"subscriptions": subscriptions}


# === Stats ===

@router.get("/stats")
async def get_stats(_: Annotated[str, Depends(_verify_token)]) -> dict:
    """Сводная статистика сервиса.

    Returns:
        Словарь со статистикой пользователей, подписок и доходов.
    """
    users_count = await repo.user.count()
    active_subs = await repo.subscription.count_active()
    revenue = await repo.payment.get_revenue_stats()

    return {
        "users_total": users_count,
        "subscriptions_active": active_subs,
        "revenue": revenue,
    }
