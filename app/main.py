"""FastAPI entrypoint: pages, admin API and the /s/{token} relay endpoint."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import current_admin, login, logout, require_admin, verify_password
from .cache import FileCache
from .config import ConfigError, ConfigManager
from .models import (
    AppConfig,
    Subscription,
    SubscriptionCreate,
    SubscriptionUpdate,
)
from .relay import RelayError, relay_fetch, test_source
from .security import generate_token, mask_url, validate_url_sync, SecurityError
from .state import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("subrelay.main")

VERSION = "0.1.0"

BASE_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------- setup


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = ConfigManager()
    try:
        cfg.load()
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
    for note in cfg.bootstrap():
        logger.warning("[首次启动] %s", note)

    cache = FileCache()
    cache.root.mkdir(parents=True, exist_ok=True)
    state = StateStore()
    state.load()

    app.state.cfg = cfg
    app.state.cache = cache
    app.state.state = state
    logger.info("Subscription Relay %s started", VERSION)
    yield


app = FastAPI(title="Subscription Relay", version=VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _cfg(request: Request) -> ConfigManager:
    return request.app.state.cfg


def _cache(request: Request) -> FileCache:
    return request.app.state.cache


def _state(request: Request) -> StateStore:
    return request.app.state.state


def _relay_base_url(request: Request) -> str:
    cfg = _cfg(request)
    if cfg.config.server.public_base_url:
        return cfg.config.server.public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _fmt_ts(ts: str | None) -> str | None:
    """'2026-09-22T06:50:28.025905+00:00' -> '2026-09-22 06:50:28'"""
    if not ts:
        return None
    try:
        return ts.replace("T", " ")[:19]
    except (AttributeError, TypeError):
        return ts


def _sub_view(request: Request, sub: Subscription) -> dict:
    cfg, cache, state = _cfg(request), _cache(request), _state(request)
    ttl = sub.cache_ttl or cfg.config.defaults.cache_ttl
    entry = cache.read(sub.id)
    if entry is None:
        cache_state, cache_size = "None", None
    elif entry.is_fresh(ttl):
        cache_state, cache_size = "Fresh", len(entry.content)
    else:
        cache_state, cache_size = "Stale", len(entry.content)
    st = state.get(sub.id)
    return {
        "id": sub.id,
        "name": sub.name,
        "enabled": sub.enabled,
        "source_url": sub.source_url,
        "source_url_masked": mask_url(sub.source_url),
        "access_token": sub.access_token,
        "relay_url": f"{_relay_base_url(request)}/s/{sub.access_token}",
        "cache_ttl": sub.cache_ttl,
        "user_agent_mode": sub.user_agent_mode or cfg.config.defaults.user_agent_mode,
        "user_agent": sub.user_agent,
        "last_success_at": _fmt_ts(st.last_success_at),
        "last_failure_at": _fmt_ts(st.last_failure_at),
        "last_error": st.last_error,
        "cache_state": cache_state,
        "cache_size": cache_size,
        "online": st.last_failure_at is None
        or (
            st.last_success_at is not None
            and st.last_success_at >= st.last_failure_at
        ),
    }


def _page(
    request: Request, name: str, context: dict, status_code: int = 200
) -> HTMLResponse:
    context.setdefault("version", VERSION)
    context.setdefault("admin_username", current_admin(request))
    return templates.TemplateResponse(
        request, name, context, status_code=status_code
    )


# ---------------------------------------------------------------- relay page


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/s/{token}")
async def relay_subscription(token: str, request: Request):
    cfg, cache, state = _cfg(request), _cache(request), _state(request)
    sub = cfg.find_by_token(token)
    if sub is None or not sub.enabled:
        raise HTTPException(status_code=404, detail="订阅不存在或已停用")

    client_ua = request.headers.get("user-agent")
    try:
        result = await relay_fetch(sub, cfg, cache, state, client_ua)
    except RelayError as exc:
        return PlainTextResponse(
            f"订阅源暂时不可用：{exc}", status_code=502
        )

    headers = dict(result.headers)
    headers["X-Subscription-Cache"] = result.cache_status
    return Response(content=result.content, status_code=200, headers=headers)


# -------------------------------------------------------------- admin pages


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_admin(request):
        return RedirectResponse(url="/admin", status_code=303)
    return _page(request, "login.html", {"error": None})


@app.post("/admin/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    cfg = _cfg(request)
    if not verify_password(cfg, username, password):
        logger.warning("admin login failed for user %r", username)
        return _page(
            request, "login.html", {"error": "用户名或密码错误"}, status_code=401
        )
    response = RedirectResponse(url="/admin", status_code=303)
    login(response, cfg, username)
    logger.info("admin logged in: %s", username)
    return response


@app.post("/admin/logout")
async def logout_submit(request: Request):
    response = RedirectResponse(url="/admin/login", status_code=303)
    logout(response)
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_index(request: Request):
    if not current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    cfg = _cfg(request)
    views = [_sub_view(request, s) for s in cfg.config.subscriptions]
    return _page(request, "index.html", {"subs": views})


@app.get("/admin/subscriptions/new", response_class=HTMLResponse)
async def sub_new(request: Request):
    if not current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return _page(request, "edit.html", {"sub": None})


@app.get("/admin/subscriptions/{sub_id}/edit", response_class=HTMLResponse)
async def sub_edit(sub_id: str, request: Request):
    if not current_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    cfg = _cfg(request)
    sub = cfg.find_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return _page(request, "edit.html", {"sub": _sub_view(request, sub)})


# ---------------------------------------------------------------- admin API


def _validate_source_url(request: Request, source_url: str) -> None:
    allow_private = _cfg(request).config.server.allow_private_networks
    try:
        validate_url_sync(source_url, allow_private)
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail=f"原始订阅地址不合法：{exc}") from exc


def _check_token_unique(cfg: ConfigManager, token: str, exclude_id: str | None = None):
    for sub in cfg.config.subscriptions:
        if sub.access_token == token and sub.id != exclude_id:
            raise HTTPException(status_code=400, detail="Access Token 已被其他订阅使用")


@app.get("/api/subscriptions")
async def api_list(request: Request, _: str = Depends(require_admin)):
    cfg = _cfg(request)
    return {"subscriptions": [_sub_view(request, s) for s in cfg.config.subscriptions]}


@app.post("/api/subscriptions", status_code=201)
async def api_create(
    payload: SubscriptionCreate, request: Request, _: str = Depends(require_admin)
):
    cfg = _cfg(request)
    _validate_source_url(request, payload.source_url)

    sub_id = payload.id or f"sub_{secrets.token_hex(4)}"
    if cfg.find_by_id(sub_id):
        raise HTTPException(status_code=400, detail="ID 已存在")
    token = payload.access_token or generate_token()
    _check_token_unique(cfg, token)

    sub = Subscription(
        id=sub_id,
        name=payload.name,
        source_url=payload.source_url,
        access_token=token,
        enabled=payload.enabled,
        cache_ttl=payload.cache_ttl,
        user_agent_mode=payload.user_agent_mode,
        user_agent=payload.user_agent,
    )
    new_config = cfg.config.model_copy(
        update={"subscriptions": [*cfg.config.subscriptions, sub]}
    )
    await cfg.save(new_config)
    logger.info("subscription created: %s", sub.id)
    return _sub_view(request, sub)


@app.put("/api/subscriptions/{sub_id}")
async def api_update(
    sub_id: str,
    payload: SubscriptionUpdate,
    request: Request,
    _: str = Depends(require_admin),
):
    cfg = _cfg(request)
    old = cfg.find_by_id(sub_id)
    if old is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    _validate_source_url(request, payload.source_url)
    _check_token_unique(cfg, payload.access_token, exclude_id=sub_id)

    sub = Subscription(
        id=sub_id,
        name=payload.name,
        source_url=payload.source_url,
        access_token=payload.access_token,
        enabled=payload.enabled,
        cache_ttl=payload.cache_ttl,
        user_agent_mode=payload.user_agent_mode,
        user_agent=payload.user_agent,
    )
    subs = [sub if s.id == sub_id else s for s in cfg.config.subscriptions]
    await cfg.save(cfg.config.model_copy(update={"subscriptions": subs}))
    logger.info("subscription updated: %s", sub_id)
    return _sub_view(request, sub)


@app.delete("/api/subscriptions/{sub_id}", status_code=204)
async def api_delete(sub_id: str, request: Request, _: str = Depends(require_admin)):
    cfg, cache, state = _cfg(request), _cache(request), _state(request)
    if cfg.find_by_id(sub_id) is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    subs = [s for s in cfg.config.subscriptions if s.id != sub_id]
    await cfg.save(cfg.config.model_copy(update={"subscriptions": subs}))
    cache.delete(sub_id)
    await state.remove(sub_id)
    logger.info("subscription deleted: %s", sub_id)
    return Response(status_code=204)


@app.post("/api/subscriptions/{sub_id}/test")
async def api_test(sub_id: str, request: Request, _: str = Depends(require_admin)):
    cfg = _cfg(request)
    sub = cfg.find_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    ok, message, latency = await test_source(sub, cfg)
    return {"ok": ok, "message": message, "latency_ms": latency}


@app.post("/api/subscriptions/{sub_id}/refresh")
async def api_refresh(sub_id: str, request: Request, _: str = Depends(require_admin)):
    cfg, cache, state = _cfg(request), _cache(request), _state(request)
    sub = cfg.find_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    try:
        result = await relay_fetch(sub, cfg, cache, state, None, force=True)
    except RelayError as exc:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "message": f"刷新失败：{exc}", "cache_status": None},
        )
    return {
        "ok": True,
        "message": f"已刷新，{len(result.content)} 字节",
        "cache_status": result.cache_status,
    }


@app.post("/api/subscriptions/{sub_id}/regenerate-token")
async def api_regenerate_token(
    sub_id: str, request: Request, _: str = Depends(require_admin)
):
    cfg, cache, state = _cfg(request), _cache(request), _state(request)
    sub = cfg.find_by_id(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    new_token = generate_token()
    _check_token_unique(cfg, new_token, exclude_id=sub_id)
    updated = sub.model_copy(update={"access_token": new_token})
    subs = [updated if s.id == sub_id else s for s in cfg.config.subscriptions]
    await cfg.save(cfg.config.model_copy(update={"subscriptions": subs}))
    logger.info("token regenerated for %s (old address invalidated)", sub_id)
    return _sub_view(request, updated)
