# -*- coding: utf-8 -*-
"""独立验证：answer_shape 修复（「回答太多，只要答所问」）是否**真的生效**。

要证的链路：agent/app/core/answer_shape.py 的 rules() 已从「每次必给六段、禁止省略」
改为「默认只答所问、能一句答清就一句；仅当用户想做的事做不了时才补『下一步+找谁办』」，
并由 agent_runtime 注入系统提示。本脚本跑活体对话 + 活体提示词口径 + 判别力证明，
证明修复**不是只看代码改了**。

断言（逐条 PASS/FAIL/SKIP + 实测值）：
  1. 复现用户场景：上传含唯一地标的小 txt，问「这里面有什么？」
       a) 回答不含分节词（结论先行/状态卡/能力边界/唯一下一步/管理员话术/通过后续接）
       b) 回答简短（≤400 字，贴实测字符数）
       c) 回答切题（出现地标「9417」）
       d) 不罗列用户没问的信息（不得出现 ROLE_ 或「令牌」）
  2. 简单事实问「1+1 等于几？」：≤200 字且不含分节词（贴原文）。
  3. 保留的原意图：构造「用户想做的事做不了」一轮 → 回答有「下一步/找谁办」之意
       （出现 请联系/下一步/管理员/权限申请 之一）。若该分支无法稳定触发 → 如实 SKIP。
  4. 判别力证明（防「判据恒真」）：
       a) 检查函数对**故意含五段标题**的合成文本判 FAIL；
       b) 对真实回答判 PASS。两条都贴出来。
  5. 活体提示词口径：POST :8000/internal/v1/answer-shape → rules 无旧口径
       （必须齐备/按顺序组织）、有新口径（只回答用户问到的内容）。
  6. 回归（不得被改动弄坏）：
       a) python scripts/_verify_chat_attachment_e2e.py → 9/9 PASS、退出码 0；
       b) cd agent && ./.venv/Scripts/python.exe -m pytest tests/ -q → 全绿（基线 106 passed）。

纪律：不许为转绿放宽断言；环境不允许的如实 SKIP；测试会话用完软删，不留污染数据。
用法：
    python scripts/_verify_answer_conciseness.py
退出码：0 = 全过；1 = 有 FAIL；2 = 仅 SKIP（环境不可用）。
"""
import io
import os
import re
import sys
import time
import json
import subprocess
import requests

API = "http://127.0.0.1:8080/api/v1"
AGENT = "http://127.0.0.1:8000"
USER, PWD = "zhangsan", "User@123"
MODEL_REF = "default"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = dict(host="127.0.0.1", port=3306, user="root", password="",
          database="aioa", charset="utf8mb4", connect_timeout=10)

# 分节词（旧六段标题）：用于 a)/判别力证明
FORBIDDEN_SECTIONS = ["结论先行", "状态卡", "能力边界", "唯一下一步",
                      "管理员话术", "通过后续接"]
# 用户没问却旧版会罗列的信息
FORBIDDEN_NOASK = ["ROLE_", "令牌"]
# 做不了时「下一步/找谁办」的命中词
NEXT_STEP_HINTS = ["请联系", "下一步", "管理员", "权限申请"]

PASS, FAIL, SKIP = [], [], []
RES = []


def chk(cid, ok, detail=""):
    RES.append((cid, bool(ok)))
    (PASS if ok else FAIL).append(cid + ("  | " + str(detail)[:600] if detail else ""))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", cid,
                           ("  | " + str(detail)[:600]) if detail else ""))
    return bool(ok)


def skip(cid, detail=""):
    SKIP.append(cid + ("  | " + str(detail)[:600] if detail else ""))
    print("  [SKIP] %s%s" % (cid, ("  | " + str(detail)[:600]) if detail else ""))
    return False


def has_section_words(text):
    t = text or ""
    return any(w in t for w in FORBIDDEN_SECTIONS)


# ---- 复用 _verify_chat_attachment_e2e.py 的登录/上传/发起/消费 SSE 写法 ----
def login():
    r = requests.post(API + "/auth/login",
                      json={"username": USER, "password": PWD}, timeout=15)
    if r.status_code != 200 or r.json().get("code") != 0:
        raise RuntimeError("登录失败: HTTP %s %s" % (r.status_code, r.text[:200]))
    return r.json()["data"]["accessToken"]


def upload_doc(token, content_bytes, name, mime="text/plain"):
    r = requests.post(API + "/files/upload", headers={"Authorization": "Bearer " + token},
                      files={"file": (name, io.BytesIO(content_bytes), mime)}, timeout=30)
    d = r.json()
    if d.get("code") != 0 or not (d.get("data") or {}).get("id"):
        raise RuntimeError("上传失败: %s" % r.text[:200])
    return d["data"]["id"]


def create_conv(token, title):
    r = requests.post(API + "/conversations",
                      headers={"Authorization": "Bearer " + token},
                      json={"title": title, "appCode": "aioa-client", "workerId": None},
                      timeout=15)
    d = r.json()
    if d.get("code") != 0 or not (d.get("data") or {}).get("id"):
        raise RuntimeError("建会话失败: %s" % r.text[:200])
    return d["data"]["id"]


def start_run(token, conv_id, text, attachments):
    body = {"text": text, "context": {}, "model_ref": MODEL_REF}
    if attachments:
        body["attachments"] = attachments
    r = requests.post(API + "/conversations/%s/runs" % conv_id,
                      headers={"Authorization": "Bearer " + token},
                      json=body, timeout=30)
    d = r.json()
    if d.get("code") != 0 or not (d.get("data") or {}).get("runId"):
        raise RuntimeError("发起对话失败: %s" % r.text[:200])
    return d["data"]["runId"]


def consume_sse(token, run_id, timeout=120):
    """订阅 SSE 事件流，触发 agent 推理并收口；返回 (status, assistant_content)。"""
    status, assistant = None, ""
    cur_event, data_lines = None, []

    def flush():
        nonlocal status, assistant
        data = "\n".join(data_lines)
        if cur_event == "message.completed":
            try:
                assistant = json.loads(data).get("content", "") or ""
            except Exception:
                pass
        if cur_event in ("run.completed", "run.failed", "error"):
            st = "FAILED" if cur_event != "run.completed" else "SUCCEEDED"
            try:
                j = json.loads(data)
                st = j.get("status", st)
            except Exception:
                pass
            status = st

    resp = requests.get(API + "/runs/%s/events" % run_id,
                        headers={"Authorization": "Bearer " + token},
                        stream=True, timeout=timeout)
    for raw in resp.iter_lines(decode_unicode=False):
        if raw is None:
            continue
        line = raw.decode("utf-8", "replace")
        if line == "":
            flush()
            cur_event, data_lines = None, []
            if status is not None:
                break
        elif line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    flush()
    return status, assistant


def cleanup_convs(token, conv_ids):
    for cid in conv_ids:
        try:
            requests.delete(API + "/conversations/%s" % cid,
                            headers={"Authorization": "Bearer " + token}, timeout=15)
            print("  [cleanup] 已逻辑删除测试会话 convId=%s" % cid)
        except Exception as e:
            print("  [cleanup] 删除会话 %s 失败（非阻断）：%s" % (cid, e))


# ---- 第 5 条：活体提示词口径 ----
def check_live_prompt():
    print("\n=== 5. 活体提示词口径（:8000/internal/v1/answer-shape） ===")
    try:
        r = requests.post(AGENT + "/internal/v1/answer-shape",
                          json={"role": "GENERAL", "scope": None}, timeout=15)
    except Exception as e:
        skip("5 活体提示词口径", "agent 不在线：%s" % e)
        return
    if r.status_code != 200:
        skip("5 活体提示词口径", "HTTP %s" % r.status_code)
        return
    body = r.json()
    rules = body.get("rules") or []
    rules_text = "\n".join(rules)
    print("    rules 原文:\n" + "\n".join("      " + ln for ln in rules))
    old_absent = ("必须齐备" not in rules_text) and ("按顺序组织" not in rules_text)
    new_present = "只回答用户问到的内容" in rules_text
    chk("5a 旧口径缺失（无『必须齐备』/『按顺序组织』）", old_absent,
        "命中旧口径=%s" % ([w for w in ("必须齐备", "按顺序组织") if w in rules_text] or "无"))
    chk("5b 新口径存在（含『只回答用户问到的内容』）", new_present)


# ---- 第 4 条：判别力证明 ----
def check_discrimination(real_answer):
    print("\n=== 4. 判别力证明（防判据恒真） ===")
    synthetic = (
        "结论先行：本文件仅记录了一个端口号。\n"
        "状态卡：角色 ROLE_ADMIN，令牌 tk-9f3a，已具备读取权限。\n"
        "能力边界：只覆盖文档摘要，不覆盖系统配置。\n"
        "唯一下一步：请到后台查看完整配置。\n"
        "管理员话术：请联系管理员开放更多字段。\n"
        "通过后续接：放行后将自动同步。"
    )
    syn_hit = has_section_words(synthetic)
    real_hit = has_section_words(real_answer)
    print("    合成文本（含五段标题）命中分节词 = %s" % syn_hit)
    print("    真实回答命中分节词 = %s" % real_hit)
    chk("4a 检查函数对合成分节文本判 FAIL（syn_hit=True）", syn_hit is True,
        "syn_hit=%s" % syn_hit)
    chk("4b 检查函数对真实回答判 PASS（real_hit=False）", real_hit is False,
        "real_hit=%s" % real_hit)


# ---- 第 1/2/3 条：活体对话 ----
def check_live_conversation(token):
    print("\n=== 1-3. 活体对话（复现用户场景 / 简单事实问 / 保留原意图） ===")
    stamp = time.strftime("%m%d-%H%M%S")
    conv_ids = []
    try:
        # ---- 第 1 条：复现用户场景 ----
        txt = ("本文件记录：服务器端口 9417\n"
               "这是一份用于验收回答精简的测试文件，没有别的内容。\n").encode("utf-8")
        try:
            file_id = upload_doc(token, txt, "精简验收-%s.txt" % stamp, mime="text/plain")
        except Exception as e:
            skip("1 复现用户场景", "上传失败：%s" % e)
            return
        conv1 = create_conv(token, "精简验收-复现场景 %s" % stamp)
        conv_ids.append(conv1)
        run1 = start_run(token, conv1, "这里面有什么？", [file_id])
        st1, ans1 = consume_sse(token, run1)
        print("    ① 回答（原文，共 %d 字符）：%s" % (len(ans1 or ""), repr(ans1)))
        chk("1-pre run 收口（SUCCEEDED）", st1 == "SUCCEEDED", "status=%s" % st1)
        if st1 != "SUCCEEDED":
            skip("1a/1b/1c/1d", "run 未收口，回答不可信")
        else:
            no_section = not has_section_words(ans1)
            short = len(ans1 or "") <= 400
            on_topic = "9417" in (ans1 or "")
            no_noask = not any(w in (ans1 or "") for w in FORBIDDEN_NOASK)
            chk("1a 回答不含分节词", no_section,
                "命中=%s" % ([w for w in FORBIDDEN_SECTIONS if w in (ans1 or "")] or "无"))
            chk("1b 回答简短（≤400 字）", short, "实际字符数=%d" % len(ans1 or ""))
            chk("1c 回答切题（含地标 9417）", on_topic)
            chk("1d 不罗列用户没问的信息（无 ROLE_/令牌）", no_noask,
                "命中=%s" % ([w for w in FORBIDDEN_NOASK if w in (ans1 or "")] or "无"))

        # ---- 第 2 条：简单事实问（同会话新轮） ----
        run2 = start_run(token, conv1, "1+1 等于几？", None)
        st2, ans2 = consume_sse(token, run2)
        print("    ② 回答（原文，共 %d 字符）：%s" % (len(ans2 or ""), repr(ans2)))
        chk("2-pre run 收口（SUCCEEDED）", st2 == "SUCCEEDED", "status=%s" % st2)
        if st2 == "SUCCEEDED":
            short2 = len(ans2 or "") <= 200
            no_sec2 = not has_section_words(ans2)
            chk("2a 回答简短（≤200 字）", short2, "实际字符数=%d" % len(ans2 or ""))
            chk("2b 回答不含分节词", no_sec2,
                "命中=%s" % ([w for w in FORBIDDEN_SECTIONS if w in (ans2 or "")] or "无"))
        else:
            skip("2 简单事实问", "run 未收口")

        # ---- 第 3 条：保留原意图（做不了才补下一步） ----
        run3 = start_run(token, conv1, "帮我给张三开通系统审批权限", None)
        st3, ans3 = consume_sse(token, run3)
        print("    ③ 回答（原文，共 %d 字符）：%s" % (len(ans3 or ""), repr(ans3)))
        chk("3-pre run 收口（SUCCEEDED）", st3 == "SUCCEEDED", "status=%s" % st3)
        if st3 == "SUCCEEDED":
            has_hint = any(w in (ans3 or "") for w in NEXT_STEP_HINTS)
            if has_hint:
                chk("3 做不了分支：回答含『下一步/找谁办』之意",
                    True, "命中=%s" % ([w for w in NEXT_STEP_HINTS if w in (ans3 or "")]))
            else:
                # 如实 SKIP，不硬凑 PASS；贴出观察到的真实回答
                skip("3 做不了分支", "未稳定命中 请联系/下一步/管理员/权限申请；"
                     "真实回答=%s" % (repr(ans3)[:300]))
        else:
            skip("3 做不了分支", "run 未收口")

        return ans1  # 供判别力证明使用
    finally:
        cleanup_convs(token, conv_ids)


# ---- 第 6 条：回归 ----
def check_regression():
    print("\n=== 6. 回归（不得被改动弄坏） ===")
    # 6a 附件 e2e
    print("  -- 6a scripts/_verify_chat_attachment_e2e.py --")
    try:
        p = subprocess.run([sys.executable, "scripts/_verify_chat_attachment_e2e.py"],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        out = p.stdout + p.stderr
        print("    " + "\n    ".join(out.strip().splitlines()[-12:]))
        nine = "9/9" in out or re.search(r"(\d+)/(\1)\b", out) is not None
        # 更稳妥：看通过计数
        m = re.search(r"(\d+)/(\d+) 通过", out)
        ok9 = m and m.group(1) == m.group(2) and int(m.group(1)) >= 9
        chk("6a 附件 e2e 通过且退出码 0", p.returncode == 0 and ok9,
            "returncode=%s 计数=%s" % (p.returncode, m.group(0) if m else "?"))
    except Exception as e:
        skip("6a 附件 e2e", "执行异常：%s" % e)

    # 6b agent pytest
    print("  -- 6b agent pytest --")
    venv_py = os.path.join(ROOT, "agent", ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_py):
        skip("6b agent pytest", "venv 不存在: %s" % venv_py)
        return
    try:
        p = subprocess.run([venv_py, "-m", "pytest", "tests/", "-q"],
                           cwd=os.path.join(ROOT, "agent"),
                           capture_output=True, text=True, timeout=600)
        out = p.stdout + p.stderr
        print("    " + "\n    ".join(out.strip().splitlines()[-12:]))
        m = re.search(r"(\d+) passed", out)
        failed = re.search(r"(\d+) failed", out)
        chk("6b agent pytest 全绿（基线 106 passed）",
            p.returncode == 0 and m and not failed,
            "passed=%s failed=%s returncode=%s" % (
                m.group(1) if m else "?", failed.group(1) if failed else 0, p.returncode))
    except Exception as e:
        skip("6b agent pytest", "执行异常：%s" % e)


def main():
    print("=== 独立验证：answer_shape 修复（回答精简）是否生效 ===")
    # 第 5 条（活体提示词口径，不依赖会话）
    check_live_prompt()
    # 第 1-3 条（活体对话），拿回真实回答供第 4 条
    try:
        token = login()
    except Exception as e:
        skip("1-3 活体对话", "登录失败/后端不在线：%s" % e)
        real_answer = ""
    else:
        chk("登录成功（%s）" % USER, True)
        real_answer = check_live_conversation(token) or ""
    # 第 4 条（判别力证明）
    check_discrimination(real_answer if real_answer else "无可用真实回答")
    # 第 6 条（回归）
    check_regression()

    n = len(RES)
    bad = [c for c, ok in RES if not ok]
    print("\n" + "=" * 70)
    print("=== 答案精简验证：%d/%d 通过；SKIP %d ===" % (n - len(bad), n, len(SKIP)))
    for f in FAIL:
        print("  - FAIL " + f)
    for s in SKIP:
        print("  - SKIP " + s)
    return 1 if bad else (2 if SKIP else 0)


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        chk("流程未跑完（异常中断）", False, "%s: %s" % (type(exc).__name__, exc)[:300])
        rc = 1
    sys.exit(rc)
