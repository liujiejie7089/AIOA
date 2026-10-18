# -*- coding: utf-8 -*-
"""专家 AI「真有专业能力」端到端验收 —— 真实后端 + 真实库 + 真实模型
================================================================================

## 验的是什么

用户端选了某位专家（ai_expert.expert_key）后，该专家的**领域系统提示词**
（expert_config GLOBAL 片段里的 `systemPrompt`）必须真的进到模型上下文。
这条链此前断在最后一跳：Java 只在「会话绑数字员工」时才解析专家配置，
而专家会话恰恰不绑数字员工；且 agent 从未消费 `expert_settings.systemPrompt`。

## 判据（行为级，不看日志）

  X1  目录里有 ≥13 位专家，且含本轮新增的 doc_writer / translator / legal
  X2  translator 专家：同一句话问「翻译成英文」⇒ 回答**正文**是英文（中文前言不超一行）
      —— 该专家的提示词明确要求「默认直接给译文，不要先解释再翻译」，通用助手不会这样收敛
  X3  库里 chat_conversation.expert_key 已落库为 translator（不是只在前端参数里）
  X4  同一会话第二轮**不再携带** expert_key ⇒ 仍按 translator 作答（人设靠落库继承，不靠每轮传参）
  X5  负向对照：传一个不存在的 expert_key ⇒ 不得写坏会话（expert_key 保持原值/NULL），
      且对话照常成功（不得 500）
  X6  legal 专家：问「试用期最长多久」⇒ 回答给出「六个月/6 个月」这个法定上限
      （这是该专家提示词要求「引用法律名称与规则」的可观测结果；通用助手常答成 1 年）
  X7  专家会话**不得**弹业务表单（need_form）—— 专家是顾问不是办事员；
      实测缺陷：法律专家曾弹出「合同管理/contract_draft」表且正文为空

## 跑法
    "C:/Users/刘尖尖/.workbuddy/binaries/python/versions/3.13.12/python.exe" scripts/_verify_expert_prompt_e2e.py
    ... --tenant 3 --user wjj_xu --pwd User@123

前置：后端 :8080、agent :8000、MySQL 127.0.0.1:3306(root/空密码/aios)、V88 已迁移。
前置不满足 ⇒ 打印 SKIP 并 exit 2（不伪装 PASS）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080/api/v1"
SSE_TIMEOUT = 180


def log(s: str) -> None:
    print(s, flush=True)


def _req(path: str, method: str, body, token: str | None = None, timeout: int = 60):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {path} {e.read().decode('utf-8', 'ignore')[:200]}") from e


def _unwrap(resp: dict) -> dict:
    if not isinstance(resp, dict) or resp.get("code") not in (0, None):
        raise RuntimeError(f"接口返回失败：{resp}")
    return resp.get("data") or {}


def _ask(conv_id: int, text: str, token: str, expert_key: str | None) -> str:
    """发一轮对话并把回答正文拼起来（message.delta 累积）。"""
    return _ask_events(conv_id, text, token, expert_key)[0]


def _ask_events(conv_id: int, text: str, token: str,
                expert_key: str | None) -> tuple[str, list[str]]:
    """同上，但同时返回收到的事件名序列（用于断言「专家会话不得弹业务表单」）。"""
    body: dict = {"text": text}
    if expert_key is not None:
        body["expert_key"] = expert_key
    run = _unwrap(_req(f"/conversations/{conv_id}/runs", "POST", body, token))
    run_id = run.get("runId") or run.get("run_id")
    req = urllib.request.Request(f"{BASE}/runs/{run_id}/events")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "text/event-stream")
    answer, names, cur_event, cur_data = [], [], "message", []
    with urllib.request.urlopen(req, timeout=SSE_TIMEOUT) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "ignore").rstrip("\r\n")
            if line == "":
                if cur_data:
                    data = "\n".join(cur_data)
                    names.append(cur_event)
                    if cur_event == "message.delta":
                        try:
                            answer.append((json.loads(data) or {}).get("text") or "")
                        except Exception:  # noqa: BLE001
                            answer.append(data)
                    if cur_event in ("need_form", "need_clarification") or "completed" in cur_event \
                            or "failed" in cur_event:
                        break
                cur_event, cur_data = "message", []
                continue
            if line.startswith("event:"):
                cur_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur_data.append(line[len("data:"):].strip())
    return "".join(answer).strip(), names


def conv_expert_key(conv_id: int) -> str | None:
    import pymysql

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("select expert_key from chat_conversation where id=%s", (conv_id,))
            row = cur.fetchone()
            return None if not row else row["expert_key"]
    finally:
        conn.close()


def _latin_ratio(s: str) -> float:
    letters = sum(1 for c in s if ("a" <= c <= "z") or ("A" <= c <= "Z"))
    han = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    total = letters + han
    return 0.0 if total == 0 else letters / total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=int, default=3)
    ap.add_argument("--user", default="wjj_xu")
    ap.add_argument("--pwd", default="User@123")
    args = ap.parse_args()

    try:
        login = _unwrap(_req("/auth/login", "POST", {"username": args.user, "password": args.pwd}))
    except Exception as exc:  # noqa: BLE001
        log(f"[SKIP] 后端 :8080 不可达或登录失败：{exc}")
        return 2
    token = login.get("accessToken") or login.get("token")
    if not token:
        log(f"[SKIP] 登录未返回 accessToken：{login}")
        return 2

    try:
        experts = _unwrap(_req("/experts", "GET", None, token))
    except Exception as exc:  # noqa: BLE001
        log(f"[SKIP] 专家目录取不到：{exc}")
        return 2
    if isinstance(experts, dict):
        experts = experts.get("list") or experts.get("items") or []
    keys = {e.get("key") for e in experts}

    ok = bad = 0

    def chk(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok, bad
        if cond:
            ok += 1
            log(f"[PASS] {label}  {detail}")
        else:
            bad += 1
            log(f"[FAIL] {label}  {detail}")

    log("=" * 92)
    log(f"专家 AI 端到端验收：tenant={args.tenant} 目录 {len(experts)} 位")
    log("=" * 92)

    chk("X1 目录含 13+ 位专家且含新增的 translator/legal/doc_writer",
        len(experts) >= 13 and {"translator", "legal", "doc_writer"} <= keys,
        f"n={len(experts)} keys 命中={sorted(k for k in ('translator', 'legal', 'doc_writer') if k in keys)}")

    if "translator" not in keys or "legal" not in keys:
        log("[SKIP] 关键专家不在目录（V88 未迁移或本租户目录未补行），后续用例不跑")
        log(f"结果：通过 {ok} 项，失败 {bad} 项")
        log("[STATUS] " + ("PASS" if bad == 0 else "FAIL"))
        return 0 if bad == 0 else 1

    conv_id = None
    try:
        conv = _unwrap(_req("/conversations", "POST", {"title": "专家能力验收"}, token))
        conv_id = conv.get("id")

        src = "请于本周五前提交材料。"
        ans = _ask(conv_id, f"把这句话翻译成英文：{src}", token, "translator")
        log(f"       translator 回答前 120 字：{ans[:120]!r}")
        chk("X2 翻译专家直接给英文译文（正文英文占比 > 0.6）", _latin_ratio(ans) > 0.6,
            f"latin_ratio={_latin_ratio(ans):.2f} len={len(ans)}")
        chk("X3 会话 expert_key 已落库为 translator", conv_expert_key(conv_id) == "translator",
            f"db={conv_expert_key(conv_id)}")

        ans2 = _ask(conv_id, "把这句话翻译成英文：会议改到明天上午十点。", token, None)
        log(f"       第二轮（不带 expert_key）回答前 120 字：{ans2[:120]!r}")
        chk("X4 第二轮不再传 expert_key 仍按专家作答（人设靠落库继承）",
            _latin_ratio(ans2) > 0.6 and conv_expert_key(conv_id) == "translator",
            f"latin_ratio={_latin_ratio(ans2):.2f} db={conv_expert_key(conv_id)}")

        # X5 负向：不存在的专家不得写坏会话、不得 500
        try:
            ans3 = _ask(conv_id, "你好", token, "no_such_expert_key")
            ok5 = True
            detail5 = f"answer_len={len(ans3)} db={conv_expert_key(conv_id)}"
        except Exception as exc:  # noqa: BLE001
            ok5 = False
            detail5 = f"异常：{exc}"
        chk("X5 负向：不存在的 expert_key 不得写坏会话、对话仍成功",
            ok5 and conv_expert_key(conv_id) == "translator", detail5)

        # X6 法律专家：试用期法定上限
        conv2 = _unwrap(_req("/conversations", "POST", {"title": "专家能力验收-法律"}, token))
        cid2 = conv2.get("id")
        try:
            ans4, ev4 = _ask_events(cid2, "劳动合同的试用期最长可以约定多久？", token, "legal")
            log(f"       legal 回答前 160 字：{ans4[:160]!r}  帧={ev4}")
            hit = ("六个月" in ans4) or ("6个月" in ans4) or ("6 个月" in ans4) or bool(re.search(r"\b6\b.*月", ans4))
            chk("X6 法律专家给出试用期法定上限（六个月）", hit, f"hit={hit}")
            # X7：专家是「顾问」不是「办事员」——纯咨询问题不得弹任何数字人的业务表单
            #     （实测缺陷：曾弹出 contract_draft「合同管理」表且正文为空）
            chk("X7 专家会话不得弹业务表单（need_form）", "need_form" not in ev4, f"frames={ev4}")
        finally:
            try:
                _req(f"/conversations/{cid2}", "DELETE", None, token)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        bad += 1
        log(f"[FAIL] 链路异常：{exc}")
    finally:
        if conv_id:
            try:
                _req(f"/conversations/{conv_id}", "DELETE", None, token)
            except Exception:  # noqa: BLE001
                pass

    log("-" * 92)
    log(f"结果：通过 {ok} 项，失败 {bad} 项")
    log("[STATUS] " + ("PASS" if bad == 0 else "FAIL"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
