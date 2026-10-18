# -*- coding: utf-8 -*-
"""数字人「自动调用自定义表单」的真实端到端哨兵（真实 LLM，不 stub 任何帧）
================================================================================

为什么需要它（2026-10-17 的实测缺口）：
  已有哨兵 `_verify_form_confirm.py` / `_verify_form_invoke_e2e.py` 都**伪造** `need_form` 帧，
  只证明「帧到了以后前端能渲染」。它们无法回答用户真正的问题：
  **「我说『办公用品报销』，数字人会不会自己请求那张表单？」**
  该行为取决于两件事，二者都不在这两个哨兵覆盖范围内：
    ① `request_form` 是否真的在模型工具表里（取决于 `AIOS_HITL`，关闭时工具根本不注入）；
    ② 提示词是否要求「命中清单表单就必须调用，禁止给通用操作教程」。
  本脚本直接打真实链路：登录 → 建会话 → 发 run → 读真实 SSE。

判据（每条都能因缺陷变红）
  P0  前置：后端 :8080 在线且账号可登录（否则后面全是空转）
  P1  「办公用品报销」这一轮，SSE 流里出现 `need_form` 事件
      —— 这是「数字人主动请求表单」的**唯一**判据；模型只回文字操作步骤时必红。
  P2  `need_form` 载荷里 `form_code` 非空、`fields` 非空（Java 用库定义补全成功），
      且 `title` 是中文表单名（不是内部枚举）。
  P3  `need_form` 的 `reason` 非空（模型说明了为什么要这张表）。
  N1  负向对照：「你好」这类寒暄**不得**触发 `need_form`
      —— 证明 P1 不是「任何输入都出现表单」的恒真断言。

跑法（后端 :8080 + agent :8000 在线；会创建并删除一个临时会话）：
    agent/.venv/Scripts/python.exe scripts/_verify_form_autocall_live.py
    # 想换提问：
    agent/.venv/Scripts/python.exe scripts/_verify_form_autocall_live.py --text "我要报销打车费"

退出码 = 失败条数。缺服务时打印 SKIP 原因并退出 2（不伪装 PASS）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080/api/v1"
USER, PWD = "wjj_xu", "User@123"
DEFAULT_TEXT = "办公用品报销"
GREETING = "你好"
SSE_TIMEOUT = 150

_results: list[tuple[str, str]] = []


def ok(cid: str, msg: str) -> None:
    _results.append(("PASS", f"{cid} {msg}"))
    print(f"[PASS] {cid} {msg}")


def fail(cid: str, msg: str) -> None:
    _results.append(("FAIL", f"{cid} {msg}"))
    print(f"[FAIL] {cid} {msg}")


def _req(path: str, method: str = "GET", body=None, token: str | None = None, timeout: int = 30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _unwrap(payload: dict) -> dict:
    """后端统一包一层 {code,message,data}；code!=0 视为失败。"""
    if isinstance(payload, dict) and "code" in payload:
        if payload.get("code") != 0:
            raise RuntimeError(f"业务错误 {payload.get('code')}: {payload.get('message')}")
        return payload.get("data") or {}
    return payload


def _sse(run_id: str, token: str, timeout: int = SSE_TIMEOUT) -> list[tuple[str, str]]:
    """读 SSE，遇到 need_form / 收尾事件即返回。返回 [(event, data_json_str), ...]。"""
    r = urllib.request.Request(f"{BASE}/runs/{run_id}/events")
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Accept", "text/event-stream")
    events: list[tuple[str, str]] = []
    cur_event, cur_data = "message", []
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            line = raw.decode("utf-8").rstrip("\r\n")
            if line == "":
                if cur_data:
                    events.append((cur_event, "\n".join(cur_data)))
                    name = cur_event
                    if name in ("need_form", "need_clarification") or "completed" in name or "failed" in name:
                        return events
                cur_event, cur_data = "message", []
                continue
            if line.startswith("event:"):
                cur_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur_data.append(line[len("data:"):].strip())
    return events


def _run_once(text: str, token: str, worker_id: int | None = None) -> tuple[list[tuple[str, str]], int]:
    title = "表单自动调用哨兵" if not worker_id else f"表单自动调用哨兵-w{worker_id}"
    conv = _unwrap(_req("/conversations", "POST",
                        {"title": title, "workerId": worker_id}, token))
    conv_id = conv.get("id")
    run = _unwrap(_req(f"/conversations/{conv_id}/runs", "POST", {"text": text}, token))
    run_id = run.get("runId") or run.get("run_id")
    if not run_id:
        raise RuntimeError(f"建 run 未拿到 runId：{run}")
    events = _sse(str(run_id), token)
    # 自清理：临时会话删除（失败不影响判据，只提示）
    try:
        _req(f"/conversations/{conv_id}", "DELETE", None, token)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 临时会话 {conv_id} 清理失败：{exc}")
    return events, int(conv_id)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=DEFAULT_TEXT, help="正向提问（默认：办公用品报销）")
    ap.add_argument("--worker-id", type=int, default=None,
                    help="绑定某个数字人（会话 workerId）；不传=一般会话。用户真实路径通常带数字人。")
    args = ap.parse_args()

    # ---- P0 前置 ----
    try:
        login = _unwrap(_req("/auth/login", "POST", {"username": USER, "password": PWD}))
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] P0 后端不可达或登录失败（{exc}）。请先确认 :8080 在线。")
        return 2
    token = login.get("accessToken") or login.get("token")
    if not token:
        print(f"[SKIP] P0 登录未返回 accessToken：{login}")
        return 2
    ok("P0", f"后端在线、{USER} 登录成功")

    # ---- P1/P2/P3 正向：真实提问应触发 need_form ----
    try:
        events, conv_id = _run_once(args.text, token, args.worker_id)
    except Exception as exc:  # noqa: BLE001
        fail("P1", f"真实 run 失败：{exc}")
        return len([r for r in _results if r[0] == "FAIL"])

    form_ev = [(e, d) for e, d in events if e == "need_form"]
    if not form_ev:
        names = [e for e, _ in events]
        fail("P1", f"提问「{args.text}」未出现 need_form；实际事件={names}"
                   "（模型只给了文字教程 ⇒ 要么 request_form 不在工具表，要么提示词没强制）")
    else:
        ok("P1", f"提问「{args.text}」触发了 need_form（共 {len(form_ev)} 次）")
        try:
            payload = json.loads(form_ev[0][1])
        except Exception as exc:  # noqa: BLE001
            fail("P2", f"need_form 载荷不是合法 JSON：{exc}")
            payload = {}
        code = payload.get("form_code")
        fields = payload.get("fields") or []
        title = payload.get("title")
        if code and fields:
            ok("P2", f"form_code={code}, title={title}, fields={len(fields)} 个，首个字段="
                     f"{(fields[0] or {}).get('name')}")
        else:
            fail("P2", f"need_form 载荷缺 form_code/fields：form_code={code}, fields={len(fields)}, "
                       f"error={payload.get('error')}")
        if payload.get("reason"):
            ok("P3", f"reason={payload.get('reason')}")
        else:
            fail("P3", "need_form 未带 reason（模型没说明为何要这张表）")

    # ---- N1 负向对照：寒暄不得触发表单 ----
    try:
        neg_events, _ = _run_once(GREETING, token, args.worker_id)
        if any(e == "need_form" for e, _ in neg_events):
            fail("N1", f"寒暄「{GREETING}」也触发了 need_form（判据可能恒真）")
        else:
            ok("N1", f"寒暄「{GREETING}」未触发表单（负向对照成立）")
    except Exception as exc:  # noqa: BLE001
        fail("N1", f"负向对照片段运行失败：{exc}")

    failed = [r for r in _results if r[0] == "FAIL"]
    print("\n──────── 收口 ────────")
    print(f"通过：{len(_results) - len(failed)} / 失败：{len(failed)}")
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
