"""知识库：检索工具名常量与「检索结果 → 引用溯源条目」的转换。

原寄居在 `app/core/agent_runtime.py`（`KB_TOOL` 与 `_citations_from_tool`）。
之所以独立成模块：这两个符号被**回声运行时**与**图运行时**共同使用，
放在任一运行时里都会造成运行时之间互相 import。按职责归到 knowledge 层后，
依赖方向变成「运行时 → knowledge」，单向且稳定。
"""
from __future__ import annotations

# 知识库检索工具名：其结果回写 message.completed.citations（FR-D5 引用溯源）
KB_TOOL = "search_kb_documents"


def _citations_from_tool(name: str, outcome) -> list[dict]:
    """知识库检索结果 → 引用溯源条目 [{docId, title, source}]（同文档去重）。

    ``outcome`` 为工具执行结果对象（需具备 .ok 与 .data 属性），
    与具体工具客户端实现解耦，故本函数不 import 任何工具层模块。
    """
    if name != KB_TOOL or not outcome.ok or not isinstance(outcome.data, list):
        return []
    out: list[dict] = []
    seen: set = set()
    for doc in outcome.data:
        if isinstance(doc, dict) and doc.get("id") is not None and doc["id"] not in seen:
            seen.add(doc["id"])
            out.append({"docId": doc["id"], "title": str(doc.get("docName") or ""),
                        "source": "knowledge_base"})
    return out
