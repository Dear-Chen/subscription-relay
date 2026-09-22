"""File-based cache: data/cache/{sub_id}/content.bin + meta.json.

No database, no Redis — just the filesystem. Layout:

    data/cache/
    ├── airport_a/
    │   ├── content.bin
    │   └── meta.json
    └── airport_b/
        ├── content.bin
        └── meta.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import data_dir

logger = logging.getLogger("subrelay.cache")

CACHE_SCHEMA_VERSION = 1


@dataclass
class CacheEntry:
    content: bytes
    updated_at: datetime
    status_code: int
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)

    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds()

    def is_fresh(self, ttl: int) -> bool:
        return self.age_seconds() < ttl


class FileCache:
    def __init__(self, root: Path | None = None):
        self.root = root or (data_dir() / "cache")
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    def _dir(self, sub_id: str) -> Path:
        return self.root / sub_id

    def _meta_path(self, sub_id: str) -> Path:
        return self._dir(sub_id) / "meta.json"

    def _content_path(self, sub_id: str) -> Path:
        return self._dir(sub_id) / "content.bin"

    async def _lock_for(self, sub_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(sub_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[sub_id] = lock
            return lock

    # ------------------------------------------------------------------ read
    def read(self, sub_id: str) -> CacheEntry | None:
        meta_path = self._meta_path(sub_id)
        content_path = self._content_path(sub_id)
        if not meta_path.exists() or not content_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            updated_at = datetime.fromisoformat(meta["updated_at"])
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            content = content_path.read_bytes()
            return CacheEntry(
                content=content,
                updated_at=updated_at,
                status_code=int(meta.get("status_code", 200)),
                content_type=str(meta.get("content_type", "application/octet-stream")),
                headers={str(k): str(v) for k, v in meta.get("headers", {}).items()},
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("cache unreadable for %s, ignoring: %s", sub_id, exc)
            return None

    # ----------------------------------------------------------------- write
    async def write(
        self,
        sub_id: str,
        content: bytes,
        status_code: int,
        content_type: str,
        headers: dict[str, str],
    ) -> None:
        lock = await self._lock_for(sub_id)
        async with lock:
            target_dir = self._dir(sub_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "schema": CACHE_SCHEMA_VERSION,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "status_code": status_code,
                "content_type": content_type,
                "headers": headers,
            }
            self._atomic_write(
                self._meta_path(sub_id),
                json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            self._atomic_write(self._content_path(sub_id), content)
        logger.info("cache written for %s (%d bytes)", sub_id, len(content))

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ---------------------------------------------------------------- delete
    def delete(self, sub_id: str) -> None:
        target_dir = self._dir(sub_id)
        if not target_dir.exists():
            return
        for child in target_dir.iterdir():
            child.unlink(missing_ok=True)
        target_dir.rmdir()
        logger.info("cache deleted for %s", sub_id)
