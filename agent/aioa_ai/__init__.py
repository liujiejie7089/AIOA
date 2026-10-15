"""aioa_ai —— AI 能力内核。

本包统一承载 AIOA 平台的全部 AI 能力：图运行时（LangGraph）、模型接入、工具编排、
知识检索、提示词、护栏、意图识别、事件序列化、语音。

  - 对外唯一入口：`aioa_ai.entry.run`（分派 回声 / LangGraph 图，产出一致的 SSE 事件流）；
  - 与 `agent/app/` 的依赖方向固定为 `app -> aioa_ai`（单向）；
  - **只有 `aioa_ai/graph/` 允许 import langgraph**，其余子包保持框架无关。

详见同目录 README.md。
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
