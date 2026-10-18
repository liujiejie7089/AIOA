# -*- coding: utf-8 -*-
"""HITL 澄清链端到端哨兵：`ask_user` → `need_clarification` → `resume`。

判据（对应 docs/50 §7 试点验收，**抓 SSE 帧**，不是看 UI）：
  [H1] POST /internal/v1/runs 时模型调 ask_user ⇒ SSE 出现 need_clarification，
       载荷含 question + suggested_options（契约 internal-agent.yaml:133）；
  [H2] 该轮**不发** run.completed（是暂停，不是结束）；
  [H3] POST /internal/v1/runs/{id}/resume 回填答案 ⇒ 续跑到 message.completed + run.completed；
  [H4] **Q3 精确恢复**：resume 后已完成的业务工具**不重跑**（调用计数 = 1）；
  [H5] 关闭 HITL（AIOA_HITL=false）时同样输入不产生 need_clarification（开关有效，默认零回归）。

实现方式：用 FastAPI TestClient 在**进程内**起真实路由，只把「模型解析 + 上游 HTTP +
业务工具」打桩 —— 路由、SSE 帧化、图、checkpointer 全是真跑。

用法：`./agent/.venv/Scripts/python.exe scripts/_verify_ask_user_hitl.py`
退出码 0 = 全过。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

# ⚠️ 必须在 import app.main 之前设置：settings 是导入期单例，读的就是此刻的环境变量。
os.environ["AIOA_HITL"] = "true"
os.environ["AIOA_CHECKPOINT_URL"] = ""      # 内存（本地）
os.environ["AIOA_TEST_FAKE_KEY"] = "k"

from fastapi.testclient import TestClient  # noqa: E402

from aioa_ai.llm import Provider  # noqa: E402
from aioa_ai.tools.client import ToolClient, ToolOutcome  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent))
from _svc_token import svc_headers  # noqa: E402 服务间令牌（/internal/v1/* 已强制校验）

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOA_TEST_FAKE_KEY")

RUN_ID = "run_hitl_sentinel_0001"
RESULTS: list[tuple[str, bool, str]] = []


def chk(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def parse_sse(text: str) -> list[tuple[int, str, dict]]:
    """把 SSE 报文解析成 [(seq, event, data)]。"""
    out: list[tuple[int, str, dict]] = []
    seq, event, data = None, None, None
    for line in text.splitlines():
        if line.startswith("id:"):
            seq = int(line[3:].strip())
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            raw = line[5:].strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"_raw": raw}
        elif line == "" and event is not None:
            out.append((seq if seq is not None else 0, event, data or {}))
            seq, event, data = None, None, None
    if event is not None:
        out.append((seq if seq is not None else 0, event, data or {}))
    return out


def _make_stream():
    """第 1 轮调业务工具；第 2 轮调 ask_user；第 3 轮（resume 后）作答。"""
    state = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        state["n"] += 1
        if state["n"] == 1:
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "get_my_quota", "arguments": "{}"}}]},
                {"prompt_tokens": 5, "completion_tokens": 1})
        elif state["n"] == 2:
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "a1", "type": "function",
                 "function": {"name": "ask_user", "arguments": json.dumps({
                     "question": "你要处理哪一类事务？",
                     "options": [{"value": "contract", "label": "合同"},
                                 {"value": "expense", "label": "报销"}]},
                     ensure_ascii=False)}}]},
                {"prompt_tokens": 5, "completion_tokens": 2})
        else:
            for piece in ("已", "按", "合同", "处理"):
                yield ("delta", piece)
            yield ("done", {"role": "assistant", "content": "已按合同处理"},
                   {"prompt_tokens": 6, "completion_tokens": 3})

    return fake_stream, state


def main() -> int:
    from app.main import app

    # 断言路由已注册（防「写了函数没挂路由」）
    paths = {getattr(r, "path", None) for r in app.routes}
    chk("H0 路由 /internal/v1/runs/{run_id}/resume 已注册",
        "/internal/v1/runs/{run_id}/resume" in paths, f"routes={sorted(p for p in paths if p)}")

    fake_stream, stream_state = _make_stream()
    tool_hits = {"n": 0}

    async def counting_invoke(self, name, arguments=None):
        if name == "get_my_quota":
            tool_hits["n"] += 1
        return ToolOutcome(name=name, arguments=arguments or {}, ok=True, data={"left": 10})

    body = {"run_id": RUN_ID, "conversation_id": 1, "text": "帮我处理一下",
            "model_ref": "fake", "user_token": "tok",
            "user_context": {"user_id": 1, "tenant_id": 1}}

    patches = [
        patch("aioa_ai.entry.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes._post_stream", fake_stream),
        patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
            {"type": "function", "function": {"name": "get_my_quota",
                                             "description": "q", "parameters": {}}}])),
        patch.object(ToolClient, "invoke", counting_invoke),
    ]
    for p in patches:
        p.start()
    try:
        # 内部端点强制服务间令牌（2026-10-18 起）：统一挂到 client 上，正文不动。
        with TestClient(app, headers=svc_headers()) as client:
            r1 = client.post("/internal/v1/runs", json=body)
            f1 = parse_sse(r1.text)
            types1 = [t for _, t, _ in f1]
            chk("H1 首轮产出 need_clarification", "need_clarification" in types1, f"types={types1}")
            nc = next((d for _, t, d in f1 if t == "need_clarification"), {})
            chk("H1 载荷含 question + suggested_options",
                bool(nc.get("question")) and len(nc.get("suggested_options") or []) == 2,
                f"payload={json.dumps(nc, ensure_ascii=False)}")
            chk("H1 选项保序且带 value/label",
                [o.get("value") for o in nc.get("suggested_options", [])] == ["contract", "expense"],
                str(nc.get("suggested_options")))
            chk("H2 暂停轮不发 run.completed", "run.completed" not in types1, f"types={types1}")

            r2 = client.post(f"/internal/v1/runs/{RUN_ID}/resume", json={"answer": "contract"})
            f2 = parse_sse(r2.text)
            types2 = [t for _, t, _ in f2]
            chk("H3 resume 续跑完成",
                types2[-1:] == ["run.completed"] and "need_clarification" not in types2,
                f"types={types2}")
            completed = next((d for _, t, d in f2 if t == "message.completed"), {})
            chk("H3 续跑产出正文", completed.get("content") == "已按合同处理",
                f"content={completed.get('content')!r}")
            chk("H4/Q3 已完成的工具不重跑（调用计数=1）", tool_hits["n"] == 1,
                f"get_my_quota 调用 {tool_hits['n']} 次")
            chk("H4 seq 在每段内自 1 单调递增",
                [s for s, _, _ in f1] == list(range(1, len(f1) + 1))
                and [s for s, _, _ in f2] == list(range(1, len(f2) + 1)),
                f"f1={[s for s,_,_ in f1]} f2={[s for s,_,_ in f2]}")
    finally:
        for p in patches:
            p.stop()

    # —— H5：关闭 HITL，同一输入**不得**产生 need_clarification，且正常跑完（开关真有效）——
    import asyncio

    from aioa_ai.config import settings
    from aioa_ai.graph import builder, checkpoint

    async def _off():
        settings.agent_hitl = False
        await checkpoint.aclose()      # 释放上一段的挂起态存储
        builder.reset()                # 让图按「无 checkpointer」重编译

    asyncio.new_event_loop().run_until_complete(_off())

    fake2, _ = _make_stream()
    off_hits = {"n": 0}

    async def off_invoke(self, name, arguments=None):
        if name == "get_my_quota":
            off_hits["n"] += 1
        return ToolOutcome(name=name, arguments=arguments or {}, ok=True, data={"left": 10})

    patches2 = [
        patch("aioa_ai.entry.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes._post_stream", fake2),
        patch.object(ToolClient, "list_tools", AsyncMock(return_value=[])),
        patch.object(ToolClient, "invoke", off_invoke),
    ]
    for p in patches2:
        p.start()
    try:
        body2 = dict(body, run_id="run_hitl_off_0001")
        # 内部端点强制服务间令牌（2026-10-18 起）：统一挂到 client 上，正文不动。
        with TestClient(app, headers=svc_headers()) as client:
            r = client.post("/internal/v1/runs", json=body2)
        types = [t for _, t, _ in parse_sse(r.text)]
        chk("H5 关闭 HITL 时不产生 need_clarification", "need_clarification" not in types,
            f"types={types}")
        chk("H5 关闭 HITL 时正常跑完（run.completed）", "run.completed" in types, f"types={types}")
    finally:
        for p in patches2:
            p.stop()

    ok = all(x[1] for x in RESULTS)
    print("=== HITL 澄清链端到端哨兵 ===")
    for name, passed, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    print(f"\n结果：失败 {sum(1 for x in RESULTS if not x[1])} 项")
    print(f"[STATUS] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
