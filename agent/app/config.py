"""服务配置：全部从环境变量读取（不落盘、不入库）。"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """agent 服务运行期配置。"""

    # 服务间调用 JWT（Java aioa-server 签发的 service JWT，RS256，5min）
    # M1 仅记录日志，不强制校验；M2 启用校验。
    service_jwt_secret: str = Field(default="", alias="SERVICE_JWT_SECRET")

    # Java 业务后端地址，agent 回调（tools/invoke、runs 上报）使用
    aioa_server_base_url: str = Field(default="http://aioa-server:8080", alias="AIOA_SERVER_BASE_URL")

    # 默认模型引用，对应 model_gateway/providers.yaml 中的 key
    model_default: str = Field(default="echo", alias="MODEL_DEFAULT")

    # 数据库（M2+ 持久化会话/审批），M1 不连接
    pg_dsn: str = Field(default="", alias="PG_DSN")

    # 服务监听
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def _load() -> Settings:
    return Settings(
        **{
            "SERVICE_JWT_SECRET": os.getenv("SERVICE_JWT_SECRET", ""),
            "AIOA_SERVER_BASE_URL": os.getenv("AIOA_SERVER_BASE_URL", "http://aioa-server:8080"),
            "MODEL_DEFAULT": os.getenv("MODEL_DEFAULT", "echo"),
            "PG_DSN": os.getenv("PG_DSN", ""),
            "HOST": os.getenv("HOST", "0.0.0.0"),
            "PORT": os.getenv("PORT", "8000"),
            "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        }
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局配置单例（测试用 get_settings.cache_clear() 重置）。"""
    return _load()


settings = get_settings()
