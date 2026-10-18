# -*- coding: utf-8 -*-
"""跨数字人自动转交（handoff）端到端验收 —— 真实后端 + 真实库 + 真实模型
================================================================================

## 验的是什么

需求：用户当前绑定「A 数字人」，却说了一件属于「B 数字人」的事 ⇒ 后端应当
① 在同一会话内把 `worker_id` 改绑到 B（**不换会话**，否则历史丢失）；
② 用**同一条已落库的用户消息**继续跑（不重复落 user 消息、不让用户重述）；
③ 先发一帧 `worker.handoff` 告诉前端切人，随后 B 按自己的职责处理。

## 判据

  H1  流里出现 `worker.handoff`，且是最先到达的事件
  H2  载荷 `to_worker_id` == 期望目标（由库按与后端同一规则算出，不写死 id）
  H3  库里 `chat_conversation.worker_id` 已变为目标（证明是**改绑**而不是换个说法）
  H4  ★该会话里这条提问的用户消息**只有 1 条**（没重复落库 —— 需求「不要重述」的硬判据）
  H5  转交后由目标数字人继续处理：出现 `need_form` 且 `form_code` == 目标的 capability
      （这条同时证明「换人真的换了执行者」，而不是只发个通知帧）
  H6  负向对照：同一会话（此刻已绑目标）问一句不属于任何他人的话 ⇒ **不得**出现 worker.handoff

## 跑法
    agent/.venv/Scripts/python.exe scripts/_verify_worker_handoff.py
    ... --tenant 3 --user wjj_xu --pwd User@123

前置：后端 :8080、agent :8000、本地 MySQL（127.0.0.1:3306 root 空密码 库 aios）。
前置不满足 ⇒ 打印 SKIP 并 exit 2（与全仓矩阵同口径，不伪装 PASS）。
"""
from __future__ import annotations

import argparse
import json
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


def _sse(run_id: str, token: str) -> list[tuple[str, str]]:
    """读 SSE 到「暂停帧」或终态帧为止，返回 [(event, raw_data)]。

    与 `_verify_worker_form_routing.py:_sse` 同口径（readline 逐行读、空行分帧）：
    `worker.handoff` 是**通知帧不是暂停帧**，不能在此提前 break，否则看不到后续
    `need_form`（H5 的判据就靠它证明「换人后由新数字人继续办理」）。
    """
    req = urllib.request.Request(f"{BASE}/runs/{run_id}/events")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "text/event-stream")
    events: list[tuple[str, str]] = []
    cur_event, cur_data = "message", []
    try:
        with urllib.request.urlopen(req, timeout=SSE_TIMEOUT) as resp:
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "ignore").rstrip("\r\n")
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
    except Exception as exc:  # noqa: BLE001
        # 不静默吞掉：零帧时必须能看出是「流断了」还是「服务端没发」
        log(f"       [warn] SSE 读取中断（已收到 {len(events)} 帧）：{exc!r}")
    return events


def load_caps(tenant: int) -> list[dict]:
    import pymysql

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select w.id, w.name, w.worker_type, c.task_code, c.task_name, c.form_code "
                "from agent_worker w join worker_capability c on c.worker_id = w.id "
                "where w.tenant_id=%s and w.deleted_at is null and w.enabled=1 "
                "  and c.deleted_at is null and (c.enabled is null or c.enabled<>0) "
                "order by w.id, c.sort, c.id", (tenant,))
            return list(cur.fetchall())
    finally:
        conn.close()


def conv_worker_id(conv_id: int) -> int | None:
    import pymysql

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("select worker_id from chat_conversation where id=%s", (conv_id,))
            row = cur.fetchone()
            return None if not row else row["worker_id"]
    finally:
        conn.close()


def user_msg_count(conv_id: int, text: str) -> int:
    import pymysql

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) as n from chat_message where conversation_id=%s and role='USER'",
                        (conv_id,))
            total = cur.fetchone()["n"]
            cur.execute("select count(*) as n from chat_message where conversation_id=%s "
                        "and role='USER' and content=%s", (conv_id, text))
            same = cur.fetchone()["n"]
            return same if same else total
    finally:
        conn.close()


def pick_pair(caps: list[dict]) -> tuple[dict, dict, str] | None:
    """按与后端 matchHandoff 同一规则选一组 (当前 worker, 目标 capability, 提问文本)。

    规则复述：文本包含某 worker 的 task_name（>=2 字）或 task_code ⇒ 该 worker 命中；
    命中集合必须**恰好只有一个** worker，且它不是当前 worker。
    """
    names = {}
    for c in caps:
        names.setdefault(c["id"], []).append(c)

    def matched(text: str) -> set[int]:
        hit = set()
        for c in caps:
            tn = (c.get("task_name") or "").strip()
            tc = (c.get("task_code") or "").strip()
            if (len(tn) >= 2 and tn in text) or (tc and tc in text):
                hit.add(c["id"])
        return hit

    for target in caps:
        tn = (target.get("task_name") or "").strip()
        if len(tn) < 2:
            continue
        text = f"我要办理{tn}。"
        if matched(text) != {target["id"]}:
            continue
        for cur in names:
            if cur == target["id"]:
                continue
            return names[cur][0], target, text
    return None


# ---- Tier B（口语化）用例挑选 -------------------------------------------------
# 与后端 matchHandoff 的 Tier B 同口径：任务名剥掉「申请/办理/…」等通用词得核心词，
# 再与用户原话求最长公共子串。这里只用它**挑一个无歧义的用例**（目标唯一最高分、
# 当前数字人不重叠），判定本身仍由后端做 —— 不在此重复实现业务判定。
_GENERIC_WORDS = ("申请", "办理", "审批", "流程", "助手", "数字人", "工作", "业务", "管理",
                  "服务", "信息", "记录", "统计", "查询", "处理", "系统", "平台", "客服",
                  "支持", "配置", "录入", "下发", "发起", "发布", "维护", "借阅", "起草",
                  "添加", "新建", "申诉", "报名", "上报", "设置", "填报")


def _core_task_name(task_name: str) -> str:
    s = (task_name or "").strip()
    changed = True
    while changed:
        changed = False
        for g in sorted(_GENERIC_WORDS, key=len, reverse=True):
            if s.endswith(g) and len(s) - len(g) >= 2:
                s = s[: len(s) - len(g)]
                changed = True
                break
    return s


def _core_overlap(user_text: str, task_name: str) -> str:
    core = _core_task_name(task_name).lower()
    u = (user_text or "").lower()
    best = ""
    for i in range(len(u)):
        for j in range(i + 2, len(u) + 1):
            frag = u[i:j]
            if frag in core and len(frag) > len(best) and frag not in _GENERIC_WORDS:
                best = frag
    return best


def pick_colloquial(caps: list[dict]) -> tuple[dict, dict, str] | None:
    """挑一组「口语化提问」（不含任何任务全名）仍应转交的组合。

    条件：① 该句不含任何 task_name/task_code（Tier A 全不命中）；
         ② 目标核心词重叠分唯一最高且 >= 2；③ 当前数字人重叠 < 2。
    """
    for target in caps:
        core = _core_task_name(target.get("task_name") or "")
        if len(core) < 2 or core == (target.get("task_name") or "").strip():
            continue  # 剥不出核心词（本身就短）⇒ 无法构造口语化说法
        text = f"我要{core}，应该怎么弄？"
        # ① Tier A 必须完全不命中（否则测的就不是 Tier B）
        if any(((c.get("task_name") or "").strip() and len((c.get("task_name") or "").strip()) >= 2
                and (c.get("task_name") or "").strip() in text)
               or ((c.get("task_code") or "").strip() and (c.get("task_code") or "").strip() in text)
               for c in caps):
            continue
        scores = {}
        for c in caps:
            scores[c["id"]] = len(_core_overlap(text, c.get("task_name") or ""))
        tscore = scores.get(target["id"], 0)
        if tscore < 2:
            continue
        others = [s for wid, s in scores.items() if wid != target["id"]]
        if others and max(others) >= tscore:
            continue  # 并列或更高 ⇒ 后端会放弃，不是可用用例
        for cur in scores:
            if cur != target["id"] and scores[cur] < 2:
                by_worker = {c["id"]: c for c in caps}
                return by_worker[cur], target, text
    return None



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
        caps = load_caps(args.tenant)
    except Exception as exc:  # noqa: BLE001
        log(f"[SKIP] 读库失败（需要本地 MySQL 3306 / root 空密码 / 库 aios）：{exc}")
        return 2

    pair = pick_pair(caps)
    if pair is None:
        log("[SKIP] 本租户找不到「提问只会命中唯一他人」的组合（数据不满足，非产品缺陷）")
        return 2
    cur_cap, target, text = pair

    log("=" * 92)
    log(f"跨数字人转交验收：tenant={args.tenant} 当前={cur_cap['id']} {cur_cap['name']} "
        f"→ 目标={target['id']} {target['name']}")
    log(f"提问：{text}")
    log("=" * 92)

    ok = 0
    bad = 0

    def chk(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok, bad
        if cond:
            ok += 1
            log(f"[PASS] {label}  {detail}")
        else:
            bad += 1
            log(f"[FAIL] {label}  {detail}")

    conv_id = None
    try:
        conv = _unwrap(_req("/conversations", "POST",
                            {"title": "转交验收", "workerId": cur_cap["id"]}, token))
        conv_id = conv.get("id")
        chk("H0 会话初始绑定当前数字人", conv_worker_id(conv_id) == cur_cap["id"],
            f"conv={conv_id} worker={conv_worker_id(conv_id)}")

        run = _unwrap(_req(f"/conversations/{conv_id}/runs", "POST", {"text": text}, token))
        run_id = run.get("runId") or run.get("run_id")
        events = _sse(str(run_id), token)
        names = [e for e, _ in events]
        log(f"       首发帧：{names}")

        first = names[0] if names else None
        chk("H1 最先到达的是 worker.handoff", first == "worker.handoff", f"first={first}")
        payload = {}
        for e, d in events:
            if e == "worker.handoff":
                try:
                    payload = json.loads(d)
                except Exception:  # noqa: BLE001
                    payload = {}
                break
        chk("H2 载荷 to_worker_id == 期望目标",
            int(payload.get("to_worker_id") or 0) == int(target["id"]),
            f"got={payload.get('to_worker_id')} expect={target['id']} name={payload.get('to_worker_name')}")
        chk("H2b 载荷带原问题（供前端展示，不含内部流程）",
            str(payload.get("question") or "") == text, f"question={payload.get('question')}")
        chk("H3 会话已改绑到目标（同会话，不换 id）",
            conv_worker_id(conv_id) == target["id"], f"worker={conv_worker_id(conv_id)}")

        n = user_msg_count(conv_id, text)
        chk("H4 ★用户消息只落 1 条（未重复入库）", n == 1, f"count={n}")

        forms = [(e, d) for e, d in events if e == "need_form"]
        got_form = ""
        if forms:
            try:
                got_form = (json.loads(forms[0][1]) or {}).get("form_code") or ""
            except Exception:  # noqa: BLE001
                got_form = ""
        chk("H5 转交后由目标数字人继续办理（开它自己的表单）",
            got_form == target["form_code"],
            f"got={got_form or '无 need_form'} expect={target['form_code']} frames={names}")

        # ---- H6 负向对照：此刻会话已绑目标，问一句不属于任何他人职责的话 ----
        run2 = _unwrap(_req(f"/conversations/{conv_id}/runs", "POST",
                            {"text": "你好，简单介绍一下你自己"}, token))
        ev2 = _sse(str(run2.get("runId") or run2.get("run_id")), token)
        chk("H6 负向对照：普通寒暄不得触发转交",
            "worker.handoff" not in [e for e, _ in ev2], f"frames={[e for e, _ in ev2]}")

        # ---- H7 口语化提问（Tier B：不含任务全名，只有核心词重合）----
        # 库里任务名是书面语（「费用报销申请」），用户说的是口语（「我要报销差旅费」）。
        # 只做整词匹配时这类提问永远转不出去 —— 这条用例就是钉住 Tier B 是否真的生效。
        colloquial = pick_colloquial(caps)
        if colloquial is None:
            chk("H7 口语化提问也能转交（Tier B）", False,
                "数据里挑不出无歧义的口语化用例（非产品缺陷，但需要补能力数据）")
        else:
            c_cur, c_target, c_text = colloquial
            conv2 = _unwrap(_req("/conversations", "POST",
                                 {"title": "口语化转交验收", "workerId": c_cur["id"]}, token))
            cid2 = conv2.get("id")
            try:
                run3 = _unwrap(_req(f"/conversations/{cid2}/runs", "POST", {"text": c_text}, token))
                ev3 = _sse(str(run3.get("runId") or run3.get("run_id")), token)
                pay3 = {}
                for e, d in ev3:
                    if e == "worker.handoff":
                        try:
                            pay3 = json.loads(d)
                        except Exception:  # noqa: BLE001
                            pay3 = {}
                        break
                chk("H7 口语化提问也能转交（Tier B）",
                    int(pay3.get("to_worker_id") or 0) == int(c_target["id"])
                    and conv_worker_id(cid2) == c_target["id"],
                    f"「{c_text}」{c_cur['name']} → {pay3.get('to_worker_name') or '未转交'}"
                    f"（期望 {c_target['name']}）")
                chk("H7b 口语化转交后用户消息仍只落 1 条",
                    user_msg_count(cid2, c_text) == 1, f"count={user_msg_count(cid2, c_text)}")
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
