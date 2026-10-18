"""运行时门面（服务接入层 / 兼容入口）。

AI 实现已统一搬迁到 ``aios_ai``；本文件**不再是实现**，只做「服务层 → AI 层」的转接：

  - 保持历史 import 路径 ``from app.core import runtime`` 与 ``runtime.run(req)`` 签名不变，
    使 ``agent/app/main.py`` 等调用点零改动；
  - 内部委托给 ``aios_ai.entry.run``（按 ``provider.driver`` 分派回声 / LangGraph 图运行时）。

分派规则、事件契约、错误语义全部在 ``aios_ai.entry`` 内定义一份，这里不重复判定。
"""
from __future__ import annotations

from aios_ai.entry import FIRST_SEQ, run  # noqa: F401

__all__ = ["FIRST_SEQ", "run"]
