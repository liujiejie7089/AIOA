"""知识库：检索工具名常量与「检索结果 → 引用溯源条目」的转换。

原寄居在 `app/core/agent_runtime.py`（`KB_TOOL` 与 `_citations_from_tool`）。
之所以独立成模块：这两个符号被**回声运行时**与**图运行时**共同使用，
放在任一运行时里都会造成运行时之间互相 import。按职责归到 knowledge 层后，
依赖方向变成「运行时 → knowledge」，单向且稳定。
"""
from __future__ import annotations

from aios_ai.knowledge import sources

# 知识库检索工具名：其结果回写 message.completed.citations（FR-D5 引用溯源）
KB_TOOL = "search_kb_documents"


def _citations_from_tool(name: str, outcome) -> list[dict]:
    """工具结果 → 引用溯源条目 [{docId, title, source, label, action}]（同来源去重）。

    ``outcome`` 为工具执行结果对象（需具备 .ok 与 .data 属性），
    与具体工具客户端实现解耦，故本函数不 import 任何工具层模块。

    联网检索同样要溯源（2026-10-30）：用户要的是「网上的依据」，
    只把正文拼进回答、不留链接，等于让他无法核实。``docId`` 用 URL，
    与知识库文档 id 天然不冲突（一个是整数、一个是 http 串）。

    三方数据源与内部模块同样要溯源（2026-11-03，「智能数据聚合」）：
    周报类回答由企微会话 / 邮箱 / 审批 / 知识库拼成，**若只标注知识库**，
    用户根本分不清哪句来自他自己的聊天记录、哪句来自公司制度文档。
    口径分两层：
      * 能挖到条目标题 → **条目级**引用（每封邮件 / 每份文档各一条）
      * 挖不到（返回是单个对象或纯文本）→ **调用级**引用（「企业微信 · 最近会话」）
    """
    if not outcome.ok:
        return []
    if name == "web_search" and isinstance(outcome.data, dict):
        out: list[dict] = []
        seen: set = set()
        for item in (outcome.data.get("results") or []):
            url = (item or {}).get("url")
            if url and url not in seen:
                seen.add(url)
                out.append({"docId": url, "title": str(item.get("title") or url),
                            "source": "web", "label": sources.source_label("web"),
                            "action": "联网检索"})
        return out
    if name == KB_TOOL and isinstance(outcome.data, list):
        out: list[dict] = []
        seen: set = set()
        for doc in outcome.data:
            if isinstance(doc, dict) and doc.get("id") is not None and doc["id"] not in seen:
                seen.add(doc["id"])
                out.append({"docId": doc["id"], "title": str(doc.get("docName") or ""),
                            "source": "knowledge_base",
                            "label": sources.source_label("knowledge_base"),
                            "action": "知识库检索"})
        return out
    return _citations_from_other_tools(name, outcome)


def _citations_from_other_tools(name: str, outcome) -> list[dict]:
    """其余工具（MCP 连接器 / 内部业务工具）的引用抽取。

    只对**已登记来源**的工具产出引用：``ask_user`` / ``request_form`` 这类交互工具
    不是数据源，给它们挂「来源」会让引用区变成操作日志。
    """
    src = sources.tool_source(name)
    if not src:
        return []
    items = sources.item_citations(name, outcome.data)
    if items:
        return items
    # 条目级挖不到：只要**确实有数据**就记一条调用级引用。
    # 空结果不记 —— 「查了但没查到」不是来源，标出来反而误导用户以为有依据。
    payload = sources.normalize_payload(outcome.data)
    if payload in (None, "", [], {}):
        return []
    count = len(payload) if isinstance(payload, list) else None
    return [sources.call_citation(name, count)]
