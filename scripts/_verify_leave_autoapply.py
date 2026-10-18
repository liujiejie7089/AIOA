# -*- coding: utf-8 -*-
"""请假动作意图修复的第一层 QA：验证「裸请假语料不得触发 apply_permission 自动落库」。

正对照（特性不被拔掉）：fagai_liu 显式要求「请直接调用工具帮我提交 approval:leave 权限申请」
  → SSE 仍出现 tool.call(apply_permission) 且 permission_grant 新增一行（V36 既有特性保留）。
负对照（本次缺陷的判别性断言）：裸语料「我要请假两天」连跑 5 轮，断言 0 条新增 grant 行。
收尾：fagai_admin 驳回该 grant，确认 fagai_liu 的 approval:leave 回到 held=false/pending=false。

注意：负对照是**统计性**证据而非硬门禁——修前该语料自动触发率约 2/3，5 轮 0 触发在
原行为下概率约 (1/3)^5≈0.4%，可判定提示词生效，但提示词本身不构成硬门禁（硬门禁需服务端）。
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080/api/v1"
PERM = "approval:leave"
U = "fagai_liu"
A = "fagai_admin"
PWD = "User@123"

RESULTS = []


def chk(tag, cond, detail=""):
    RESULTS.append((tag, bool(cond), detail))
    print(("PASS  " if cond else "FAIL  ") + tag + (("   <<< " + detail) if detail else ""))
    return bool(cond)


def post(url, obj, token=None, timeout=60):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def get(url, token, timeout=60):
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def read_sse(url, token, budget=150):
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "text/event-stream")
    buf, code = [], 0
    try:
        with urllib.request.urlopen(req, timeout=budget) as r:
            code = r.status
            import time as _t
            deadline = _t.time() + budget
            while _t.time() < deadline:
                line = r.readline()
                if not line:
                    break
                buf.append(line.decode("utf-8", "replace"))
                j = "".join(buf)
                if "event:run.completed" in j or "event:run.failed" in j:
                    break
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:  # noqa: BLE001
        buf.append("EXC: %s" % e)
    return code, "".join(buf)


def list_grants(tok):
    st, b = get(BASE + "/org/permissions/mine", tok)
    items = []
    if isinstance(b, dict) and b.get("code") == 0:
        v = b["data"]
        items = v if isinstance(v, list) else v.get("items") or v.get("list") or []
    return [g for g in items if g.get("permissionCode") == PERM]


def login(u):
    st, b = post(BASE + "/auth/login", {"username": u, "password": PWD})
    if b.get("code") != 0:
        raise SystemExit("登录失败 %s: %s" % (u, b.get("message")))
    return b["data"]["accessToken"]


def new_conv(tok):
    st, b = post(BASE + "/conversations", {"title": "leave-qa"}, tok)
    return b["data"]["id"]


def run_and_sse(tok, cid, text):
    st, b = post("%s/conversations/%s/runs" % (BASE, cid), {"text": text, "context": {}}, tok)
    if b.get("code") != 0:
        return None, None, b.get("message")
    rid = b["data"]["runId"]
    code, sse = read_sse("%s/runs/%s/events" % (BASE, rid), tok)
    return rid, sse, None


def find_apply_call(sse):
    """从 SSE 文本里找 tool.call 调 apply_permission 与 tool.result(apply_permission)。"""
    has_call = ("event:tool.call" in sse) and ("apply_permission" in sse)
    has_result = ("event:tool.result" in sse) and ("apply_permission" in sse)
    return has_call, has_result


def main():
    t_u = login(U)
    t_a = login(A)

    # ---------- 正对照：显式要求提交权限申请，特性必须仍在 ----------
    print("\n===== 正对照：显式申请（V36 特性保留）=====")
    before = list_grants(t_u)
    n_before = len(before)

    cid = new_conv(t_u)
    rid, sse, err = run_and_sse(
        t_u, cid,
        "请直接调用工具帮我提交 approval:leave 权限申请，理由：e2e 显式验证")
    if sse is None:
        chk("正对照·run 返回成功", False, str(err))
    else:
        chk("正对照·run 成功返回 SSE", True)
        hc, hr = find_apply_call(sse)
        chk("正对照·SSE 出现 tool.call(apply_permission)", hc,
            "SSE 前 400 字符：%s" % sse[:400].replace("\n", " ⏎ "))
        chk("正对照·SSE 出现 tool.result(apply_permission)", hr)

    # 等一拍让落库生效
    import time
    time.sleep(3)
    after = list_grants(t_u)
    n_after = len(after)
    chk("正对照·permission_grant 新增一行", n_after == n_before + 1,
        "before=%d after=%d" % (n_before, n_after))
    new_grant = next((g for g in after if g not in before), None)
    if new_grant:
        print("      新增 grant: id=%s status=%s reason=%s" % (
            new_grant.get("id"), new_grant.get("status"), new_grant.get("reason")))
        chk("正对照·新 grant 为 PENDING", new_grant.get("status") == "PENDING",
            str(new_grant.get("status")))

    # ---------- 收尾复位：fagai_admin 驳回，回到 held=false/pending=false ----------
    print("\n===== 收尾复位：驳回并校验回到未申请态 =====")
    # 找 fagai_admin 待办里对应单据
    st, b = get(BASE + "/workflow/tasks?scope=todo", t_a)
    todo = []
    if isinstance(b, dict) and b.get("code") == 0:
        v = b["data"]
        todo = v if isinstance(v, list) else v.get("items") or v.get("list") or []
    order_id = new_grant.get("orderId") if new_grant else None
    target = next((t for t in todo if t.get("id") == order_id), None)
    if target:
        st2, b2 = post(BASE + "/workflow/tasks/%s/decide" % target["taskId"],
                       {"decision": "REJECT", "note": "e2e 复位"}, t_a)
        chk("收尾·admin 驳回成功", st2 == 200 and b2.get("code") == 0,
            "http=%s code=%s" % (st2, b2.get("code")))
    else:
        chk("收尾·在 admin 待办找到该单据", False,
            "order_id=%s todo 共 %d 条" % (order_id, len(todo)))

    time.sleep(2)
    st, b = get(BASE + "/org/permissions/catalog", t_u)
    cat = b.get("data") or {}
    items = cat.get("items") if isinstance(cat, dict) else cat
    it = next((x for x in items if x.get("permissionCode") == PERM), None) if isinstance(items, list) else None
    if it:
        chk("收尾·approval:leave 回到 held=false", it.get("held") is False, str(it.get("held")))
        chk("收尾·approval:leave 回到 pending=false", it.get("pending") is False,
            str(it.get("pending")))
    else:
        chk("收尾·目录含 approval:leave", False, "catalog=%s" % str(cat)[:120])

    # ---------- 负对照：裸语料「我要请假两天」×5 轮，0 新增 grant ----------
    print("\n===== 负对照：裸请假语料 5 轮（统计性证据）=====")
    base_count = len(list_grants(t_u))
    new_rows_total = 0
    for i in range(1, 6):
        # 每轮先确认无 PENDING（异常兜底：若有旧 PENDING 先记下来，不计入本轮新增）
        pending_before = [g for g in list_grants(t_u) if g.get("status") == "PENDING"]
        cid = new_conv(t_u)
        rid, sse, err = run_and_sse(t_u, cid, "我要请假两天")
        if sse is None:
            chk("负对照·第 %d 轮 run 成功" % i, False, str(err))
            continue
        hc, hr = find_apply_call(sse)
        if hc:
            # 取出 tool.call 里的参数，确认是否真落库
            print("      [第 %d 轮] 检测到 tool.call(apply_permission)！SSE=%s"
                  % (i, sse[:300].replace("\n", " ⏎ ")))
        # 等落库
        time.sleep(2)
        grants_after = list_grants(t_u)
        # 本轮新增：总数增量（扣除已有的 PENDING 作为异常兜底）
        new_this_round = len(grants_after) - base_count - new_rows_total
        new_rows_total = len(grants_after) - base_count
        if new_this_round > 0:
            print("      [第 %d 轮] 新增 %d 行 grant（SSE 含 tool.call=%s tool.result=%s）"
                  % (i, new_this_round, hc, hr))
        chk("负对照·第 %d 轮 无新增 grant 行" % i, new_this_round == 0,
            "new=%d tool_call=%s" % (new_this_round, hc))

    chk("负对照·5 轮合计 0 新增 grant 行", new_rows_total == 0,
        "base=%d total_new=%d" % (base_count, new_rows_total))

    # ---------- 汇总 ----------
    fails = [r for r in RESULTS if not r[1]]
    print("\n结果：%d/%d 通过；失败 %d 项" % (len(RESULTS) - len(fails), len(RESULTS), len(fails)))
    for t, _, d in fails:
        print("  FAIL " + t + "  " + d)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
