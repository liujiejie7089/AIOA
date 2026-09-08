"""M1 回声运行时：把输入文本逐字符回显；M2 起支持工具调用演示。

无用户 token / 未命中工具关键词 → 纯回声（与 M1 行为一致）；
命中关键词且工具网关可用 → 完整演示工具调用事件流：
    run.started → tool.call → tool.result → message.delta×N
    → message.completed{content,citations,tool_calls,usage} → run.completed

用途：不依赖真实模型 key 即可端到端验证「工具注册 → 权限 → 执行 → 结果回注 → 计量」
全链路（技术方案 M1 门禁：智能体可完成一次带工具调用与计量的完整任务）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.guards import ECHO_DELTA_INTERVAL, WallClock, check_text_len
from app.schemas import RunRequest, SseEvent
from app.tools_client import ToolClient, ToolOutcome

# 关键词 → 工具路由（按序匹配，先特指后泛化）
_TOOL_ROUTES: list[tuple[tuple[str, ...], str]] = [
    (("待我审批", "待办审批", "待审"), "list_todo_approvals"),
    (("我的审批", "审批进度", "审批"), "list_my_approvals"),
    (("额度", "词元", "余额"), "get_my_quota"),
    (("知识库", "找资料", "检索", "查资料"), "search_kb_documents"),
]


def pick_tool(text: str) -> tuple[str, dict] | None:
    """按关键词路由工具；返回 (name, arguments) 或 None。"""
    for keywords, name in _TOOL_ROUTES:
        for kw in keywords:
            idx = text.find(kw)
            if idx >= 0:
                if name == "search_kb_documents":
                    rest = (text[idx + len(kw):] or "").strip(" ？?。，,")
                    return name, {"keyword": rest or text}
                return name, {}
    return None


def summarize(outcome: ToolOutcome) -> str:
    """把工具结果转成面向用户的汇总文本（echo 模式的「反思」阶段）。"""
    if not outcome.ok:
        return f"工具调用失败：{outcome.error or '未知错误'}"
    data = outcome.data
    name = outcome.name
    if name in ("list_my_approvals", "list_todo_approvals"):
        rows = data if isinstance(data, list) else []
        if not rows:
            label = "待你审批" if name == "list_todo_approvals" else "你提交的审批"
            return f"当前{label}单：暂无。"
        label = "待你审批" if name == "list_todo_approvals" else "你提交的审批"
        lines = [f"当前{label}单共 {len(rows)} 条："]
        for r in rows:
            note = r.get("decisionNote")
            extra = f"，意见：{note}" if note else ""
            lines.append(f"· #{r.get('id')} {r.get('title')}（{r.get('status')}{extra}）")
        return "\n".join(lines)
    if name == "search_kb_documents":
        rows = data if isinstance(data, list) else []
        if not rows:
            return "知识库中没有找到相关资料。"
        lines = [f"在知识库中找到 {len(rows)} 份相关资料："]
        for r in rows:
            lines.append(f"· 《{r.get('docName')}》（{r.get('state')}）")
        return "\n".join(lines)
    if name == "get_my_quota":
        if isinstance(data, dict):
            return (f"当前词元额度：总量 {data.get('quota')}，已用 {data.get('used')}，"
                    f"剩余 {data.get('left')}。")
    return f"工具返回：{data}"


async def run(req: RunRequest, seq_start: int = 1) -> AsyncIterator[SseEvent]:
    """产出回声事件流（含可选的工具调用演示），seq 从 seq_start 单调递增。"""
    seq = seq_start
    check_text_len(req.text)
    clock = WallClock()

    yield SseEvent(seq=seq, type="run.started", data={"run_id": req.run_id, "conversation_id": req.conversation_id, "model": "echo", "gateway_key": "echo"})
    seq += 1

    client = ToolClient.from_request(req.user_token)
    tool_calls: list[dict] = []

    if client.enabled:
        tools = await client.list_tools()
        hit = pick_tool(req.text)
        if hit is not None and any(t.get("function", {}).get("name") == hit[0] for t in tools):
            name, args = hit
            yield SseEvent(seq=seq, type="tool.call", data={"name": name, "arguments": args})
            seq += 1
            outcome = await client.invoke(name, args)
            tool_calls.append({"name": name, "arguments": args, "ok": outcome.ok})
            yield SseEvent(seq=seq, type="tool.result",
                           data={"name": name, "ok": outcome.ok, "summary": outcome.summary()})
            seq += 1
            content = summarize(outcome)
        else:
            content = echo_text(req)
    else:
        content = echo_text(req)

    for ch in content:
        yield SseEvent(seq=seq, type="message.delta", data={"text": ch})
        seq += 1
        await clock.sleep(ECHO_DELTA_INTERVAL)

    usage = {"prompt_tokens": 0, "completion_tokens": len(content)}
    yield SseEvent(
        seq=seq,
        type="message.completed",
        data={"content": content, "citations": [], "tool_calls": tool_calls, "usage": usage},
    )
    seq += 1

    yield SseEvent(seq=seq, type="run.completed", data={"status": "SUCCEEDED", "usage": usage})


def echo_text(req: RunRequest) -> str:
    """回显文本 = f"[{appCode}/{page}] " + text（context 为空则仅 text）。"""
    ctx = req.context
    if ctx is not None and ctx.appCode and ctx.page:
        return f"[{ctx.appCode}/{ctx.page}] {req.text}"
    return req.text
