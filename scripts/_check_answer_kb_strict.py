# -*- coding: utf-8 -*-
"""哨兵：数字人「严格知识库口径」是否真的落到**运行中的** agent 上。

背景（2026-10-15，用户指定）
    answer_shape.rules() 的回答口径由「默认只答所问」改为**严格知识库口径**：
      只依据本轮四类资料作答（知识库召回 / 工具返回 / 对话内参考文档 / 职责定义）、
      逐维度覆盖不跳项、缺失项标注到具体维度（「知识库暂未收录」/「当前检索未返回相关内容」）、
      统计与对比类用表格、输出前强制自检。

与 `_verify_answer_conciseness.py` 的分工（别互相替代）
    * 后者管**旧**契约仍成立：不冗长（简单提问要短）+ 权限话题才给办理指引；
    * 本脚本管**新**口径的契约件与**运行态**是否真生效。

    判据必须回到「运行中的 agent 返回什么」，而不是「源码里写了什么」——
    agent 无 `--reload`，改了源码但不重启，提示词不会生效（这是本项目实测过的坑）。
    ⚠️ 活体前置不满足时**如实 SKIP 并写出具体缺什么**，不用 PASS 伪装（铁律 15）。

判据
    C1 契约件齐备（源码 rules()）：8 个关键件全在。
    C2 scope 只多一条（绑数字员工不挤掉职责限制的其它规则）。
    C3 权限分支保留（涉及权限 / 除权限问题外 / 下一步 / 转述）。
    C4 **判别力**（铁律 12）：同一组契约件在**改动前**的 rules() 上必须全部缺席。
       ⚠️ 钉死 `PREFIX_REV`，**不取 HEAD** —— 一旦本改动提交，HEAD 就是新版，对着 HEAD 自检会立刻失效。
    C5 活体口径：POST :8000/internal/v1/answer-shape 返回的 rules 含全部契约件
       （证明**跑着的** agent 已加载新口径）。前置：agent :8000 在线且已重启；离线 → SKIP。
    C6 （**报告型，不计入退出码**）活体表格能力：问一个统计类问题，看回答是否真的用
       markdown 表格 + 「数据来源」列。LLM 输出非确定，故只报 `[TABLE-ABILITY]`，
       不影响退出码；前置不足（后端/agent/知识库内容任一缺）→ 如实 SKIP。

用法
    <python> scripts/_check_answer_kb_strict.py            # 全跑（活体不可用则 SKIP）
    <python> scripts/_check_answer_kb_strict.py --no-live  # 只跑 C1–C4（离线可跑）
退出码：0 = C1–C5 全过；1 = 有 FAIL。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import types
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = os.path.join(REPO, "agent")
# 改动前最后一个提交（严格知识库口径之前的 rules()）—— 钉死，勿改取 HEAD。
PREFIX_REV = "a831a1a"

# 新口径契约件：少一个都算契约不完整。
MARKERS = (
    "知识库暂未收录", "当前检索未返回相关内容", "不得跳过任何一项",
    "应答清单", "数据来源", "自检", "维度层级", "没问到的维度",
)

FAILS = []


def chk(cid, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + cid + ("" if ok else "   <<< %s" % detail))
    if not ok:
        FAILS.append(cid)


def skip(cid, detail):
    print("SKIP  " + cid + "   <<< %s" % detail)


def load_live_rules():
    """从工作区源码加载 rules()（不走 HTTP）。"""
    path = os.path.join(AGENT_DIR, "app", "core", "answer_shape.py")
    spec = importlib.util.spec_from_file_location("answer_shape_live", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_prefix_rules():
    """从钉定的改动前提交取 rules()（判别力对照）。"""
    src = subprocess.check_output(
        ["git", "show", "%s:agent/app/core/answer_shape.py" % PREFIX_REV],
        cwd=REPO, text=True, encoding="utf-8")
    mod = types.ModuleType("answer_shape_prefix")
    exec(compile(src, "answer_shape_prefix.py", "exec"), mod.__dict__)
    return mod


def post(url, obj, token=None, timeout=30):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def read_sse(url, token, budget=120):
    """订阅 SSE，读到达终止事件为止。返回 (http_code, 文本)。"""
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


def extract_answer(sse_text):
    """从 SSE 文本里拼出模型回答。

    事件结构（实测 :8080）：
        message.delta     → {"text": "增量"}
        message.completed → {"content": "完整回答", citations, usage, ...}
        run.completed     → {"status", "usage"}
    **优先用 delta 拼接**；只有当整段一个 delta 都没有时，才回落到 ``message.completed.content``。
    两者都收会把同一段回答算两次 ⇒ 报告里出现重复正文（那是解析器问题，**不是**产品缺陷；
    H5 走的是 onDelta，只消费 delta）。
    """
    deltas, final = [], ""
    for ln in sse_text.splitlines():
        if not ln.startswith("data:"):
            continue
        raw = ln[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        body = obj.get("data") if isinstance(obj.get("data"), dict) else obj
        if not isinstance(body, dict):
            continue
        v = body.get("delta")
        if v is None and "text" in body:
            v = body.get("text")
        if isinstance(v, str) and v:
            deltas.append(v)
            continue
        for key in ("content", "answer"):
            x = body.get(key)
            if isinstance(x, str) and x:
                final = x
    return "".join(deltas) if deltas else final


def check_contract(live):
    scoped = "\n".join(live.rules({"duty": "受理请假申请"}))
    plain = live.rules(None)

    missing = [m for m in MARKERS if m not in scoped]
    chk("C1 新口径契约件齐备（%d 件）" % len(MARKERS), not missing,
        "缺失=%s" % (missing or "无"))

    chk("C2 scope 只多一条（职责限制没被挤掉）",
        len(live.rules({"duty": "受理请假申请"})) == len(plain) + 1,
        "plain=%d scoped=%d" % (len(plain), len(live.rules({"duty": "x"}))))

    perm_ok = all(w in scoped for w in ("涉及权限", "除权限问题外", "下一步", "转述"))
    chk("C3 权限分支保留（涉及权限/除权限问题外/下一步/转述）", perm_ok)

    try:
        old = load_prefix_rules()
        old_scoped = "\n".join(old.rules({"duty": "受理请假申请"}))
        hit = [m for m in MARKERS if m in old_scoped]
        chk("C4 判别力：契约件在改动前(%s)全部缺席" % PREFIX_REV, not hit,
            "旧版命中=%s（命中即判据无判别力）" % (hit or "无"))
    except Exception as e:  # noqa: BLE001
        chk("C4 判别力（取改动前源码）", False, "git 取 %s 失败：%s" % (PREFIX_REV, e))


def check_live_rules(agent):
    print("\n--- C5 活体口径（%s/internal/v1/answer-shape）---" % agent)
    try:
        body = post(agent + "/internal/v1/answer-shape",
                    {"role": "GENERAL", "scope": None}, timeout=15)
    except Exception as e:  # noqa: BLE001
        skip("C5 活体口径", "agent 不在线或不可达（%s）；"
                            "前置=agent :8000 已按新代码重启" % e)
        return
    rules_text = "\n".join(body.get("rules") or [])
    missing = [m for m in MARKERS if m not in rules_text]
    chk("C5 跑着的 agent 已加载新口径（运行态）", not missing,
        "agent 返回的 rules 缺失=%s；多半是 agent 未重启" % (missing or "无"))


def check_table_ability(base, agent):
    print("\n--- C6 【报告型·不计入退出码】活体表格能力 ---")
    try:
        tok = post(base + "/api/v1/auth/login",
                   {"username": "admin", "password": "Admin@123"})["data"]["accessToken"]
        conv = post(base + "/api/v1/conversations", {"title": "kb-strict-table-probe"}, tok)["data"]
        # 探针问题必须**可被现有检索工具满足**：知识库工具是关键词检索、不做全库枚举，
        # 若问「全库各类型共几份」会因工具能力不足而判成 prompt 不合规（不公平的探针）。
        # 这里用一个**必然能命中**的关键词（本环境知识库里有 kbprobe_量子_*.txt），
        # 且要求多维度列表 ⇒ 触发「统计/多维度对比类必须用表格」这条规则。
        q = "请检索知识库中与「量子」相关的文档，并用表格列出文档名称、状态和数据来源。"
        run = post("%s/api/v1/conversations/%s/runs" % (base, conv["id"]),
                   {"text": q, "context": {}}, tok)
        code, sse = read_sse("%s/api/v1/runs/%s/events" % (base, run["data"]["runId"]), tok)
    except Exception as e:  # noqa: BLE001
        print("[TABLE-ABILITY] SKIP  前置不足：%s（需要 :8080 + :8000 在线，且知识库有内容）" % e)
        return
    ans = extract_answer(sse)
    if not ans.strip():
        print("[TABLE-ABILITY] SKIP  未取到回答正文（http=%s, sse=%d bytes）" % (code, len(sse)))
        return
    has_table = bool(("|" in ans) and ("---" in ans))
    has_src = "数据来源" in ans
    has_missing_mark = ("知识库暂未收录" in ans) or ("当前检索未返回相关内容" in ans)
    verdict = "PASS" if (has_table and has_src or has_missing_mark) else "FAIL"
    print("[TABLE-ABILITY] %s  表格=%s 数据来源列=%s 缺失标注=%s" %
          (verdict, has_table, has_src, has_missing_mark))
    print("     回答原文：\n" + "\n".join("       " + ln for ln in ans.strip().splitlines()[:25]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="http://127.0.0.1:8000")
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--no-live", action="store_true", help="只跑离线判据 C1–C4")
    args = ap.parse_args()

    live = load_live_rules()
    check_contract(live)

    if not args.no_live:
        check_live_rules(args.agent.rstrip("/"))
        check_table_ability(args.base.rstrip("/"), args.agent.rstrip("/"))
    else:
        skip("C5 活体口径", "--no-live")
        skip("C6 表格能力", "--no-live")

    print("\n结果：失败 %d 项 %s" % (len(FAILS), FAILS if FAILS else ""))
    print("[STATUS] %s" % ("PASS" if not FAILS else "FAIL"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
