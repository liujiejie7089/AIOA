# -*- coding: utf-8 -*-
"""独立验证：answer_shape 的回答口径是否**真的生效**（含「不冗长」与「严格知识库口径」两面）。

要证的链路：agent/app/core/answer_shape.py 的 rules() 生成的行为规则由 agent_runtime 注入系统提示。
本脚本跑活体对话 + 活体提示词口径 + 判别力证明，证明口径**不是只看代码改了**。

口径三次变更（全部用户反馈驱动）：
  ① 2026-10-12「每次必给六段」→「默认只答所问」（用户原话：回答太多，只要答所问）；
  ② 2026-10-12「做不了就补下一步」→「**仅限权限话题**」——答不了／超出职责／查不到数据
     一律不出现办理指引、管理员话术或下一步建议；
  ③ **2026-10-15「严格知识库口径」**——只依据本轮四类资料作答、逐维度覆盖不跳项、
     缺失项标注到具体维度、统计/对比类用表格、输出前强制自检。③ 取代 ①② 的**结构**部分，
     但**不撤**②的权限收窄，也不撤①的「不冗长」精神（由新规则 8「不得为没问到的维度凑段落」承载）。

故本脚本在**两侧**都要立断言：
  - 「不冗长」侧（①的延续，仍必须成立）：简单提问要短、不含分节词、不罗列没问的信息；
  - 「权限收窄」侧（②，仍必须成立）：权限场景**必须**有下一步/找谁办；非权限的「做不了」
    **不得**有办理指引/管理员话术/主动推销权限。
  ⚠️ ③ 的**能力面**（逐维度覆盖 / 缺失标注三态 / 表格）**不在本脚本**，见
     `scripts/_check_answer_kb_strict.py` —— 两个脚本各管一半，别互相替代。

断言（逐条 PASS/FAIL/SKIP + 实测值）：
  1. 复现用户场景：上传含唯一地标的小 txt，问「这里面有什么？」
       a) 回答不含分节词（结论先行/状态卡/能力边界/唯一下一步/管理员话术/通过后续接）
       b) 回答简短（≤400 字，贴实测字符数）
       c) 回答切题（出现地标「9417」）
       d) 不罗列用户没问的信息（不得出现 ROLE_ 或「令牌」）
  2. 简单事实问「1+1 等于几？」：≤200 字且不含分节词（贴原文）。
  3. 权限场景（**正面**）：构造「涉及权限」的一轮 → 回答须有「下一步/找谁办」之意
       （出现 管理员/权限申请/转述/放行 之一）。
     3b. 非权限「做不了」（**负向对照，本次新增**）：构造一个明显与权限无关、AI 也办不到的
       请求 → 回答**不得**出现任何办理指引/管理员话术，含「主动推销权限」的写法
       （管理员/权限申请/转述/放行/权限码/开通权限/申请权限/审批权限/办理权限）。
       若该轮并未表现为「答不了」，如实 SKIP（不硬凑），并贴出真实回答。
  4. 判别力证明（防「判据恒真」）：
       a) 检查函数对**故意含五段标题**的合成文本判 FAIL；
       b) 对真实回答判 PASS。两条都贴出来。
  5. 活体提示词口径：POST :8000/internal/v1/answer-shape → rules 无旧口径
       （必须齐备/按顺序组织/「做不了」），有**新口径**关键件（知识库暂未收录 /
       当前检索未返回相关内容 / 不得跳过任何一项 / 应答清单 / 数据来源 / 自检 / 维度层级），
       且仍含「涉及权限」+「除权限问题外」，并保留护栏「没问到的维度」。
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
# 权限场景「找谁办」的命中词：只有涉及权限时才该出现
HANDOFF_HINTS = ["管理员", "权限申请", "转述", "放行"]
# 非权限场景的禁止词：出现任一即说明办理指引/权限推销被滥用（本次口径收窄的核心判据）。
# 后五项专门拦「用户没问权限、模型却主动提议帮申请/开通权限」这一**实测出现过的残余**——
# 首版只拦 HANDOFF_HINTS，实测有 1/2 轮出现过「如果您需要开通系统审批权限…我可以为您申请」，漏网。
FORBIDDEN_HANDOFF_WHEN_NO_PERM = HANDOFF_HINTS + [
    "权限码", "开通权限", "申请权限", "审批权限", "办理权限"]
# 「答不了」的自述标记：负向对照只在确实答不了时才判定，避免判据退化成恒真
REFUSAL_HINTS = ["无法", "不能", "不支持", "办不到", "没办法", "不提供", "无权", "做不到"]


# 额度耗尽：本项目把「今日免费额度已用完」视为**环境限制**，不是回答口径的回归。
# 该异常由 start_run 抛出、由活体对话段捕获后如实记为 SKIP ——
# 铁律：环境不允许的如实 SKIP，既不伪装 PASS，也不该判成 FAIL（否则「额度用完」会被读成缺陷）。
class QuotaExhausted(RuntimeError):
    pass

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
        msg = d.get("message") or ""
        # 额度耗尽 ≠ 口径回归：单独抛出，交给活体段记 SKIP（不是 FAIL）。
        if d.get("code") == 403 and ("额度" in msg):
            raise QuotaExhausted("发起对话失败(额度耗尽): %s" % r.text[:200])
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
    old_hits = [w for w in ("必须齐备", "按顺序组织", "做不了") if w in rules_text]
    # 2026-10-15 契约变更：口径由「只答所问」改为「严格知识库口径」（见 answer_shape.rules 说明），
    # 故 5b 改钉**新**口径关键件；旧短语（只回答用户问到的内容 / 最多 3-5 条）已不是契约，不再断言。
    new_markers = ("知识库暂未收录", "当前检索未返回相关内容", "不得跳过任何一项",
                   "应答清单", "数据来源", "自检", "维度层级")
    new_missing = [m for m in new_markers if m not in rules_text]
    perm_scoped = ("涉及权限" in rules_text) and ("除权限问题外" in rules_text)
    guard = "没问到的维度" in rules_text      # 防「全覆盖」被执行成「每题都展开」
    chk("5a 旧口径缺失（无『必须齐备』/『按顺序组织』/『做不了』）", not old_hits,
        "命中旧口径=%s" % (old_hits or "无"))
    chk("5b 新口径存在（严格知识库口径关键件齐备）", not new_missing,
        "缺失=%s" % (new_missing or "无"))
    chk("5b2 保留护栏「不得为没问到的维度凑段落」", guard)
    chk("5c 触发条件已收窄到权限（含『涉及权限』『除权限问题外』）", perm_scoped,
        "涉及权限=%s 除权限问题外=%s" % ("涉及权限" in rules_text, "除权限问题外" in rules_text))


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

        # ---- 第 3 条（正面）：权限场景应补「下一步 / 找谁办」 ----
        run3 = start_run(token, conv1, "帮我给张三开通系统审批权限", None)
        st3, ans3 = consume_sse(token, run3)
        print("    ③ 权限场景回答（原文，共 %d 字符）：%s" % (len(ans3 or ""), repr(ans3)))
        chk("3-pre run 收口（SUCCEEDED）", st3 == "SUCCEEDED", "status=%s" % st3)
        if st3 == "SUCCEEDED":
            hit3 = [w for w in HANDOFF_HINTS if w in (ans3 or "")]
            chk("3 权限场景：回答含『找谁办』之意（管理员/权限申请/转述/放行）", bool(hit3),
                "命中=%s" % (hit3 or "无；真实回答=%s" % (repr(ans3)[:300])))
        else:
            skip("3 权限场景", "run 未收口")

        # ---- 第 3b 条（负向对照，本次新增）：非权限「做不了」不得出现办理指引 ----
        # 说明：禁止词只取「办理/放行」类词（管理员/权限申请/转述/放行），不取宽泛的「请联系」
        # —— 后者可能是对提问的**直接回答**（如「请联系物业」），拿来判 FAIL 会误伤正常回答。
        # 断言前提：该轮确实表现为「答不了」；若模型没答不了，则如实 SKIP，不硬凑。
        run3b = start_run(token, conv1, "帮我把这栋楼的水电费交了", None)
        st3b, ans3b = consume_sse(token, run3b)
        print("    ③b 非权限场景回答（原文，共 %d 字符）：%s" % (len(ans3b or ""), repr(ans3b)))
        chk("3b-pre run 收口（SUCCEEDED）", st3b == "SUCCEEDED", "status=%s" % st3b)
        if st3b == "SUCCEEDED":
            refused = [w for w in REFUSAL_HINTS if w in (ans3b or "")]
            bad_handoff = [w for w in FORBIDDEN_HANDOFF_WHEN_NO_PERM if w in (ans3b or "")]
            if not refused:
                # 该轮并未表现为「答不了」→ 断言前提不成立，如实 SKIP（不硬凑）
                skip("3b 非权限不做指引", "该轮未表现为答不了，无法判定；真实回答=%s"
                     % (repr(ans3b)[:300]))
            else:
                chk("3b 非权限『做不了』不得出现办理指引/管理员话术（命中禁止词即 FAIL）",
                    not bad_handoff,
                    "命中禁止词=%s；真实回答=%s" % (bad_handoff or "无", repr(ans3b)[:300]))
        else:
            skip("3b 非权限不做指引", "run 未收口")

        return ans1  # 供判别力证明使用
    except QuotaExhausted as e:
        # 环境额度限制：1/2/3/3b 全部无法判定 —— 如实 SKIP，不硬凑、不判 FAIL。
        skip("1/2/3/3b 活体对话",
             "%s —— 这是**环境额度限制**（非口径回归）；口径契约 5a–5c 已独立验证，"
             "换一个有额度的账号或次日再跑本段即可" % e)
        return ""
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
        if p.returncode == 2:
            # 子脚本按纪律以「环境不可用」SKIP（退出码 2）—— 不是附件链路回归，如实 SKIP。
            skip("6a 附件 e2e", "子脚本记 SKIP（退出码 2，环境不可用；常见原因＝账号额度耗尽）")
        else:
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
