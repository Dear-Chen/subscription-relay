"""Pydantic models describing the YAML configuration."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Subscription(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2048)
    access_token: str = Field(min_length=1, max_length=128)
    enabled: bool = True

    cache_ttl: int | None = Field(default=None, gt=0)
    user_agent_mode: str | None = None  # "passthrough" | "fixed"; None -> defaults
    user_agent: str | None = Field(default=None, max_length=256)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not ID_PATTERN.match(v):
            raise ValueError("id 只允许字母、数字、下划线和中划线，长度 1-64")
        return v

    @field_validator("user_agent_mode")
    @classmethod
    def _check_ua_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in ("passthrough", "fixed"):
            raise ValueError("user_agent_mode 必须是 passthrough 或 fixed")
        return v


class ServerConfig(BaseModel):
    public_base_url: str = ""
    admin_username: str = "admin"
    # 明文密码，优先于 admin_password_hash；启动时在内存中计算哈希，不回写文件
    admin_password: str = ""
    admin_password_hash: str = ""
    session_secret: str = ""
    session_max_age: int = Field(default=7 * 24 * 3600, gt=0)
    allow_private_networks: bool = False


class DefaultsConfig(BaseModel):
    cache_ttl: int = Field(default=1800, gt=0)
    connect_timeout: float = Field(default=5.0, gt=0, le=120)
    read_timeout: float = Field(default=15.0, gt=0, le=300)
    max_response_size: int = Field(default=5 * 1024 * 1024, gt=0)
    user_agent_mode: str = "passthrough"
    user_agent: str = "SubscriptionRelay/0.1.0"

    @field_validator("user_agent_mode")
    @classmethod
    def _check_ua_mode(cls, v: str) -> str:
        if v not in ("passthrough", "fixed"):
            raise ValueError("user_agent_mode 必须是 passthrough 或 fixed")
        return v


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    subscriptions: list[Subscription] = Field(default_factory=list)


# --------------------------------------------------------------------- API


class SubscriptionCreate(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2048)
    access_token: str = Field(default="", max_length=128)  # 空则自动生成
    enabled: bool = True
    cache_ttl: int | None = Field(default=None, gt=0)
    user_agent_mode: str | None = None
    user_agent: str | None = Field(default=None, max_length=256)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str | None) -> str | None:
        if v is not None and not ID_PATTERN.match(v):
            raise ValueError("id 只允许字母、数字、下划线和中划线，长度 1-64")
        return v

    @field_validator("user_agent_mode")
    @classmethod
    def _check_ua_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in ("passthrough", "fixed"):
            raise ValueError("user_agent_mode 必须是 passthrough 或 fixed")
        return v


class SubscriptionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2048)
    access_token: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    cache_ttl: int | None = Field(default=None, gt=0)
    user_agent_mode: str | None = None
    user_agent: str | None = Field(default=None, max_length=256)

    @field_validator("user_agent_mode")
    @classmethod
    def _check_ua_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in ("passthrough", "fixed"):
            raise ValueError("user_agent_mode 必须是 passthrough 或 fixed")
        return v
