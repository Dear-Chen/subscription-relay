"""Subscription relay core: fetch upstream, handle cache, pass headers.

Request flow (per Project.md §10):

    收到请求 -> 查找 token -> 检查 enabled -> 检查缓存
      - Fresh        -> 直接返回            (X-Subscription-Cache: hit)
      - 访问原始订阅  -> 成功 -> 保存缓存    (X-Subscription-Cache: miss)
                     -> 失败 -> 有旧缓存    (X-Subscription-Cache: stale)
                            -> 无缓存       -> 返回错误
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .cache import FileCache
from .config import ConfigManager
from .models import Subscription
from .security import SecurityError, validate_url
from .state import StateStore

logger = logging.getLogger("subrelay.relay")

# Header whitelist forwarded to clients (Project.md §14). Lower-case keys.
PASSTHROUGH_HEADERS = {
    "content-type",
    "subscription-userinfo",
    "profile-update-interval",
    "profile-web-page-url",
    "content-disposition",
}

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


class RelayError(Exception):
    """Upstream fetch failed with no cache available."""


@dataclass
class RelayResult:
    content: bytes
    status_code: int
    headers: dict[str, str]
    cache_status: str  # hit | miss | stale


# Single-flight per subscription: concurrent requests for the same sub share
# one upstream fetch instead of stampeding the provider.
_fetch_locks: dict[str, asyncio.Lock] = {}
_fetch_locks_guard = asyncio.Lock()


async def _lock_for(sub_id: str) -> asyncio.Lock:
    async with _fetch_locks_guard:
        lock = _fetch_locks.get(sub_id)
        if lock is None:
            lock = asyncio.Lock()
            _fetch_locks[sub_id] = lock
        return lock


def resolve_user_agent(
    sub: Subscription, cfg: ConfigManager, client_ua: str | None
) -> str:
    mode = sub.user_agent_mode or cfg.config.defaults.user_agent_mode
    if mode == "fixed":
        return sub.user_agent or cfg.config.defaults.user_agent
    return client_ua or cfg.config.defaults.user_agent


def _pick_headers(resp: httpx.Response) -> dict[str, str]:
    picked = {
        name: value
        for name, value in resp.headers.items()
        if name.lower() in PASSTHROUGH_HEADERS
    }
    return picked


async def _fetch_upstream(
    sub: Subscription, cfg: ConfigManager, client_ua: str | None
) -> tuple[bytes, int, dict[str, str]]:
    """Fetch the source URL. Returns (content, status_code, headers).

    Redirects are followed manually so every hop re-passes SSRF validation.
    Raises RelayError on any failure.
    """
    defaults = cfg.config.defaults
    allow_private = cfg.config.server.allow_private_networks
    url = sub.source_url
    headers = {"User-Agent": resolve_user_agent(sub, cfg, client_ua)}

    timeout = httpx.Timeout(
        connect=defaults.connect_timeout,
        read=defaults.read_timeout,
        write=defaults.read_timeout,
        pool=defaults.connect_timeout,
    )
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)

    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            for _ in range(MAX_REDIRECTS + 1):
                try:
                    await validate_url(url, allow_private)
                except SecurityError as exc:
                    raise RelayError(f"SSRF 拦截: {exc}") from exc

                redirect_to: str | None = None
                try:
                    async with client.stream(
                        "GET", url, headers=headers, follow_redirects=False
                    ) as resp:
                        if (
                            resp.status_code in REDIRECT_STATUSES
                            and "location" in resp.headers
                        ):
                            redirect_to = urljoin(url, resp.headers["location"])
                        elif 200 <= resp.status_code < 300:
                            size = 0
                            chunks: list[bytes] = []
                            async for chunk in resp.aiter_bytes():
                                size += len(chunk)
                                if size > defaults.max_response_size:
                                    raise RelayError(
                                        f"源站响应超过大小限制 "
                                        f"{defaults.max_response_size} 字节"
                                    )
                                chunks.append(chunk)
                            picked = _pick_headers(resp)
                            if not any(
                                k.lower() == "content-type" for k in picked
                            ):
                                picked["Content-Type"] = resp.headers.get(
                                    "content-type", "application/octet-stream"
                                )
                            return b"".join(chunks), resp.status_code, picked
                        else:
                            raise RelayError(f"HTTP {resp.status_code}")
                except RelayError:
                    raise
                except httpx.ConnectTimeout as exc:
                    raise RelayError("连接源站超时") from exc
                except httpx.ReadTimeout as exc:
                    raise RelayError("读取源站响应超时") from exc
                except httpx.ConnectError as exc:
                    raise RelayError(f"无法连接源站: {exc.__class__.__name__}") from exc
                except httpx.HTTPError as exc:
                    raise RelayError(f"请求源站失败: {exc}") from exc

                if redirect_to is not None:
                    url = redirect_to
                    continue
                raise RelayError("重定向次数过多")

            raise RelayError("重定向次数过多")
    except RelayError:
        raise
    except Exception as exc:  # httpx.TimeoutException etc.
        raise RelayError(f"请求源站失败: {exc}") from exc


async def relay_fetch(
    sub: Subscription,
    cfg: ConfigManager,
    cache: FileCache,
    state: StateStore,
    client_ua: str | None,
    write_cache: bool = True,
    force: bool = False,
) -> RelayResult:
    """Serve a subscription: cache hit -> upstream -> stale fallback.

    force=True bypasses fresh-cache checks (manual refresh / test).
    """
    ttl = sub.cache_ttl or cfg.config.defaults.cache_ttl
    entry = cache.read(sub.id)

    if not force and entry is not None and entry.is_fresh(ttl):
        logger.info("subscription %s: cache hit", sub.id)
        return RelayResult(entry.content, entry.status_code, entry.headers, "hit")

    lock = await _lock_for(sub.id)
    async with lock:
        # Re-check after acquiring the lock: another request may have refreshed.
        entry = cache.read(sub.id)
        if not force and entry is not None and entry.is_fresh(ttl):
            return RelayResult(entry.content, entry.status_code, entry.headers, "hit")

        try:
            content, status, headers = await _fetch_upstream(sub, cfg, client_ua)
        except RelayError as exc:
            await state.record_failure(sub.id, str(exc))
            if entry is not None:
                logger.warning(
                    "subscription %s: upstream failed (%s), serving stale cache",
                    sub.id,
                    exc,
                )
                return RelayResult(entry.content, entry.status_code, entry.headers, "stale")
            logger.error("subscription %s: upstream failed (%s), no cache", sub.id, exc)
            raise

        await state.record_success(sub.id)
        if write_cache:
            content_type = headers.get("Content-Type", "application/octet-stream")
            await cache.write(sub.id, content, status, content_type, headers)
        logger.info("subscription %s: fetched from upstream", sub.id)
        return RelayResult(content, status, headers, "miss")


async def test_source(
    sub: Subscription, cfg: ConfigManager, client_ua: str | None = None
) -> tuple[bool, str, int | None]:
    """Probe the source URL without touching the cache. Returns
    (ok, message, latency_ms)."""
    start = time.monotonic()
    try:
        content, status, _ = await _fetch_upstream(sub, cfg, client_ua)
    except RelayError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    latency = int((time.monotonic() - start) * 1000)
    return True, f"HTTP {status}，{len(content)} 字节，{latency} ms", latency
