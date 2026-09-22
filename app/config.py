"""ConfigManager: load / save / hot-reload data/config.yaml.

Writes are atomic: tmp file + fsync + rename, so a crash mid-write
cannot leave a truncated config behind.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import tempfile
from pathlib import Path

import yaml

from .models import AppConfig, Subscription

logger = logging.getLogger("subrelay.config")

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def data_dir() -> Path:
    override = os.environ.get("SUBRELAY_DATA_DIR")
    return Path(override) if override else DEFAULT_DATA_DIR


class ConfigError(Exception):
    pass


class ConfigManager:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "config.yaml")
        self._config = AppConfig()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ load
    def load(self) -> AppConfig:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            logger.info("config file not found, creating default: %s", self.path)
            self._config = AppConfig()
            self._atomic_write(self._config)
            return self._config
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"config.yaml 解析失败: {exc}") from exc
        if raw is None:
            raw = {}
        try:
            self._config = AppConfig.model_validate(raw)
        except Exception as exc:
            raise ConfigError(f"config.yaml 校验失败: {exc}") from exc
        logger.info("config loaded: %d subscription(s)", len(self._config.subscriptions))
        return self._config

    @property
    def config(self) -> AppConfig:
        return self._config

    # ------------------------------------------------------------------ save
    async def save(self, config: AppConfig) -> None:
        async with self._lock:
            self._atomic_write(config)
            self._config = config
        logger.info("config saved (%d subscription(s))", len(config.subscriptions))

    def _atomic_write(self, config: AppConfig) -> None:
        payload = yaml.safe_dump(
            config.model_dump(), allow_unicode=True, sort_keys=False
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

    # ------------------------------------------------------------- bootstrap
    def bootstrap(self) -> list[str]:
        """Fill in secrets / admin password on first run. Returns log lines
        that must be shown to the operator (never logged again afterwards)."""
        notes: list[str] = []
        cfg = self._config
        dirty = False

        if not cfg.server.session_secret or cfg.server.session_secret == "CHANGE_ME":
            cfg.server.session_secret = secrets.token_urlsafe(32)
            dirty = True
            notes.append("已自动生成 session_secret 并写入 config.yaml")

        if cfg.server.admin_password:
            # 明文密码：启动时计算哈希仅用于内存校验，不回写文件
            cfg.server.admin_password_hash = hash_password(cfg.server.admin_password)
        elif not cfg.server.admin_password_hash:
            env_password = os.environ.get("SUBRELAY_ADMIN_PASSWORD")
            if env_password:
                password = env_password
                notes.append("管理员密码来自环境变量 SUBRELAY_ADMIN_PASSWORD")
            else:
                password = secrets.token_urlsafe(9)
                notes.append(f"已生成随机管理员密码，请立即记录：{password}")
            cfg.server.admin_password_hash = hash_password(password)
            dirty = True

        if dirty:
            self._atomic_write(cfg)
        return notes

    # -------------------------------------------------------------- lookups
    def find_by_token(self, token: str) -> Subscription | None:
        for sub in self._config.subscriptions:
            if sub.access_token == token:
                return sub
        return None

    def find_by_id(self, sub_id: str) -> Subscription | None:
        for sub in self._config.subscriptions:
            if sub.id == sub_id:
                return sub
        return None


# bcrypt lives here to avoid a circular import (security.py imports models only).
def hash_password(plain: str) -> str:
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
