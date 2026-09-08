"""服务配置：环境变量 + agent/.env（敏感凭据，不入库不入 git）。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


def _load_dotenv() -> None:
    """轻量 .env 加载：读 agent/.env 的 KEY=VALUE 注入环境变量。

    规则：已存在的环境变量优先（不覆盖），支持 # 注释与引号值；
    不引入 python-dotenv 依赖。
    """
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.is_file():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass  # .env 不可读不算致命，继续用环境变量


_load_dotenv()


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
