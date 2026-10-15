"""兼容垫片（deprecation shim）：实现已搬迁到 ``aioa_ai.runtimes.multi_task``。

``_replay`` 等模块级缓存是**同一个对象**（不是副本），因此这里的 clear()/写入
与运行中的实现共享同一份缓存。
"""
from __future__ import annotations

from aioa_ai.runtimes.multi_task import *  # noqa: F401,F403
from aioa_ai.runtimes.multi_task import (  # noqa: F401
    MAX_SUBTASKS,
    REPLAY_MAX_ENTRIES,
    PlanRejected,
    SubTask,
    build_plan,
    run,
)
from aioa_ai.runtimes.multi_task import _replay, _replay_get, _replay_put  # noqa: F401
