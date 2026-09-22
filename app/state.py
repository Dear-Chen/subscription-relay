"""Runtime state per subscription (last success / failure / error).

Persisted in data/state.yaml so status survives restarts. Small file,
atomic writes, no database.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import data_dir

logger = logging.getLogger("subrelay.state")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubState:
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error: str | None = None


class StateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "state.yaml")
        self._states: dict[str, SubState] = {}
        self._lock = asyncio.Lock()

    def load(self) -> None:
        if not self.path.exists():
            self._states = {}
            return
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            subs = raw.get("subscriptions", {}) or {}
            self._states = {
                str(k): SubState(
                    last_success_at=v.get("last_success_at"),
                    last_failure_at=v.get("last_failure_at"),
                    last_error=v.get("last_error"),
                )
                for k, v in subs.items()
                if isinstance(v, dict)
            }
        except (yaml.YAMLError, OSError, AttributeError) as exc:
            logger.warning("state.yaml unreadable, starting fresh: %s", exc)
            self._states = {}

    def get(self, sub_id: str) -> SubState:
        return self._states.get(sub_id) or SubState()

    async def record_success(self, sub_id: str) -> None:
        state = self._states.setdefault(sub_id, SubState())
        state.last_success_at = _now_iso()
        state.last_error = None  # 恢复后清掉错误信息；最后失败时间保留作历史
        await self._save()

    async def record_failure(self, sub_id: str, error: str) -> None:
        state = self._states.setdefault(sub_id, SubState())
        state.last_failure_at = _now_iso()
        state.last_error = error
        await self._save()

    async def remove(self, sub_id: str) -> None:
        if sub_id in self._states:
            del self._states[sub_id]
            await self._save()

    async def _save(self) -> None:
        async with self._lock:
            payload = yaml.safe_dump(
                {
                    "subscriptions": {
                        k: {
                            "last_success_at": v.last_success_at,
                            "last_failure_at": v.last_failure_at,
                            "last_error": v.last_error,
                        }
                        for k, v in sorted(self._states.items())
                    }
                },
                allow_unicode=True,
                sort_keys=False,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self.path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
