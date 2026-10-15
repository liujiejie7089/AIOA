"""护栏（M1 简单实现）：文本长度与整体耗时上限。"""
from __future__ import annotations

import asyncio
import time

# 单次输入文本最大长度（超出直接拒绝）
MAX_TEXT_LEN = 4000
# 单次 run 墙钟时间上限（秒）
MAX_WALL_TIME = 120

# 回声模式下每帧间隔（秒）
ECHO_DELTA_INTERVAL = 0.03


class GuardError(Exception):
    """护栏触发。"""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def check_text_len(text: str) -> None:
    """输入文本长度护栏。"""
    if len(text) > MAX_TEXT_LEN:
        raise GuardError(
            code="TEXT_TOO_LONG",
            message=f"text length {len(text)} exceeds MAX_TEXT_LEN={MAX_TEXT_LEN}",
        )


class WallClock:
    """墙钟护栏：进入时记录起点，每步检查是否超时。"""

    def __init__(self, limit: float = MAX_WALL_TIME):
        self.limit = limit
        self.started = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def check(self) -> None:
        if self.elapsed() > self.limit:
            raise GuardError(
                code="WALL_TIME_EXCEEDED",
                message=f"run exceeded MAX_WALL_TIME={self.limit}s",
            )

    async def sleep(self, seconds: float) -> None:
        """受护栏约束的 sleep：sleep 前先检查剩余时间是否够。"""
        self.check()
        if self.elapsed() + seconds > self.limit:
            raise GuardError(
                code="WALL_TIME_EXCEEDED",
                message=f"run exceeded MAX_WALL_TIME={self.limit}s",
            )
        await asyncio.sleep(seconds)
