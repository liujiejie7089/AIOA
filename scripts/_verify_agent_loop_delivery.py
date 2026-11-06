# -*- coding: utf-8 -*-
"""agent loop 完成判定闭环：真机验收（2026-11-06，docs/86）。

## 现场缺陷（用户截图）

用户说「帮我写一份周报」，界面只出现一句
「我先把本周的原始素材拉齐，再整理成周报。」+ 一张「数据来源 · 4 个」引用卡，
周报正文一个字都没有，run 却记 SUCCEEDED。库里 ``chat_message#2966`` 留着同款
真实原文：「我先收集本周的实际数据（日志、考勤、审批、业务产出），再据此起草周报。」

根因：旧 loop 的结束判定只有「本轮有没有 tool_calls」——聚合扇出在 prepare 阶段由代码
直连完成，模型无需再调工具，于是「零调用 ⇒ finalize」，导语被当成最终答案。

## 本脚本验什么

不是「代码里写了闸」，而是**用户真实发起一轮周报后拿到的东西**：
  * 走 :8080 的建会话 → 发 run → SSE 全链路（与界面同源）；
  * 落库正文回库核（铁律 7/12：界面展示了 X 须回到库再取，不得同源）；
  * delta 逐帧拼接 == message.completed.content == chat_message.content（三者同源）；
  * 正文必须是成稿：够长、有分节、交代完成状态/已覆盖需求/完成依据、无「待续」类收尾；
  * 数据来源引用卡**仍在**（修完成判定不能把聚合来源一起弄丢）；
  * 判别力证明（防判据恒真）：把库里那句真实旧导语喂给 `assess_delivery` 必须判红，
    把本次成稿喂进去必须判绿；
  * 确定性路由与活体提示词：补齐态必须回 agent、系统提示词必须带闭环约束、
    聚合素材块必须写明「本轮就要给出成稿」。

额度耗尽视为环境限制如实 SKIP（不是 PASS、也不是缺陷）；静态/活体判据仍照跑，
其余可执行内容不因 SKIP 停摆。测试会话跑完逻辑删除，不留污染数据。

用法：
    agent/.venv/Scripts/python.exe scripts/_verify_agent_loop_delivery.py
    agent/.venv/Scripts/python.exe scripts/_verify_agent_loop_delivery.py --static-only
退出码：0 = 全过；1 = 有 FAIL；2 = 仅 SKIP（环境不可用）。
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印中文/✅ 会 UnicodeEncodeError
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import json
import os
import re
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "http://127.0.0.1:8080"
API = BASE + "/api/v1"
AGENT = "http://127.0.0.1:8000"
MYSQL = r"D:\dev\mysql\mysql-8.4.10-winx64\bin\mysql.exe"
USER, PWD = "test", "test"
QUESTION = "帮我写一份周报"
# 截图现场那句真实导语（chat_message#2966 原文，一字未改）——用于判别力证明。
OLD_LEAD = "我先收集本周的实际数据（日志、考勤、审批、业务产出），再据此起草周报。"
MIN_CHARS = 140

PASS, FAIL, SKIP, RES = [], [], [], []


def chk(cid, ok, expect="", actual="", note=""):
    RES.append((cid, bool(ok)))
    (PASS if ok else FAIL).append(cid)
    print("  [%s] %s" % ("PASS" if ok else "FAIL", cid))
    if expect != "" or actual != "":
        print("        expect=%r" % (expect,))
        print("        actual=%r" % (str(actual)[:400],))
    if note:
        print("        note  : %s" % note)
    return bool(ok)


def skip(cid, why):
    SKIP.append(cid)
    print("  [SKIP] %s — %s" % (cid, why))
    return False


def sql_one(q):
    r = subprocess.run([MYSQL, "-uroot", "aios", "-N", "-e", q],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").strip()


def svc_headers():
    from _svc_token import svc_headers as _h
    return _h()


# ---------------------------------------------------------------- 静态 / 活体代码判据

def case_code():
    print("\n=== A. 确定性闸与活体提示词（不消耗额度） ===")
    from aios_ai.graph import delivery
    from aios_ai.graph.nodes import route_after_agent
    from aios_ai.prompt.builder import build_messages
    from aios_ai.contracts import RunRequest, UserContext
    from aios_ai.aggregate.plan import build_block, is_aggregate_request

    # A1 判别力证明之一：真实旧导语必须判红（否则闸是恒真的摆设）
    ok_old, why_old = delivery.assess_delivery(OLD_LEAD, True)
    chk("A1 现场旧导语被完成判定判红（防判据恒真）", not ok_old,
        False, ok_old, "原因=%s；原文=%s" % (why_old, OLD_LEAD))

    # A2 交付意图识别：周报类诉求必须算交付任务，闲聊不能算
    chk("A2 「帮我写一份周报」命中交付类诉求 + 跨源聚合",
        delivery.is_delivery_request(QUESTION) and is_aggregate_request(QUESTION),
        True, (delivery.is_delivery_request(QUESTION), is_aggregate_request(QUESTION)))
    chk("A2b 闲聊「你好」不被误判为交付任务",
        not delivery.is_delivery_request("你好"), False,
        delivery.is_delivery_request("你好"))

    # A3 确定性路由：补齐态必须回到 agent，普通收尾必须 finalize
    go = route_after_agent({"pending_calls": [], "delivery_pending": True, "allow_tools": True})
    end = route_after_agent({"pending_calls": [], "delivery_pending": False, "allow_tools": True})
    chk("A3 补齐态 route_after_agent ⇒ agent 自环；正常态 ⇒ finalize",
        go == "agent" and end == "finalize", ("agent", "finalize"), (go, end))

    # A4 补齐轮上下文：必须有 assistant 导语 + 继续指令，且不出现连续 user 消息
    src = open(os.path.join(ROOT, "agent", "aios_ai", "graph", "nodes.py"),
               encoding="utf-8").read()
    seg = src[src.find("if delivery_pending:"):src.find("if delivery_pending:") + 900]
    chk("A4 补齐轮把 assistant 导语并入上下文（不是两条连续 user）",
        '"role": "assistant"' in seg and '"role": "user"' in seg
        and "continuation_prompt" in seg,
        "assistant + user + continuation_prompt", seg[:160].replace("\n", " / "))

    # A5 活体系统提示词：闭环约束真的进了发给模型的 messages
    req = RunRequest(run_id="run_delivery_live", conversation_id=1, text=QUESTION,
                     user_context=UserContext(user_id=3240, tenant_id=56))
    msgs = build_messages(req)
    system = "\n".join(str(m.get("content") or "") for m in msgs if m.get("role") == "system")
    chk("A5 活体系统提示词含「任务闭环 · agent loop 核心执行约束」",
        "任务闭环" in system and "完成状态" in system and "已覆盖" in system
        and "完成依据" in system and "不得结束" in system,
        "闭环/完成状态/已覆盖/完成依据/不得结束",
        [k for k in ("任务闭环", "完成状态", "已覆盖", "完成依据", "不得结束")
         if k in system])

    # A6 聚合素材块：明确「本轮就要给出成稿」「来源清单不是交付」
    block = build_block([], 5, kb={"ok": False, "count": 0})
    chk("A6 聚合素材块写明本轮成稿 + 来源清单不是正文 + 三要素",
        "本轮就要给出成稿" in block and "来源清单" in block
        and "完成状态" in block and "已覆盖" in block and "完成依据" in block,
        "成稿/来源清单/三要素", [k for k in
                              ("本轮就要给出成稿", "来源清单", "完成状态", "已覆盖", "完成依据")
                              if k in block])

    # A7 补齐用尽诚实兜底：不得伪装成功，也不得用「待续」收尾
    note = delivery.exhausted_note("正文过短", delivery.MAX_DELIVERY_RETRIES, True)
    chk("A7 用尽补齐轮如实标注未完成（未决项/当前状态/下一步）",
        "本轮未完成" in note and "未决项" in note and "当前状态" in note
        and "下一步可行路径" in note and "待续" not in note,
        "未完成/未决项/当前状态/下一步，且无「待续」", note[:150].replace("\n", " / "))


# ---------------------------------------------------------------- 真机全链路

def frames_of(resp_text):
    # 用 re.split 而不是 str.splitlines()：后者还会按 U+2028/U+0085 等 Unicode
    # 行边界切正文里的中文长 JSON，造成「Unterminated string」假故障。
    out, ev, buf = [], "", []
    for line in re.split(r"\r?\n", resp_text):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[5:].lstrip())
        elif line.startswith(":"):
            continue
        elif line == "":
            if ev:
                out.append((ev, "\n".join(buf)))
            ev, buf = "", []
        # 其余行（id: / retry: / 未知字段）一律忽略。曾试过把「续行」并进 buf，
        # 结果把 id:null 之类的行拼进 JSON，制造出 delta 多 2 字的假故障。
    if ev:
        out.append((ev, "\n".join(buf)))
    return out


def frame_json(data):
    """解析帧 payload：正常单行直接解；被折行的长 JSON 去掉行间换行再解。"""
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return json.loads(data.replace("\n", ""))


def case_live(model_ref=None):
    print("\n=== B. 真机全链路：发「帮我写一份周报」 ===")
    from aios_ai.graph import delivery
    if model_ref:
        print("  本轮指定模型通道 %s（不改全局默认配置；默认通道余额耗尽时的绕行）" % model_ref)

    s = requests.Session()
    s.trust_env = False
    r = s.post(API + "/auth/login", json={"username": USER, "password": PWD}, timeout=20)
    if r.status_code != 200 or r.json().get("code") != 0:
        return skip("B 真机全链路", "登录失败：%s %s" % (r.status_code, r.text[:200]))
    tok = r.json()["data"]["accessToken"]
    h = {"Authorization": "Bearer " + tok}

    conv = s.post(API + "/conversations", headers=h,
                  json={"title": "agent loop 真机验收", "source": "aios-client"}, timeout=20)
    cid = (conv.json().get("data") or {}).get("id")
    if not cid:
        return skip("B 真机全链路", "建会话失败：%s" % conv.text[:200])
    print("  convId=%s" % cid)

    try:
        body = {"text": QUESTION, "context": {}, "kb_on": True}
        if model_ref:
            body["model_ref"] = model_ref
        rr = s.post(API + "/conversations/%s/runs" % cid, headers=h,
                    json=body, timeout=30)
        d = rr.json()
        if d.get("code") == 403 and "额度" in str(d.get("message") or ""):
            return skip("B 真机全链路", "今日额度已用完（环境限制）：%s" % str(d.get("message"))[:120])
        rid = (d.get("data") or {}).get("runId") or (d.get("data") or {}).get("id")
        if not rid:
            return skip("B 真机全链路", "发 run 失败：%s" % rr.text[:250])
        print("  runId=%s（SSE 最长 300s，聚合扇出需要时间）" % rid)

        with s.get(API + "/runs/%s/events" % rid, headers=h, stream=True,
                   timeout=(15, 300)) as resp:
            # SSE 响应通常不带 charset，requests 会按 latin-1 解码 ⇒ 中文全成
            # 「å·²ä¸º…」乱码，长度翻倍、中文判据恒假。必须显式按 utf-8 解。
            raw = resp.content.decode("utf-8", "replace")

        frames = frames_of(raw)
        types = [t for t, _ in frames]
        print("  frames(%d): %s" % (len(types), types[:24]))
        if "message.completed" not in types:
            return chk("B1 SSE 收到 message.completed", False, True, types)

        completed = frame_json(next(d for t, d in frames if t == "message.completed"))
        content = completed.get("content") or ""
        deltas = "".join(frame_json(d).get("text", "")
                         for t, d in frames if t == "message.delta")
        cites = completed.get("citations") or []
        print("  正文 %d 字，引用 %d 条" % (len(content), len(cites)))
        print("  正文节选：%s" % content[:220].replace("\n", " / "))

        chk("B1 SSE 收到 message.completed 且 run.completed 收口",
            "run.completed" in types, True, types[-4:])
        chk("B2 界面 delta 逐帧拼接 == message.completed.content（同源）",
            deltas == content, "%d 字" % len(content),
            "delta=%d 字 / completed=%d 字" % (len(deltas), len(content)))

        # 铁律 7/12：回库核，不看界面自述。
        # 必须用 pymysql 取值：mysql -N 命令行会把正文里的真实换行转义成字面 \n，
        # 造成「库里 699 字 vs SSE 674 字」的假不一致（实测 25 个换行 → 多 25 字）。
        import pymysql
        conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                              database="aios", charset="utf8mb4")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT content FROM chat_message "
                            "WHERE run_id=%s AND role='assistant' ORDER BY id DESC LIMIT 1",
                            (rid,))
                row = cur.fetchone()
                db_content = (row[0] or "") if row else ""
        finally:
            conn.close()
        chk("B3 落库 chat_message.content == SSE completed.content（回到库再取）",
            bool(db_content) and db_content == content,
            "%d 字" % len(content), "库里 %d 字" % len(db_content),
            "库里前 80 字：%s" % db_content[:80].replace("\n", " / "))

        # 核心判据：不再是「只有导语」
        chk("B4 最终正文不是只有一句导语（≥ %d 字）" % MIN_CHARS,
            len(content.strip()) >= MIN_CHARS, "≥%d" % MIN_CHARS, len(content.strip()))
        chk("B5 正文含成稿结构（分节 / 编号 / 条目）",
            bool(delivery.SECTION_RE.search(content)), True,
            bool(delivery.SECTION_RE.search(content)))
        chk("B6 正文交代完成状态 / 已覆盖需求 / 完成依据（三要素齐全）",
            all(k in content for k in ("完成状态", "已覆盖", "完成依据")),
            ["完成状态", "已覆盖", "完成依据"],
            [k for k in ("完成状态", "已覆盖", "完成依据") if k in content])
        chk("B7 无「待续 / 稍后补充 / 剩余部分自行处理」类未完收尾",
            not delivery.UNFINISHED_RE.search(content), False,
            bool(delivery.UNFINISHED_RE.search(content)))
        chk("B8 正文含周报实体内容（本周/下周/进展/计划 至少两项）",
            sum(1 for k in ("本周", "下周", "进展", "计划", "工作", "完成") if k in content) >= 2,
            "≥2 项", [k for k in ("本周", "下周", "进展", "计划", "工作", "完成") if k in content])

        ok_final, why_final = delivery.assess_delivery(content, True)
        chk("B9 完成判定对本次真机正文判绿（判别力证明的另一半）",
            ok_final, True, (ok_final, why_final))

        srcs = {c.get("source") for c in cites if isinstance(c, dict)}
        chk("B10 数据来源引用卡仍在（聚合来源未丢失）",
            len(cites) > 0 and any(x not in ("knowledge_base", "web") for x in srcs),
            "非空且含非知识库来源", {"n": len(cites), "sources": sorted(srcs)})

        db_cites = sql_one(
            "SELECT COALESCE(JSON_LENGTH(citations),0) FROM chat_message "
            "WHERE run_id='%s' AND role='assistant' ORDER BY id DESC LIMIT 1;" % rid)
        chk("B11 引用落库（chat_message.citations 非空）",
            db_cites.isdigit() and int(db_cites) > 0, ">0", db_cites)

        run_status = sql_one("SELECT status FROM agent_run WHERE run_id='%s';" % rid)
        chk("B12 run 状态 SUCCEEDED（不是停在半途却记成功）",
            run_status.upper() == "SUCCEEDED", "SUCCEEDED", run_status)
    finally:
        try:
            s.delete(API + "/conversations/%s" % cid, headers=h, timeout=15)
            print("  [cleanup] 已逻辑删除测试会话 convId=%s" % cid)
        except Exception as e:
            print("  [cleanup] 删除测试会话失败（非阻断）：%s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--model", default=None,
                    help="本轮 run 的模型通道（仅本次生效；默认通道余额不足时用它绕行）")
    a = ap.parse_args()
    case_code()
    if not a.static_only:
        case_live(a.model)
    print("\n" + "=" * 64)
    print("PASS %d · FAIL %d · SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("FAILED: " + "；".join(FAIL))
        return 1
    if SKIP:
        print("SKIPPED: " + "；".join(SKIP))
        return 2
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
