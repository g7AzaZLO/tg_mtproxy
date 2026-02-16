"""REST API для веб-админки.

Поддерживает Telegram Login Widget, CRUD по сущностям
и расширенную наблюдаемость нод.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.config import Settings
from src.db import repositories as repo
from src.services.node_manager import NodeManagerService
from src.services.subscription import SubscriptionService

router = APIRouter()
security = HTTPBearer()

_settings: Settings | None = None


def set_settings(settings: Settings) -> None:
    """Устанавливает глобальные настройки для admin API.

    Args:
        settings: Объект конфигурации приложения.
    """
    global _settings  # noqa: PLW0603
    _settings = settings


def _get_settings() -> Settings:
    """Возвращает настройки приложения.

    Returns:
        Инициализированный объект Settings.

    Raises:
        RuntimeError: Если настройки не инициализированы.
    """
    if _settings is None:
        raise RuntimeError("Admin API settings not initialized")
    return _settings


def _issue_token(payload: dict[str, Any]) -> str:
    """Выдаёт JWT access token.

    Args:
        payload: Пользовательский payload без `exp`.

    Returns:
        Подписанный JWT.
    """
    settings = _get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt.expire_minutes)
    full_payload = {**payload, "exp": expires_at}
    return jwt.encode(full_payload, settings.jwt.secret, algorithm=settings.jwt.algorithm)


def _verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict[str, Any]:
    """Проверяет JWT и возвращает payload.

    Args:
        credentials: Bearer-токен из заголовка Authorization.

    Returns:
        Payload токена.

    Raises:
        HTTPException: Если токен истёк или невалиден.
    """
    settings = _get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials,
            settings.jwt.secret,
            algorithms=[settings.jwt.algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def _require_admin(payload: Annotated[dict[str, Any], Depends(_verify_token)]) -> dict[str, Any]:
    """Проверяет, что пользователь в whitelist админов.

    Args:
        payload: JWT payload.

    Returns:
        Payload при успешной авторизации.

    Raises:
        HTTPException: Если доступ запрещён.
    """
    settings = _get_settings()
    telegram_id = payload.get("telegram_id")
    if telegram_id is None:
        return payload
    if int(telegram_id) not in settings.service.admin_ids_set:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")
    return payload


def _verify_telegram_login(body: "TelegramLoginRequest", bot_token: str) -> bool:
    """Верифицирует подпись Telegram Login Widget.

    Args:
        body: Данные входа.
        bot_token: Токен Telegram-бота.

    Returns:
        True, если подпись валидна.
    """
    max_age_seconds = 24 * 60 * 60
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts - int(body.auth_date) > max_age_seconds:
        return False

    payload_items: dict[str, str] = {
        "auth_date": str(body.auth_date),
        "id": str(body.id),
    }
    if body.first_name:
        payload_items["first_name"] = body.first_name
    if body.last_name:
        payload_items["last_name"] = body.last_name
    if body.username:
        payload_items["username"] = body.username
    if body.photo_url:
        payload_items["photo_url"] = body.photo_url

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload_items.items())
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed_hash, body.hash)


def _node_availability_from_health(health: dict[str, Any] | None) -> tuple[str, str]:
    """Строит статус доступности ноды по health payload.

    Args:
        health: Ответ node-agent `/health`.

    Returns:
        Кортеж `(status, reason)`.
    """
    if health is None:
        return "offline", "node-agent недоступен"
    if health.get("status") != "ok":
        return "degraded", "health status != ok"
    proxy_running = bool(health.get("proxy_running"))
    socks5_running = bool(health.get("socks5_running"))
    if proxy_running or socks5_running:
        return "online", "ok"
    return "degraded", "ни один прокси-сервис не запущен"


async def _build_node_observability(
    nodes: list[dict[str, Any]],
    *,
    node_manager: NodeManagerService,
) -> list[dict[str, Any]]:
    """Обогащает список нод полями статуса и загрузки.

    Args:
        nodes: Ноды из БД.
        node_manager: Сервис взаимодействия с node-agent.

    Returns:
        Список нод с observability-полями.
    """
    health_tasks = [
        node_manager.health_check(
            agent_url=str(node["agent_url"]),
            agent_api_key=str(node["agent_api_key"]),
        )
        for node in nodes
    ]
    health_results = await asyncio.gather(*health_tasks, return_exceptions=True)
    now = datetime.now(timezone.utc)
    enriched_nodes: list[dict[str, Any]] = []

    for node, raw_health in zip(nodes, health_results, strict=False):
        health: dict[str, Any] | None = None
        if isinstance(raw_health, dict):
            health = raw_health
        status_name, reason = _node_availability_from_health(health)
        current_users = int(node.get("current_users", 0))
        max_users = max(1, int(node.get("max_users", 1)))
        free_slots = max(0, max_users - current_users)
        load_percent = round((current_users / max_users) * 100, 2)
        enriched_nodes.append(
            {
                **node,
                "availability_status": status_name,
                "availability_reason": reason,
                "last_check_at": now,
                "free_slots": free_slots,
                "load_percent": load_percent,
                "health": health,
            }
        )
    return enriched_nodes


class LoginRequest(BaseModel):
    """Запрос на авторизацию по паролю."""

    username: str
    password: str


class TelegramLoginRequest(BaseModel):
    """Запрос Telegram Login Widget."""

    id: int
    auth_date: int
    hash: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None


class TokenResponse(BaseModel):
    """Ответ с access token."""

    access_token: str
    token_type: str = "bearer"


class UpdateUserRequest(BaseModel):
    """Запрос на обновление пользователя."""

    username: str | None = None
    first_name: str | None = None
    is_banned: bool
    used_trial: bool


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
    socks5_port: int = 1080


class UpdateNodeRequest(CreateNodeRequest):
    """Запрос на обновление ноды."""


class CreatePlanRequest(BaseModel):
    """Запрос на создание плана."""

    name: str
    duration_days: int = Field(ge=1)
    price_usd: float = Field(ge=0)
    is_trial: bool = False
    is_active: bool = True


class UpdatePlanRequest(CreatePlanRequest):
    """Запрос на обновление плана."""


class UpdateSubscriptionRequest(BaseModel):
    """Запрос на обновление подписки."""

    plan_id: int
    node_id: int
    status: Literal["pending", "active", "expiring", "expired", "cancelled"]


class ExtendSubscriptionRequest(BaseModel):
    """Запрос на продление подписки."""

    days: int = Field(ge=1, le=3650)


class RotateSubscriptionRequest(BaseModel):
    """Запрос на ротацию подписки."""

    country: str


class UpdatePaymentRequest(BaseModel):
    """Запрос на обновление платежа."""

    amount_usd: float = Field(ge=0)
    status: Literal["created", "success", "paid", "expired", "cancelled"]
    node_id: int | None = None
    access_type: Literal["mtproto", "socks5"] = "mtproto"


@router.get("/auth/config")
async def auth_config() -> dict[str, Any]:
    """Возвращает настройки авторизации для фронтенда.

    Returns:
        Параметры auth-конфигурации.
    """
    settings = _get_settings()
    return {
        "telegram_login_enabled": True,
        "telegram_bot_name": settings.admin.telegram_bot_name,
    }


@router.post("/login", response_model=TokenResponse)
async def admin_login(body: LoginRequest) -> TokenResponse:
    """Авторизация администратора по логину/паролю (fallback).

    Args:
        body: Логин и пароль.

    Returns:
        JWT access token.
    """
    settings = _get_settings()
    if body.username != settings.admin.username or body.password != settings.admin.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = _issue_token({"sub": body.username, "auth": "password"})
    return TokenResponse(access_token=token)


@router.post("/login/telegram", response_model=TokenResponse)
async def admin_login_telegram(body: TelegramLoginRequest) -> TokenResponse:
    """Авторизация через Telegram Login Widget.

    Args:
        body: Данные Login Widget.

    Returns:
        JWT access token.
    """
    settings = _get_settings()
    if not _verify_telegram_login(body, settings.bot.token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram signature")
    if int(body.id) not in settings.service.admin_ids_set:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin")
    token = _issue_token(
        {
            "sub": str(body.id),
            "telegram_id": int(body.id),
            "username": body.username or "",
            "auth": "telegram",
        }
    )
    return TokenResponse(access_token=token)


@router.get("/users")
async def list_users(
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    limit: int = 50,
    offset: int = 0,
    search: str = "",
) -> dict[str, Any]:
    """Возвращает список пользователей.

    Args:
        limit: Лимит записей.
        offset: Смещение.
        search: Поиск по username.

    Returns:
        Список пользователей и total.
    """
    if search:
        users = await repo.user.search_by_username(search, limit=limit)
        return {"users": users, "total": len(users)}
    users = await repo.user.get_all(limit=limit, offset=offset)
    total = await repo.user.count()
    return {"users": users, "total": total}


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает пользователя по ID."""
    user = await repo.user.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Обновляет данные пользователя."""
    user = await repo.user.update_user(
        user_id,
        username=body.username,
        first_name=body.first_name,
        is_banned=body.is_banned,
        used_trial=body.used_trial,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Удаляет пользователя."""
    ok = await repo.user.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Блокирует пользователя."""
    user = await repo.user.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await repo.user.set_banned(user_id, is_banned=True)
    return {"ok": True}


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Разблокирует пользователя."""
    user = await repo.user.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await repo.user.set_banned(user_id, is_banned=False)
    return {"ok": True}


@router.get("/users/{user_id}/subscriptions")
async def user_subscriptions(
    user_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Возвращает подписки пользователя."""
    subscriptions = await repo.subscription.get_by_user(user_id, limit=limit, offset=offset)
    return {"subscriptions": subscriptions}


@router.get("/users/{user_id}/payments")
async def user_payments(
    user_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Возвращает платежи пользователя."""
    payments = await repo.payment.get_all(limit=limit, offset=offset, user_id=user_id)
    return {"payments": payments}


@router.get("/nodes")
async def list_nodes(
    request: Request,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    include_health: bool = True,
) -> dict[str, Any]:
    """Возвращает ноды с загрузкой и статусом доступности."""
    nodes = await repo.node.get_nodes_with_load()
    if not include_health:
        return {"nodes": nodes}
    node_manager: NodeManagerService = request.app.state.node_manager
    nodes_with_health = await _build_node_observability(nodes, node_manager=node_manager)
    return {"nodes": nodes_with_health}


@router.get("/nodes/{node_id}")
async def get_node(
    request: Request,
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает детальную информацию о ноде."""
    node = await repo.node.get_by_id_with_load(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node_manager: NodeManagerService = request.app.state.node_manager
    enriched = await _build_node_observability([node], node_manager=node_manager)
    return {"node": enriched[0]}


@router.post("/nodes")
async def create_node(
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    body: CreateNodeRequest,
) -> dict[str, Any]:
    """Создаёт новую ноду."""
    node = await repo.node.create(
        name=body.name,
        host=body.host,
        port=body.port,
        country=body.country,
        country_flag=body.country_flag,
        agent_url=body.agent_url,
        agent_api_key=body.agent_api_key,
        max_users=body.max_users,
        socks5_port=body.socks5_port,
    )
    return {"node": node}


@router.put("/nodes/{node_id}")
async def update_node(
    node_id: int,
    body: UpdateNodeRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Обновляет ноду."""
    node = await repo.node.update_node(
        node_id,
        name=body.name,
        host=body.host,
        port=body.port,
        country=body.country,
        country_flag=body.country_flag,
        agent_url=body.agent_url,
        agent_api_key=body.agent_api_key,
        max_users=body.max_users,
        socks5_port=body.socks5_port,
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"node": node}


@router.delete("/nodes/{node_id}")
async def delete_node(
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Удаляет ноду, если на ней нет активных подписок."""
    subscriptions = await repo.subscription.get_by_node(node_id, limit=1, offset=0)
    if subscriptions:
        raise HTTPException(status_code=409, detail="Node has subscriptions")
    ok = await repo.node.delete_node(node_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"ok": True}


@router.patch("/nodes/{node_id}/activate")
async def activate_node(
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Активирует ноду."""
    node = await repo.node.get_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await repo.node.update_active(node_id, is_active=True)
    return {"ok": True}


@router.patch("/nodes/{node_id}/deactivate")
async def deactivate_node(
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Деактивирует ноду."""
    node = await repo.node.get_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await repo.node.update_active(node_id, is_active=False)
    return {"ok": True}


async def _check_node_health(
    node_id: int, *, node_manager: NodeManagerService,
) -> dict[str, Any]:
    """Проверяет health ноды и возвращает результат.

    Args:
        node_id: ID ноды.
        node_manager: Сервис взаимодействия с нодами.

    Returns:
        Словарь со статусом, причиной и raw health.

    Raises:
        HTTPException: Если нода не найдена.
    """
    node = await repo.node.get_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    health = await node_manager.health_check(
        agent_url=node["agent_url"],
        agent_api_key=node["agent_api_key"],
    )
    status_name, reason = _node_availability_from_health(health)
    return {"status": status_name, "reason": reason, "health": health}


@router.get("/nodes/{node_id}/health")
async def node_health(
    request: Request,
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает health-статус ноды."""
    node_manager: NodeManagerService = request.app.state.node_manager
    return await _check_node_health(node_id, node_manager=node_manager)


@router.post("/nodes/{node_id}/test-connection")
async def test_node_connection(
    request: Request,
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Принудительно проверяет доступность node-agent."""
    node_manager: NodeManagerService = request.app.state.node_manager
    return await _check_node_health(node_id, node_manager=node_manager)


@router.get("/nodes/{node_id}/subscriptions")
async def node_subscriptions(
    node_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Возвращает подписки ноды."""
    subscriptions = await repo.subscription.get_by_node(node_id, limit=limit, offset=offset)
    return {"subscriptions": subscriptions}


@router.get("/plans")
async def list_plans(
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает все тарифные планы."""
    plans = await repo.plan.get_all()
    return {"plans": plans}


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает тариф по ID."""
    plan = await repo.plan.get_by_id(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"plan": plan}


@router.post("/plans")
async def create_plan(
    body: CreatePlanRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Создаёт тарифный план."""
    plan = await repo.plan.create(
        name=body.name,
        duration_days=body.duration_days,
        price_usd=body.price_usd,
        is_trial=body.is_trial,
        is_active=body.is_active,
    )
    return {"plan": plan}


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: int,
    body: UpdatePlanRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Обновляет тарифный план."""
    plan = await repo.plan.update_plan(
        plan_id,
        name=body.name,
        duration_days=body.duration_days,
        price_usd=body.price_usd,
        is_trial=body.is_trial,
        is_active=body.is_active,
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"plan": plan}


@router.patch("/plans/{plan_id}/activate")
async def activate_plan(
    plan_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Активирует тариф."""
    ok = await repo.plan.set_active(plan_id, is_active=True)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"ok": True}


@router.patch("/plans/{plan_id}/deactivate")
async def deactivate_plan(
    plan_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Деактивирует тариф."""
    ok = await repo.plan.set_active(plan_id, is_active=False)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"ok": True}


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Удаляет тарифный план."""
    ok = await repo.plan.delete_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"ok": True}


@router.get("/subscriptions")
async def list_subscriptions(
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    limit: int = 50,
    offset: int = 0,
    status_filter: str = "",
) -> dict[str, Any]:
    """Возвращает подписки с фильтрацией по статусу."""
    subscriptions = await repo.subscription.get_all(
        limit=limit,
        offset=offset,
        status=status_filter or None,
    )
    return {"subscriptions": subscriptions}


@router.get("/subscriptions/{subscription_id}")
async def get_subscription(
    subscription_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает детальную подписку."""
    subscription = await repo.subscription.get_detail(subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"subscription": subscription}


@router.put("/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    body: UpdateSubscriptionRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Обновляет базовые поля подписки."""
    sub = await repo.subscription.update_subscription(
        subscription_id,
        plan_id=body.plan_id,
        node_id=body.node_id,
        status=body.status,
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"subscription": sub}


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(
    subscription_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Удаляет подписку."""
    ok = await repo.subscription.delete_subscription(subscription_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"ok": True}


@router.post("/subscriptions/{subscription_id}/extend")
async def extend_subscription(
    subscription_id: int,
    body: ExtendSubscriptionRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Продлевает подписку на `days` дней."""
    sub = await repo.subscription.extend_expiration(subscription_id, days=body.days)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"subscription": sub}


@router.post("/subscriptions/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Переводит подписку в статус cancelled."""
    sub = await repo.subscription.get_by_id(subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await repo.subscription.set_status(subscription_id, "cancelled")
    return {"ok": True}


@router.post("/subscriptions/{subscription_id}/activate")
async def activate_subscription(
    subscription_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Переводит подписку в статус active."""
    sub = await repo.subscription.get_by_id(subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await repo.subscription.set_status(subscription_id, "active")
    return {"ok": True}


@router.post("/subscriptions/{subscription_id}/rotate")
async def rotate_subscription(
    request: Request,
    subscription_id: int,
    body: RotateSubscriptionRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Выполняет ротацию ключа подписки в заданную страну."""
    subscription_service: SubscriptionService = request.app.state.subscription_service
    result = await subscription_service.rotate_key(subscription_id, body.country)
    return {"result": result}


@router.post("/subscriptions/{subscription_id}/change-node")
async def change_subscription_node(
    request: Request,
    subscription_id: int,
    body: RotateSubscriptionRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Переносит подписку на другую ноду через ротацию по стране."""
    subscription_service: SubscriptionService = request.app.state.subscription_service
    result = await subscription_service.rotate_key(subscription_id, body.country)
    return {"result": result}


@router.get("/payments")
async def list_payments(
    _: Annotated[dict[str, Any], Depends(_require_admin)],
    limit: int = 50,
    offset: int = 0,
    status_filter: str = "",
    user_id: int | None = None,
) -> dict[str, Any]:
    """Возвращает платежи с фильтрами."""
    payments = await repo.payment.get_all(
        limit=limit,
        offset=offset,
        status=status_filter or None,
        user_id=user_id,
    )
    return {"payments": payments}


@router.get("/payments/{payment_id}")
async def get_payment(
    payment_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает платеж по ID."""
    payment = await repo.payment.get_detail(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment": payment}


@router.put("/payments/{payment_id}")
async def update_payment(
    payment_id: int,
    body: UpdatePaymentRequest,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Обновляет платёж."""
    payment = await repo.payment.update_payment(
        payment_id,
        amount_usd=body.amount_usd,
        status=body.status,
        node_id=body.node_id,
        access_type=body.access_type,
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment": payment}


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: int,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, bool]:
    """Удаляет платёж."""
    ok = await repo.payment.delete_payment(payment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"ok": True}


@router.get("/stats")
async def get_stats(
    request: Request,
    _: Annotated[dict[str, Any], Depends(_require_admin)],
) -> dict[str, Any]:
    """Возвращает сводную статистику админки."""
    users_count = await repo.user.count()
    active_subs = await repo.subscription.count_active()
    revenue = await repo.payment.get_revenue_stats()
    nodes = await repo.node.get_nodes_with_load()
    node_manager: NodeManagerService = request.app.state.node_manager
    nodes_obs = await _build_node_observability(nodes, node_manager=node_manager)
    online_nodes = sum(1 for n in nodes_obs if n["availability_status"] == "online")
    offline_nodes = sum(1 for n in nodes_obs if n["availability_status"] == "offline")
    avg_load = round(sum(n["load_percent"] for n in nodes_obs) / max(1, len(nodes_obs)), 2)
    return {
        "users_total": users_count,
        "subscriptions_active": active_subs,
        "revenue": revenue,
        "nodes_total": len(nodes_obs),
        "nodes_online": online_nodes,
        "nodes_offline": offline_nodes,
        "nodes_avg_load_percent": avg_load,
        "nodes": nodes_obs,
    }
