"""跨源数据聚合包：对外只暴露 ``plan`` 里的入口。"""
from aios_ai.aggregate.plan import (  # noqa: F401
    AGGREGATE_RE,
    DEFAULT_PLAN,
    SourceCall,
    SourceResult,
    build_block,
    collect,
    gather,
    is_aggregate_request,
    resolve_plan,
)

__all__ = [
    "AGGREGATE_RE",
    "DEFAULT_PLAN",
    "SourceCall",
    "SourceResult",
    "build_block",
    "collect",
    "gather",
    "is_aggregate_request",
    "resolve_plan",
]
