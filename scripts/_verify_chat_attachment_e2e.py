# -*- coding: utf-8 -*-
"""H5 对话「＋」上传文档 → AI 真能读到内容的**端到端**哨兵（2026-10-12）。

要证明的链路（用户最终举证）：
    用户在 H5 对话点「＋」上传文档 → 提一轮问题（带 attachments=[fileId]）
    → 后端把文档解析为「参考快照」落 chat_message.attachments（JSON，nullable）
    → 该快照结构化下发 agent（attachment_docs）→ AI 的回答真的引用了文档里的地标。

背景（已核实，勿重复排查）：
  · 后端 :8080 与 agent :8000 于 19:17 用新构建重启；Flyway 已执行 V82；
    chat_message.attachments 列已存在；agent 活体 /openapi.json 已含 attachment_docs。
  · 修复前三者全是旧实例（jar 14:34 构建、agent 14:36 起且无 --reload），
    导致 AI 看不到文档——本脚本就是要证「现在这条链路端到端成立」。

判据（每条都回到事实源头，绝不读被测对象自己的数据副本）：
  P1  登录成功（拿 token）。
  P2  上传唯一测试文档 → fileId 非空（落 SysFile）。
  P3  建会话 → convId 非空。
  A3 ★主判据（回到库）：带 attachments=[fileId] 提一轮 → 查 chat_message 中
        run_id==runId1 且 role='user' 的行，断言 attachments 列**非 NULL**，
        且其 JSON 文本含地标「紫罗兰-7391」（证明文档内容真被解析并落库，不是空壳）。
  A4  从判据（回答）：该轮 assistant 回答里出现「紫罗兰-7391」或「880」。
  A5 ★负向对照：同一会话再发一轮**不带** attachments 的同样提问 →
        run_id==runId2 的 user 行 attachments 必须为 NULL，
        证明 A3 不是「列恒被填」的假阳性（判据的区分力）。

SKIP 纪律（铁律：绝不为转绿放宽断言 / 伪造 PASS）：
  · 后端/agent 不在线、登录失败、上传/建会话失败 → 视为环境不可用 → SKIP + 退出码 2；
  · model_ref 若必须给具体模型却拿不到 → SKIP + 写明原因；
  · 链路真断了（如 AI 没读到地标）→ 如实 FAIL + 退出码 1。

清理：跑完逻辑删除测试会话（DELETE /conversations/{id}，与产品同源软删），不自留垃圾。

用法：
    python scripts/_verify_chat_attachment_e2e.py
退出码：0 = 全过；1 = 有 FAIL（链路真断）；2 = 仅 SKIP（环境不可用）。
"""
import io
import os
import sys
import time
import json
import pymysql
import requests

API = "http://127.0.0.1:8080/api/v1"
USER, PWD = "zhangsan", "User@123"
# H5 默认模型（user-client/index.html:2482 state.model = 'default'），
# 经 /conversations/{id}/runs 透传给 agent 选择 provider。实测 'default' 可用。
MODEL_REF = "default"
HERE = os.path.dirname(os.path.abspath(__file__))
DB = dict(host="127.0.0.1", port=3306, user="root", password="",
          database="aioa", charset="utf8mb4", connect_timeout=10)

# 唯一地标：只有本脚本生成的文档才知道，AI 若回答里出现即证明真读到了文档。
LANDMARK = "本文件的暗号是 紫罗兰-7391，审批上限 880 万元。"

PASS, FAIL, SKIP = [], [], []
RES = []


# 额度耗尽：属**环境限制**，不是附件链路缺陷。由 start_run 抛出、main 捕获后记 SKIP（退出码 2）——
# 否则「账号今日免费额度用完」会被读成「附件读文功能坏了」（本项目实测过的错误归因）。
class QuotaExhausted(RuntimeError):
    pass


def chk(cid, ok, detail=""):
    RES.append((cid, bool(ok)))
    (PASS if ok else FAIL).append(cid + ("  | " + str(detail)[:500] if detail else ""))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", cid,
                           ("  | " + str(detail)[:500]) if detail else ""))
    return bool(ok)


def skip(cid, detail=""):
    SKIP.append(cid + ("  | " + str(detail)[:500] if detail else ""))
    print("  [SKIP] %s%s" % (cid, ("  | " + str(detail)[:500]) if detail else ""))


def login():
    r = requests.post(API + "/auth/login",
                      json={"username": USER, "password": PWD}, timeout=15)
    if r.status_code != 200 or r.json().get("code") != 0:
        raise RuntimeError("登录失败: HTTP %s %s" % (r.status_code, r.text[:200]))
    return r.json()["data"]["accessToken"]


def upload_doc(token, content_bytes, name):
    r = requests.post(API + "/files/upload", headers={"Authorization": "Bearer " + token},
                      files={"file": (name, io.BytesIO(content_bytes), "text/markdown")},
                      timeout=30)
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
        # 额度耗尽单独抛出 ⇒ 环境限制，记 SKIP，不判 FAIL。
        if d.get("code") == 403 and ("额度" in msg):
            raise QuotaExhausted("发起对话失败(额度耗尽): %s" % r.text[:200])
        raise RuntimeError("发起对话失败: %s" % r.text[:200])
    return d["data"]["runId"]


def consume_sse(token, run_id, timeout=90):
    """订阅 SSE 事件流，触发 agent 推理并收口；返回 (status, assistant_content)。

    SSE 帧按行：event: <name> / data: <json> / 空行分隔。run.completed / run.failed /
    error 为终态，见到即停（避免被心跳 ping 帧挂住）。原始字节按 UTF-8 解码，
    规避 iter_lines 默认 latin-1 导致的乱码。
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


def db_attachments_of_run(run_id):
    db = pymysql.connect(**DB)
    try:
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute(
            "SELECT id, role, attachments FROM chat_message "
            "WHERE run_id=%s AND role='user' ORDER BY id DESC LIMIT 1", (run_id,))
        return cur.fetchone()
    finally:
        db.close()


def db_user_row_exists(run_id):
    db = pymysql.connect(**DB)
    try:
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM chat_message WHERE run_id=%s AND role='user'",
                    (run_id,))
        return (cur.fetchone() or (0,))[0] > 0
    finally:
        db.close()


def to_text(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).decode("utf-8", "replace")
    return str(val)


def main():
    print("=== H5 对话「＋」上传文档 → AI 读文 端到端验证 ===")
    stamp = time.strftime("%m%d-%H%M%S")

    # ---- P1 登录 ----
    try:
        token = login()
    except Exception as e:
        skip("P1 登录", "环境不可用：%s" % e)
        return 2
    chk("P1 登录成功（%s）" % USER, True)

    # ---- P2 上传唯一文档 ----
    try:
        doc = ("验收唯一文档（请勿手改）。\n" + LANDMARK +
               "\n其余为无关内容，仅用于确认模型确实读到了这份被上传的文件。\n").encode("utf-8")
        file_id = upload_doc(token, doc, "验收附件-%s.md" % stamp)
    except Exception as e:
        skip("P2 上传文档", "环境/接口不可用：%s" % e)
        return 2
    if not chk("P2 唯一文档上传成功且拿到 fileId", file_id is not None, "fileId=%s" % file_id):
        skip("P3/A3/A4/A5", "无 fileId，链路无法进行")
        return 2

    # ---- P3 建会话 ----
    try:
        conv_id = create_conv(token, "验收-附件读文E2E %s" % stamp)
    except Exception as e:
        skip("P3 建会话", "环境/接口不可用：%s" % e)
        return 2
    chk("P3 建会话成功", conv_id is not None, "convId=%s" % conv_id)

    q = "这个文件的暗号是什么？审批上限多少？"
    try:
        # ---- A3 主判据：带附件提一轮 ----
        run_id1 = start_run(token, conv_id, q, [file_id])
        status1, answer1 = consume_sse(token, run_id1)
        chk("A3a 带附件 run 收口（SUCCEEDED）", status1 == "SUCCEEDED",
            "runId=%s status=%s" % (run_id1, status1))

        row1 = db_attachments_of_run(run_id1)
        raw1 = to_text(row1["attachments"]) if row1 else None
        ok_nonnull = row1 is not None and raw1 is not None and raw1 != "null"
        ok_landmark = (raw1 or "").find("紫罗兰-7391") >= 0
        chk("A3 ★主判据：该轮 user 行 attachments 列非 NULL", ok_nonnull,
            "attachments 原文片段=%s" % ((raw1 or "NULL")[:200]))
        chk("A3b ★主判据：attachments JSON 文本含地标「紫罗兰-7391」（文档真被解析落库）",
            ok_landmark, "attachments 原文片段=%s" % ((raw1 or "")[:200]))

        # ---- A4 从判据：AI 回答引用地标 ----
        ok_answer = ("紫罗兰-7391" in (answer1 or "")) or ("880" in (answer1 or ""))
        chk("A4 从判据：assistant 回答出现「紫罗兰-7391」或「880」",
            ok_answer, "assistant 回答片段=%s" % ((answer1 or "")[:200]))

        # ---- A5 负向对照：不带附件再发一轮 ----
        run_id2 = start_run(token, conv_id, q, None)
        status2, _ = consume_sse(token, run_id2)
        row2 = db_attachments_of_run(run_id2)
        raw2 = to_text(row2["attachments"]) if row2 else None
        ok_exists = db_user_row_exists(run_id2)
        chk("A5a 负向轮 user 行存在（对照有效）", ok_exists, "runId=%s" % run_id2)
        chk("A5 ★负向对照：不带附件的 user 行 attachments 必须为 NULL（证 A3 非恒填）",
            ok_exists and raw2 is None, "attachments=%s" % ("NULL" if raw2 is None else raw2[:120]))

    except QuotaExhausted as e:
        # 额度耗尽：A3/A4/A5 无法判定 —— 如实 SKIP（退出码 2），不判 FAIL、不伪装 PASS。
        skip("A3/A4/A5 附件读文判据",
             "%s —— **环境额度限制**（非链路缺陷）；换一个有额度的账号或次日再跑" % e)
    finally:
        # 自净：逻辑删除测试会话（与产品同源软删），不污染回归环境
        try:
            requests.delete(API + "/conversations/%s" % conv_id,
                            headers={"Authorization": "Bearer " + token}, timeout=15)
            print("  [cleanup] 已逻辑删除测试会话 convId=%s" % conv_id)
        except Exception as e:
            print("  [cleanup] 删除测试会话失败（非阻断）：%s" % e)

    n = len(RES)
    bad = [c for c, ok in RES if not ok]
    print("\n" + "=" * 70)
    print("=== 附件读文 E2E：%d/%d 通过；SKIP %d ===" % (n - len(bad), n, len(SKIP)))
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
