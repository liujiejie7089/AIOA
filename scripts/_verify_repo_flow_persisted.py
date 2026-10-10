# -*- coding: utf-8 -*-
"""代码仓库全流程「数据是否真的落库」核对器。

判据必须回到**事实源头（库）**，而不是读接口/界面自己的副本：
接口返回 200 只证明这一次调用成功，不证明数据落了库。

用法：
    python scripts/_verify_repo_flow_persisted.py [--tenant 62]

判据（全部按关系式，不写死条数）：
  R1 gitee_account   该租户存在已有 login 的绑定行（OAuth 绑定真的落了库）
  R2 gitee_project   存在本租户项目行，且 gitee_owner/gitee_repo/default_branch 已回写（建仓结果落库）
  R3 gitee_repo_member 存在成员行（成员同步落库），含 source 取值
  R4 gitee_event     存在事件行（Webhook 接收落库），event_type 覆盖 PUSH
  R5 gitee_commit    存在提交行（网页上传 / 本地 push 双路落库）
  R6 gitee_task      存在任务行（异步队列落库），status 取值分布
  R7 落库时间在本次运行窗口内（received_at / updated_at 晚于 --since）

退出码：0 = 全过；1 = 有判据不满足（并打印实际值）。
"""
import argparse
import sys

import pymysql

DB = dict(host="127.0.0.1", port=3306, user="root", password="",
          database="aioa", charset="utf8mb4")

PASS, FAIL = [], []


def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  | " + str(detail)[:300]) if detail else ""))
    return bool(cond)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=int, default=62)
    ap.add_argument("--since", default="2026-10-10 17:00:00")
    args = ap.parse_args()
    tid = args.tenant

    c = pymysql.connect(**DB)
    cur = c.cursor(pymysql.cursors.DictCursor)

    print("=" * 70)
    print("代码仓库全流程 —— 落库核对（tenant_id=%s）" % tid)
    print("=" * 70)

    cur.execute("""SELECT COUNT(*) n, COUNT(DISTINCT gitee_username) du,
                          SUM(gitee_username IS NOT NULL AND gitee_username <> '') with_login
                   FROM gitee_account WHERE tenant_id=%s""", (tid,))
    r = cur.fetchone()
    chk("R1 gitee_account：存在已绑定 Gitee 登录名的账号行", r["with_login"] and r["with_login"] > 0, r)

    cur.execute("""SELECT id,name,status,gitee_owner,gitee_repo,gitee_repo_id,
                          default_branch,gitee_html_url
                   FROM gitee_project WHERE tenant_id=%s ORDER BY id DESC LIMIT 5""", (tid,))
    rows = cur.fetchall()
    chk("R2a gitee_project：本租户有项目行", len(rows) > 0, len(rows))
    done = [x for x in rows if x["gitee_repo"] and x["gitee_owner"]]
    chk("R2b 建仓结果已回写（gitee_owner + gitee_repo 非空）", len(done) > 0, done[:2])
    chk("R2c 默认分支已回写（读写文件可定位分支）",
        any(x["default_branch"] for x in rows), [x["default_branch"] for x in rows])

    cur.execute("""SELECT COUNT(*) n, SUM(source='GITEE') gitee_src
                   FROM gitee_repo_member WHERE tenant_id=%s""", (tid,))
    r = cur.fetchone()
    chk("R3 gitee_repo_member：成员行已落库", r["n"] and r["n"] > 0, r)

    cur.execute("""SELECT event_type, COUNT(*) n FROM gitee_event
                   WHERE tenant_id=%s GROUP BY event_type""", (tid,))
    ev = {x["event_type"]: x["n"] for x in cur.fetchall()}
    chk("R4a gitee_event：事件行已落库", bool(ev), ev)
    chk("R4b 覆盖 PUSH 事件（本地 push 经 Webhook 回流）", ev.get("PUSH", 0) > 0, ev)

    cur.execute("SELECT COUNT(*) n FROM gitee_commit WHERE tenant_id=%s", (tid,))
    n_commit = cur.fetchone()["n"]
    chk("R5 gitee_commit：提交明细已落库", n_commit > 0, n_commit)

    cur.execute("""SELECT status, COUNT(*) n FROM gitee_task
                   WHERE tenant_id=%s GROUP BY status""", (tid,))
    tk = {x["status"]: x["n"] for x in cur.fetchall()}
    chk("R6 gitee_task：异步任务行已落库", bool(tk), tk)
    chk("R6b 任务有终态（DONE>0，队列不是卡在 PENDING）", tk.get("DONE", 0) > 0, tk)

    cur.execute("""SELECT COUNT(*) n FROM gitee_event
                   WHERE tenant_id=%s AND received_at >= %s""", (tid, args.since))
    n_recent = cur.fetchone()["n"]
    chk("R7 事件收到的时点在本次运行窗口内（证明是本轮写入）",
        n_recent > 0, {"since": args.since, "rows": n_recent})

    print("\n" + "=" * 70)
    print("落库核对：PASS=%d FAIL=%d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("未满足：" + ", ".join(FAIL))
    print("=" * 70)
    c.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
