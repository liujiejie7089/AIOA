"""服务配置：agent/.env（模块唯一配置入口，不入库）+ 环境变量。

优先级：已存在的环境变量 > agent/.env > 代码默认值。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from aios_ai.security.service_jwt import DEV_SECRET as DEV_SERVICE_JWT_SECRET


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

    # 服务间调用 JWT（Java aios-server 签发的 service JWT，HS256，5min）。
    # **默认值与 Java 侧 DevSecretPlaceholders.SERVICE_JWT 逐字相同**，否则本地开发会全 401。
    # `/internal/v1/*` 已强制校验（见 app/main.py 的中间件）；生产用 SERVICE_JWT_SECRET 覆盖。
    service_jwt_secret: str = Field(default=DEV_SERVICE_JWT_SECRET, alias="SERVICE_JWT_SECRET")

    # Java 业务后端地址，agent 回调（tools/invoke、runs 上报）使用
    aios_server_base_url: str = Field(default="http://aios-server:8080", alias="AIOS_SERVER_BASE_URL")

    # 默认模型引用，对应 model_gateway 注册表中的 key（echo/deepseek/dashscope/vllm/ollama）
    model_default: str = Field(default="echo", alias="MODEL_DEFAULT")

    # 决策轮是否走上游 SSE 流式（True=真实增量直出；False=非流式取回后本地切片）
    agent_stream: bool = Field(default=True, alias="AGENT_STREAM")

    # 一轮内多个工具调用是否并发执行（依赖由模型给出的顺序决定，彼此独立时收益最大）
    agent_parallel_tools: bool = Field(default=True, alias="AGENT_PARALLEL_TOOLS")

    # 一轮内并发执行的上限（与编排器同义，防止一次把业务网关打满）
    agent_max_concurrency: int = Field(default=4, alias="AGENT_MAX_CONCURRENCY")

    # 数据库（M2+ 持久化会话/审批），M1 不连接
    pg_dsn: str = Field(default="", alias="PG_DSN")

    # HITL（人工澄清）：开启后图挂 checkpointer，模型可调用 ask_user 暂停等待用户选择，
    # 由 /internal/v1/runs/{id}/resume 续跑。**默认关** —— 关闭时链路与既有实现逐字节一致
    # （不挂 checkpointer、不注入 ask_user 工具），既有契约零回归。
    agent_hitl: bool = Field(default=False, alias="AIOS_HITL")

    # 挂起态存储连接串（仅 agent_hitl=true 时使用）；**留空 = 内存（本地默认）**：
    #    （空）/ memory        —— InMemorySaver，本地零依赖；进程重启即丢
    #    redis://host:port/db  —— 生产用（本项目生产环境的 Redis）；**必须是 Redis Stack**
    #                             （RediSearch + RedisJSON），普通 Redis 会 FT.INFO 失败
    #    sqlite:///<path>      —— 可选：单机持久化，无需外部服务
    checkpoint_url: str = Field(default="", alias="AIOS_CHECKPOINT_URL")

    # 服务监听
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def _load() -> Settings:
    return Settings(
        **{
            # ⚠ 这里**不能**写 os.getenv("SERVICE_JWT_SECRET", "")：显式传空串会覆盖字段默认值，
            # 而 verify() 对空密钥是「失败关闭」⇒ 全站 /internal/v1/* 一起 401。
            # 2026-10-18 实测踩到：加了鉴权后 Java → agent 全链路直接 401，配置默认值形同虚设。
            "SERVICE_JWT_SECRET": os.getenv("SERVICE_JWT_SECRET") or DEV_SERVICE_JWT_SECRET,
            "AIOS_SERVER_BASE_URL": os.getenv("AIOS_SERVER_BASE_URL", "http://aios-server:8080"),
            "MODEL_DEFAULT": os.getenv("MODEL_DEFAULT", "echo"),
            "AGENT_STREAM": os.getenv("AGENT_STREAM", "true"),
            "AGENT_PARALLEL_TOOLS": os.getenv("AGENT_PARALLEL_TOOLS", "true"),
            "AGENT_MAX_CONCURRENCY": os.getenv("AGENT_MAX_CONCURRENCY", "4"),
            "PG_DSN": os.getenv("PG_DSN", ""),
            "AIOS_HITL": os.getenv("AIOS_HITL", "false"),
            "AIOS_CHECKPOINT_URL": os.getenv("AIOS_CHECKPOINT_URL", ""),
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
