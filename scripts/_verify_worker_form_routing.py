# -*- coding: utf-8 -*-
"""逐个数字人验收「它会不会调自己绑定的那张表单」（真实 LLM，不 stub 任何帧）
================================================================================

## 为什么需要它

`worker_capability` 表里，**每个数字人都绑定了恰好一张表单**
（516 行 = 43 张 OA 模板 × 12 个租户，`task_code` / `form_code` 一一对应）。
但 Java 侧下发 `available_forms` 时用的是
`RunService#buildRequest` → `FormTemplateService.listAvailable(tenantId)`：
**只按租户过滤，完全没有按 `worker_capability` 过滤**。
于是：

  - 数字人 A 的作用域里，模型看到的是**整个租户的 20 张表单**，不是它自己那 1 张；
  - 提示词又写着「按业务归属选最接近的一张」⇒ 模型可以合法地选到**别的数字人的表单**；
  - 更糟的是，选错之后没有任何一层会拦（`FormSubmissionService` 不校验 worker 归属）。

`_verify_form_autocall_live.py` 只测了「办公用品报销 → 会不会出表单」这一条，
它无法回答「**每个数字人是不是都在调自己那张**」。本脚本逐个打真实链路。

## 判据（对每个数字人）

  R1  `need_form` 出现                     —— 否则是「只给文字教程」（原始缺陷症状）
  R2  `form_code` == 该数字人 capability 的 form_code
      —— 这是本脚本存在的理由。R1 绿而 R2 红 = 「调了，但调的是别人的表」
  R3  `fields` 非空（Java 用库定义补全成功）
  R4  收尾事件是 `run.completed`（不是 `run.failed` / 超时）

另外单独统计（不算进 R1–R4 的通过率，但会单独列出）：
  - `need_clarification`：模型先反问，没调表。属「未完成」而非「调错」。
  - 无 capability 绑定的数字人：结构上不可能调表，单独列为 NO_CAP。

## 跑法

    # 全量（默认 tenant=3 的全部存活数字人）
    agent/.venv/Scripts/python.exe scripts/_verify_worker_form_routing.py
    # 只跑指定 id
    ... --workers 1231,1242
    # 只跑有 capability 的（排除 GENERAL/LEAVE_APPROVER 等）
    ... --only-cap
    # 并发（默认 4；调大更快但更容易撞上游限流）
    ... --concurrency 6

退出码 = 失败条数（R1/R2/R3/R4 命中数）。前置不满足时退出 2 并打印 SKIP 原因。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://127.0.0.1:8080/api/v1"
USER, PWD = "wjj_xu", "User@123"
SSE_TIMEOUT = 180

# 提问模板：从 capability 的 task_name 生成一句自然话术。
# 「帮我办理{task_name}」比「{task_name}」更像真实用户输入，且不会引入额外的业务词。
UTTERANCE_TPL = "帮我办理{task}"

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# ------------------------------------------------------------------ HTTP
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
    if isinstance(payload, dict) and "code" in payload:
        if payload.get("code") != 0:
            raise RuntimeError(f"业务错误 {payload.get('code')}: {payload.get('message')}")
        return payload.get("data") or {}
    return payload


def _sse(run_id: str, token: str, timeout: int = SSE_TIMEOUT) -> list[tuple[str, str]]:
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
                    if cur_event in ("need_form", "need_clarification") \
                            or "completed" in cur_event or "failed" in cur_event:
                        return events
                cur_event, cur_data = "message", []
                continue
            if line.startswith("event:"):
                cur_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur_data.append(line[len("data:"):].strip())
    return events


# ------------------------------------------------------------------ DB
def load_workers(tenant: int, only_ids: list[int] | None) -> list[dict]:
    """读存活数字人 + 其 capability（一个数字人可能 0 或 N 条，这里按 N 展开成多任务）。"""
    import pymysql

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aioa", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            sql = ("select id, name, worker_type, enabled "
                   "from agent_worker where tenant_id=%s and deleted_at is null and enabled=1 ")
            params: list = [tenant]
            if only_ids:
                sql += "and id in (" + ",".join(["%s"] * len(only_ids)) + ") "
                params += only_ids
            sql += "order by id"
            cur.execute(sql, params)
            workers = list(cur.fetchall())

            ids = [w["id"] for w in workers]
            caps: dict[int, list[dict]] = {}
            if ids:
                cur.execute(
                    "select worker_id, task_code, task_name, form_code, enabled "
                    "from worker_capability where worker_id in (" +
                    ",".join(["%s"] * len(ids)) + ") and deleted_at is null order by sort, id",
                    ids)
                for c in cur.fetchall():
                    caps.setdefault(c["worker_id"], []).append(c)
            for w in workers:
                w["caps"] = [c for c in caps.get(w["id"], []) if c.get("enabled")]
    finally:
        conn.close()
    return workers


# ------------------------------------------------------------------ 单个数字人
def probe_worker(w: dict, cap: dict | None, token: str) -> dict:
    """跑一轮真实对话，返回判定结果。"""
    wid = w["id"]
    out = {"worker_id": wid, "worker": w["name"], "type": w["worker_type"],
           "cap": None if cap is None else cap["form_code"],
           "verdict": "", "detail": "", "asked": ""}
    if cap is None:
        out["verdict"] = "NO_CAP"
        out["detail"] = "该数字人无 enabled 的 worker_capability ⇒ 结构上不可能调表"
        return out

    text = UTTERANCE_TPL.format(task=cap["task_name"])
    out["asked"] = text
    conv_id = None
    try:
        conv = _unwrap(_req("/conversations", "POST",
                            {"title": f"路由普查-{wid}", "workerId": wid}, token))
        conv_id = conv.get("id")
        run = _unwrap(_req(f"/conversations/{conv_id}/runs", "POST", {"text": text}, token))
        run_id = run.get("runId") or run.get("run_id")
        events = _sse(str(run_id), token)
    except Exception as exc:  # noqa: BLE001
        out["verdict"] = "R4_FAIL"
        out["detail"] = f"链路异常：{exc}"
        _cleanup(conv_id, token)
        return out

    _cleanup(conv_id, token)

    names = [e for e, _ in events]
    form_ev = [(e, d) for e, d in events if e == "need_form"]
    # 模型这一轮说了什么（R1 失败时用来判断「只给文字教程」还是「拒答」）
    said = "".join(_safe_json_text(d).get("delta", "") or _safe_json_text(d).get("text", "")
                   for e, d in events if e == "message.delta")[:120]
    if not form_ev:
        if "need_clarification" in names:
            pay = _safe_json(next((d for e, d in events if e == "need_clarification"), ""))
            out["verdict"] = "CLARIFY"
            out["detail"] = f"先反问未调表：{str(pay.get('question'))[:60]}"
            return out
        out["verdict"] = "R1_FAIL"
        out["detail"] = f"未出现 need_form（只给文字）；模型说：{said or '（空）'}"
        return out

    pay = _safe_json(form_ev[0][1])
    got = pay.get("form_code")
    fields = pay.get("fields") or []
    if got != cap["form_code"]:
        out["verdict"] = "R2_FAIL"
        out["detail"] = f"调错表：期望 {cap['form_code']}（{cap['task_name']}），实际 {got}（{pay.get('title')}）"
        return out
    if not fields:
        out["verdict"] = "R3_FAIL"
        out["detail"] = f"form_code 正确但 fields 为空：{pay.get('error')}"
        return out
    # R4：出现 need_form 后流会**正常结束**（run 进入 WAITING_INPUT，本就不发 run.completed），
    # 所以这里不能要求 completed，只能要求「没有失败事件」。
    if "run.failed" in names or "error" in names:
        out["verdict"] = "R4_FAIL"
        out["detail"] = f"本轮出现失败事件：{names[-4:]}"
        return out
    out["verdict"] = "PASS"
    out["detail"] = f"{got} / {len(fields)} 字段 / {pay.get('title')}"
    return out


def _safe_json_text(s: str) -> dict:
    try:
        return json.loads(s) if s else {}
    except Exception:  # noqa: BLE001
        return {}


def _safe_json(s: str) -> dict:
    try:
        return json.loads(s) if s else {}
    except Exception:  # noqa: BLE001
        return {}


def _cleanup(conv_id, token: str) -> None:
    if not conv_id:
        return
    try:
        _req(f"/conversations/{conv_id}", "DELETE", None, token)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=int, default=3)
    ap.add_argument("--workers", default="", help="逗号分隔的 worker id；空=该租户全部")
    ap.add_argument("--only-cap", action="store_true", help="只跑有 capability 的数字人")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--json-out", default="", help="把明细写成 JSON 文件")
    args = ap.parse_args()

    only_ids = [int(x) for x in args.workers.split(",") if x.strip()] or None

    try:
        login = _unwrap(_req("/auth/login", "POST", {"username": USER, "password": PWD}))
    except Exception as exc:  # noqa: BLE001
        log(f"[SKIP] 后端 :8080 不可达或登录失败：{exc}")
        return 2
    token = login.get("accessToken") or login.get("token")
    if not token:
        log(f"[SKIP] 登录未返回 accessToken：{login}")
        return 2

    try:
        workers = load_workers(args.tenant, only_ids)
    except Exception as exc:  # noqa: BLE001
        log(f"[SKIP] 读库失败（需要本地 MySQL 3306 / root 空密码 / 库 aioa）：{exc}")
        return 2
    if args.only_cap:
        workers = [w for w in workers if w["caps"]]

    # 展开成任务：一个数字人若有 N 条 capability，逐个验（当前数据是 1 条）
    tasks: list[tuple[dict, dict | None]] = []
    for w in workers:
        if not w["caps"]:
            tasks.append((w, None))
        else:
            for c in w["caps"]:
                tasks.append((w, c))

    log("=" * 96)
    log(f"数字人表单路由普查：tenant={args.tenant}，数字人 {len(workers)} 个，任务 {len(tasks)} 条，"
        f"并发 {args.concurrency}")
    log("=" * 96)

    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(probe_worker, w, c, token): (w, c) for w, c in tasks}
        done = 0
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                w, c = futs[fut]
                r = {"worker_id": w["id"], "worker": w["name"], "type": w["worker_type"],
                     "cap": c and c["form_code"], "verdict": "R4_FAIL",
                     "detail": f"未捕获异常：{exc}", "asked": ""}
            results.append(r)
            done += 1
            mark = {"PASS": "PASS", "CLARIFY": "CLAR", "NO_CAP": "NOCAP"}.get(r["verdict"], "FAIL")
            log(f"[{mark:5}] {done:>3}/{len(tasks)} {r['worker_id']:>5} {r['worker'][:14]:<14} "
                f"{str(r['cap']):<20} {r['detail'][:74]}")

    results.sort(key=lambda x: (x["verdict"] != "PASS", x["worker_id"]))

    # ---- 汇总 ----
    def cnt(v):
        return sum(1 for r in results if r["verdict"] == v)

    fails = [r for r in results if r["verdict"] in ("R1_FAIL", "R2_FAIL", "R3_FAIL", "R4_FAIL")]
    log("\n" + "=" * 96)
    log(f"用时 {time.time() - t0:.1f}s")
    log(f"PASS {cnt('PASS')} | CLARIFY {cnt('CLARIFY')} | NO_CAP {cnt('NO_CAP')} | FAIL {len(fails)}")
    for v in ("R1_FAIL", "R2_FAIL", "R3_FAIL", "R4_FAIL"):
        if cnt(v):
            log(f"  {v}: {cnt(v)}")
    if fails:
        log("\n失败明细：")
        for r in fails:
            log(f"  - {r['worker_id']} {r['worker']} [{r['cap']}] {r['verdict']}: {r['detail']}")
    nocap = [r for r in results if r["verdict"] == "NO_CAP"]
    if nocap:
        log("\n无能力绑定（结构上不可能调表）：")
        for r in nocap:
            log(f"  - {r['worker_id']} {r['worker']} ({r['type']})")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log(f"\n明细已写入 {args.json_out}")
    log("=" * 96)
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
