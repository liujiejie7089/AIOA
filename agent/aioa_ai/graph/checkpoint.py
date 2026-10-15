"""挂起态（checkpoint）存储：HITL 的「暂停住、之后接着跑」靠它。

为什么需要它
------------
没有 checkpointer，LangGraph 的 ``interrupt()`` 无处保存状态 —— 进程内暂停还行，
一旦进程重启，挂起的 run 就找不回来了（而这正是 `docs/50 §7` 的 **Q2 真挂起**判据）。
挂上之后，``build(checkpointer=...)`` 让图在 ``clarify`` 节点把整份状态落盘，
``resume`` 时按 ``thread_id``（= run_id）取回，从断点继续。

三档实现（按连接串自动选择，**默认最省事的那档**）
--------------------------------------------------
    （空）/ memory            → InMemorySaver   **本地默认**：零外部依赖、进程内可续跑；
                                                 代价是进程重启即丢（不满足 Q2，属本地取舍）
    redis://host:6379/0       → AsyncRedisSaver **生产**：跨进程/跨重启，满足 Q2；
                                                 但需 **Redis Stack**（RediSearch + RedisJSON）
    sqlite:///<path>          → AsyncSqliteSaver 可选：单机持久化，无需任何外部服务

关于 Redis 的硬约束（已实测，勿回退）
------------------------------------
``langgraph-checkpoint-redis`` 依赖 Redis 的 RediSearch/RedisJSON 模块。本机那台
Redis 是 3.0.504（连 ``MODULE`` 命令都没有）⇒ 直接 ``FT.INFO unknown command`` 失败。
所以：**本地一律不要指向普通 Redis**（默认走 memory）；生产的 Redis 必须是 Redis Stack。

生命周期：由 ``app/main.py`` 的 lifespan 在启动时 ``setup()``、关闭时 ``aclose()``。
本模块**不在 import 期连库**（测试/回声路径不该被外部依赖拖住）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from aioa_ai.config import settings

logger = logging.getLogger("aioa.ai.graph.checkpoint")

# 进程内单例。用模块级全局而非 lru_cache：setup 是 async 的，需要在事件循环里完成。
_saver = None
_conn = None          # sqlite 的 aiosqlite 连接（关闭时要显式关）
_kind: str | None = None


def default_sqlite_path() -> str:
    """SQLite 落盘位置：``<agent>/.checkpoints/hitl.sqlite``（不入库）。"""
    agent_dir = Path(__file__).resolve().parents[2]
    d = agent_dir / ".checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "hitl.sqlite")


def _resolve_url() -> str:
    """连接串：未配置 ⇒ ``memory``（本地默认）。"""
    return (settings.checkpoint_url or "").strip() or "memory"


async def setup() -> None:
    """按连接串建好 checkpointer 单例（幂等）。仅在 ``AIOA_HITL=true`` 时需要调用。"""
    global _saver, _conn, _kind
    if _saver is not None:
        return
    url = _resolve_url()
    if url.startswith("redis://") or url.startswith("rediss://"):
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        from redis.asyncio import from_url as redis_from_url

        client = redis_from_url(url)
        _saver = AsyncRedisSaver(redis_client=client)
        await _saver.asetup()          # 建索引；**要求 Redis Stack**，普通 Redis 会抛 FT.INFO 未知命令
        _kind = "redis"
    elif url.startswith("sqlite://"):
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = url[len("sqlite://"):]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(path)
        _saver = AsyncSqliteSaver(_conn)
        await _saver.setup()
        _kind = "sqlite"
    else:  # memory / inmemory / 未知串一律按内存处理（本地最省事，失败面最小）
        from langgraph.checkpoint.memory import InMemorySaver

        _saver = InMemorySaver()
        _kind = "memory"
    logger.info("checkpoint store ready: kind=%s url=%s", _kind, url.split("@")[-1])


def saver():
    """当前 checkpointer（未 setup 时为 None）。"""
    return _saver


def kind() -> str | None:
    """当前存储类型（memory / redis / sqlite / None），供诊断端点与日志使用。"""
    return _kind


async def aclose() -> None:
    """关闭连接（服务退出时调用）。"""
    global _saver, _conn, _kind
    try:
        if _conn is not None:
            await _conn.close()
    except Exception as exc:  # 关闭失败不影响退出
        logger.warning("checkpoint close failed: %s", exc)
    finally:
        _saver, _conn, _kind = None, None, None
