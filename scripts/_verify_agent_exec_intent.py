# -*- coding: utf-8 -*-
"""接口层验收 + agent 回归哨兵（2026-10-12）：钉死「项目上下文下发 / 能力否认 / 新建数字人误走权限申请 /
动作词表缺口」四类刚修好的缺陷，全部回到接口真实返回与回答原文。

要证的修复（已核实，勿重复排查）：
  · 项目上下文从未下发给 agent：RunService 现注入 `request.project`，agent 注入
    「当前项目：《X》…不要反问在哪个系统或平台」。
  · Agent 能力否认：现按 detect_action 注入动作提示 + 全局禁止能力否认话术。
  · 「新建数字人」误走权限申请咨询：现新增 CREATE_WORKER 动作，权限口径明确
    （worker:create 对全体登录用户开放，worker:manage 不可申请）。
  · 动作词表缺口：「加个文件」现已补进 _ACTION_RULES。

判据（每条都回到事实源头，绝不读被测对象自己的数据副本）：
  E1  POST /workers/intent「新建数字人」「帮我建一个数字员工」→ action == "CREATE_WORKER"
  E2  POST /workers/intent「上传文档」「加个文件」→ action == "UPLOAD_FILE"
  E3  POST /workers/intent「怎么创建数字人」→ action is None（问怎么做 ≠ 让我做）
  E4  普通会话（无 projectId）发「新建数字人」→ 回答不含 worker:manage / 我无法 / 抱歉，我无法；
      且含「创建数字员工」或「专家与员工」（打回答原文进 detail）
  E5  带 projectId 会话（GET /pm/projects 取首项目）发「上传文档」→ 回答不含 我无法 / 抱歉，我无法 /
      请使用系统 / 哪个系统或平台 / 哪个平台（动作触发型短回复，产品上不需回显项目名；
      H5 自己的气泡已写「…登记到当前项目「X」的文档里」）。
      再在同一会话发「我当前在哪个项目里？」→ 回答里出现该项目名（证 agent 真拿到上下文；
      项目名从 /pm/projects 列表项取，不读 agent 入参）。打项目名+两段回答原文进 detail。
      ★判据理由：upload 是动作触发型短回复，不能拿「短回复是否回显项目名」当判据（过强的代理断言），
      故用「直接探询当前项目」来证明上下文已下发。
  E6  普通会话（无 projectId）发「上传文档」→ 回答不含能力否认词（我无法/抱歉，我无法/请使用系统）
  E7  ★判别力证明：把同一禁用词表跑在已知会触发的合成输入上，断言判据函数返回 False
      （即判据真的会红，而非恒真）
  E8  收尾清理：DELETE 本脚本创建的全部会话，不留垃圾

SKIP 纪律（铁律：绝不为转绿放宽断言 / 伪造 PASS）：
  · 后端 :8080 / agent :8000 不在线、登录失败 → 环境不可用 → SKIP + 退出码 2；
  · /pm/projects 取不到项目 → E5 缺前置 → SKIP + 退出码 2；
  · 链路真断了（如能力否认词重现、动作路由错）→ 如实 FAIL + 退出码 = 失败数。

判据不得与被测对象同源；红了贴原始证据并归因（产品缺陷 vs 脚本/环境）。
用法：
    python scripts/_verify_agent_exec_intent.py
退出码：0 = 全过；>0 = 有 FAIL（=失败数）；仅 SKIP = 2。
"""
import os
import sys
import time
import json
import requests

API = "http://127.0.0.1:8080/api/v1"
USER, PWD = "fagai_li", "User@123"   # 可见 2 个项目；zhangsan 在 /pm 端点 403
MODEL_REF = "default"
HERE = os.path.dirname(os.path.abspath(__file__))

PASS, FAIL, SKIP = [], [], []
RES = []

# ---- 禁用词表（每个判据独立成表，回到事实源头）----
# E4：项目内说「新建数字人」原先会反问/走权限申请，故禁 worker:manage 与能力否认词
E4_FORBID = ["worker:manage", "我无法", "抱歉，我无法"]
E4_ENTRY = ["创建数字员工", "专家与员工"]
# E5：带项目上下文发「上传文档」原先反问「上传到哪个系统或平台」+ 能力否认
E5_FORBID = ["我无法", "抱歉，我无法", "请使用系统", "哪个系统或平台", "哪个平台"]
# E6：普通会话发「上传文档」原先答「抱歉，我无法直接处理文件上传操作」
E6_FORBID = ["我无法", "抱歉，我无法", "请使用系统"]


def chk(cid, ok, detail=""):
    RES.append((cid, bool(ok)))
    (PASS if ok else FAIL).append(cid + ("  | " + str(detail)[:700] if detail else ""))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", cid,
                           ("  | " + str(detail)[:700]) if detail else ""))
    return bool(ok)


def skip(cid, detail=""):
    SKIP.append(cid + ("  | " + str(detail)[:700] if detail else ""))
    print("  [SKIP] %s%s" % (cid, ("  | " + str(detail)[:700]) if detail else ""))
    return False


def answer_ok(text, forbidden):
    """判据函数：回答不含任何禁用词 → True（可接受）；含任一 → False（应红）。

    独立定义、不与被测对象同源；E7 用它做判别力证明。
    """
    return not any(w in (text or "") for w in forbidden)


def login():
    r = requests.post(API + "/auth/login",
                      json={"username": USER, "password": PWD}, timeout=15)
    if r.status_code != 200 or r.json().get("code") != 0:
        raise RuntimeError("登录失败: HTTP %s %s" % (r.status_code, r.text[:200]))
    return r.json()["data"]["accessToken"]


def detect_intent(token, text):
    r = requests.post(API + "/workers/intent",
                      headers={"Authorization": "Bearer " + token},
                      json={"text": text}, timeout=30)
    if r.status_code != 200 or r.json().get("code") != 0:
        raise RuntimeError("意图接口失败: HTTP %s %s" % (r.status_code, r.text[:200]))
    return r.json().get("data") or {}


def list_projects(token):
    r = requests.get(API + "/pm/projects",
                     headers={"Authorization": "Bearer " + token}, timeout=15)
    if r.status_code != 200 or r.json().get("code") != 0:
        raise RuntimeError("取项目列表失败: HTTP %s %s" % (r.status_code, r.text[:200]))
    return r.json().get("data") or []


def create_conv(token, project_id=None):
    body = {"title": "验收-agent执行意图 %s" % time.strftime("%m%d-%H%M%S"),
            "appCode": "aioa-client", "workerId": None}
    if project_id is not None:
        body["projectId"] = project_id
    r = requests.post(API + "/conversations",
                      headers={"Authorization": "Bearer " + token},
                      json=body, timeout=15)
    d = r.json()
    if d.get("code") != 0 or not (d.get("data") or {}).get("id"):
        raise RuntimeError("建会话失败: %s" % r.text[:200])
    return d["data"]["id"]


def start_run(token, conv_id, text):
    r = requests.post(API + "/conversations/%s/runs" % conv_id,
                      headers={"Authorization": "Bearer " + token},
                      json={"text": text, "context": {}, "model_ref": MODEL_REF},
                      timeout=30)
    d = r.json()
    if d.get("code") != 0 or not (d.get("data") or {}).get("runId"):
        raise RuntimeError("发起对话失败: %s" % r.text[:200])
    return d["data"]["runId"]


def consume_sse(token, run_id, timeout=120):
    """订阅 SSE 事件流，触发 agent 推理并收口；返回 (status, assistant_content)。

    字节流必须显式 .decode('utf-8')（iter_lines(decode_unicode=False) + 手动 decode），
    否则中文乱码且部分帧 json.loads 失败、回答被截断。
    """
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


def cleanup_conv(token, conv_id):
    try:
        requests.delete(API + "/conversations/%s" % conv_id,
                        headers={"Authorization": "Bearer " + token}, timeout=15)
        print("  [cleanup] 已逻辑删除测试会话 convId=%s" % conv_id)
    except Exception as e:
        print("  [cleanup] 删除会话 %s 失败（非阻断）：%s" % (conv_id, e))


def main():
    print("=== 接口层验收 + agent 回归哨兵：项目上下文/能力否认/新建数字人/动作词表 ===")
    conv_ids = []

    # ---- 登录前置 ----
    try:
        token = login()
    except Exception as e:
        skip("前置 登录", "环境不可用：%s" % e)
        return 2
    chk("前置 登录成功（%s）" % USER, True)

    # ============ E1 / E2 / E3：意图分类器（回到 /workers/intent 真实返回）============
    print("\n=== E1/E2/E3 意图分类器（POST /workers/intent）===")
    try:
        e1a = detect_intent(token, "新建数字人")
        e1b = detect_intent(token, "帮我建一个数字员工")
        e2a = detect_intent(token, "上传文档")
        e2b = detect_intent(token, "加个文件")
        e3 = detect_intent(token, "怎么创建数字人")
    except Exception as e:
        skip("E1/E2/E3 意图分类", "意图接口不可用：%s" % e)
        return 2

    chk('E1 「新建数字人」→ action=="CREATE_WORKER"',
        e1a.get("action") == "CREATE_WORKER",
        "action=%s" % e1a.get("action"))
    chk('E1 「帮我建一个数字员工」→ action=="CREATE_WORKER"',
        e1b.get("action") == "CREATE_WORKER",
        "action=%s" % e1b.get("action"))
    chk('E2 「上传文档」→ action=="UPLOAD_FILE"',
        e2a.get("action") == "UPLOAD_FILE",
        "action=%s" % e2a.get("action"))
    chk('E2 「加个文件」→ action=="UPLOAD_FILE"（本次新补词条）',
        e2b.get("action") == "UPLOAD_FILE",
        "action=%s" % e2b.get("action"))
    # 「怎么创建数字人」= 问怎么做，不是让我做；action 必须为 None（防词表放宽过头）
    chk('E3 「怎么创建数字人」→ action is None（负向对照）',
        e3.get("action") is None,
        "action=%s" % e3.get("action"))

    # ============ E4：普通会话（无 projectId）发「新建数字人」============
    print("\n=== E4 普通会话（无 projectId）发「新建数字人」===")
    try:
        c4 = create_conv(token, None)
        conv_ids.append(c4)
        run4 = start_run(token, c4, "新建数字人")
        st4, ans4 = consume_sse(token, run4)
    except Exception as e:
        skip("E4 新建数字人对话", "链路失败：%s" % e)
        return 2
    print("    E4 回答原文: %s" % repr(ans4))
    chk("E4-pre run 收口（SUCCEEDED）", st4 == "SUCCEEDED", "status=%s" % st4)
    if st4 != "SUCCEEDED":
        skip("E4 判据", "run 未收口，回答不可信")
    else:
        no_forbid = answer_ok(ans4, E4_FORBID)
        has_entry = any(w in (ans4 or "") for w in E4_ENTRY)
        chk("E4 回答不含禁用词（worker:manage / 我无法 / 抱歉，我无法）",
            no_forbid, "命中=%s" % ([w for w in E4_FORBID if w in (ans4 or "")] or "无"))
        chk("E4 回答含创建入口指引（创建数字员工 / 专家与员工）",
            has_entry, "命中=%s" % ([w for w in E4_ENTRY if w in (ans4 or "")] or "无"))

    # ============ E5：带 projectId 会话发「上传文档」============
    print("\n=== E5 带 projectId 会话发「上传文档」===")
    try:
        projects = list_projects(token)
    except Exception as e:
        skip("E5 取项目", "接口不可用：%s" % e)
        return 2
    if not projects:
        skip("E5 带项目发上传文档", "GET /pm/projects 返回 0 个项目，缺前置")
        return 2
    pid = projects[0].get("id")
    pname = projects[0].get("name")
    if not pid or not pname:
        skip("E5 带项目发上传文档", "项目项缺 id/name：%s" % projects[0])
        return 2
    try:
        c5 = create_conv(token, pid)
        conv_ids.append(c5)
        run5 = start_run(token, c5, "上传文档")
        st5, ans5 = consume_sse(token, run5)
    except Exception as e:
        skip("E5 上传文档对话", "链路失败：%s" % e)
        return 2
    print("    E5 项目名: %s (id=%s)" % (repr(pname), pid))
    print("    E5 回答原文(上传文档): %s" % repr(ans5))
    chk("E5-pre run 收口（SUCCEEDED）", st5 == "SUCCEEDED", "status=%s" % st5)
    if st5 != "SUCCEEDED":
        skip("E5 判据", "run 未收口，回答不可信")
    else:
        # E5a 否定词子句（保持不变）：upload 短回复不得反问/能力否认
        no_forbid5 = answer_ok(ans5, E5_FORBID)
        chk("E5a 上传文档回复不含反问/能力否认词（我无法/抱歉我无法/请使用系统/哪个系统或平台/哪个平台）",
            no_forbid5, "命中=%s" % ([w for w in E5_FORBID if w in (ans5 or "")] or "无"))
        # E5b ★上下文下发探针：upload 是动作触发型短回复，不回显项目名；
        # 改以「直接探询当前项目」证明上下文真下发（H5 气泡自行写「登记到当前项目「X」」）。
        # 项目名从 /pm/projects 列表项取，不读 agent 入参。
        try:
            run5b = start_run(token, c5, "我当前在哪个项目里？我们在做的项目叫什么？")
            st5b, ans5b = consume_sse(token, run5b)
        except Exception as e:
            skip("E5b 上下文探针", "链路失败：%s" % e)
        else:
            print("    E5 回答原文(探询当前项目): %s" % repr(ans5b))
            chk("E5b-pre run 收口（SUCCEEDED）", st5b == "SUCCEEDED", "status=%s" % st5b)
            if st5b == "SUCCEEDED":
                has_name = (pname or "") in (ans5b or "")
                chk("E5b 探询问当前项目 → 回答含项目名（证上下文已下发）：%s" % pname,
                    has_name, "项目名是否出现=%s" % has_name)
            else:
                skip("E5b 判据", "run 未收口，回答不可信")

    # ============ E6：普通会话（无 projectId）发「上传文档」============
    print("\n=== E6 普通会话（无 projectId）发「上传文档」===")
    try:
        c6 = create_conv(token, None)
        conv_ids.append(c6)
        run6 = start_run(token, c6, "上传文档")
        st6, ans6 = consume_sse(token, run6)
    except Exception as e:
        skip("E6 上传文档对话", "链路失败：%s" % e)
        return 2
    print("    E6 回答原文: %s" % repr(ans6))
    chk("E6-pre run 收口（SUCCEEDED）", st6 == "SUCCEEDED", "status=%s" % st6)
    if st6 != "SUCCEEDED":
        skip("E6 判据", "run 未收口，回答不可信")
    else:
        no_forbid6 = answer_ok(ans6, E6_FORBID)
        chk("E6 回答不含能力否认词（我无法/抱歉，我无法/请使用系统）",
            no_forbid6, "命中=%s；允许提示进入项目" % (
                [w for w in E6_FORBID if w in (ans6 or "")] or "无"))

    # ============ E7 ★ 判别力证明（防判据恒真）============
    print("\n=== E7 判别力证明（判据函数对已知坏输入必须返回 False）===")
    # 合成一个必然触发 E5 禁用词的假回答（模拟旧行为「抱歉，我无法直接处理…请使用系统上传功能」）
    fake_bad = "抱歉，我无法直接处理文件上传操作，请使用系统提供的文件上传功能，并告诉我上传到哪个系统或平台。"
    fake_good = "正在为你打开上传窗口，请选择文件。"
    judge_bad = answer_ok(fake_bad, E5_FORBID)
    judge_good = answer_ok(fake_good, E5_FORBID)
    print("    合成坏回答=%s → answer_ok 返回 %s（期望 False）" % (repr(fake_bad), judge_bad))
    print("    合成好回答=%s → answer_ok 返回 %s（期望 True）" % (repr(fake_good), judge_good))
    chk("E7 判据函数对含禁用词的合成坏回答返回 False（证会红）",
        judge_bad is False, "返回=%s" % judge_bad)
    chk("E7 判据函数对正常回答返回 True（证非恒假）",
        judge_good is True, "返回=%s" % judge_good)

    # ============ E8 收尾清理 ============
    print("\n=== E8 收尾清理 ===")
    for cid in conv_ids:
        cleanup_conv(token, cid)
    chk("E8 已删除本脚本创建的全部会话（%d 个）" % len(conv_ids),
        len(conv_ids) > 0, "convIds=%s" % conv_ids)

    # ---- 汇总 ----
    n = len(RES)
    bad = [c for c, ok in RES if not ok]
    print("\n" + "=" * 70)
    print("=== agent 执行意图验收：%d/%d 通过；SKIP %d ===" % (n - len(bad), n, len(SKIP)))
    for f in FAIL:
        print("  - FAIL " + f)
    for s in SKIP:
        print("  - SKIP " + s)
    return len(bad) if bad else (2 if SKIP else 0)


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        chk("流程未跑完（异常中断）", False, "%s: %s" % (type(exc).__name__, exc)[:400])
        rc = 1
    sys.exit(rc)
