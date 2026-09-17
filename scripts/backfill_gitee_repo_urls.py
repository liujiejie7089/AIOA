#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""存量仓库地址回填工具 —— 修复「地址曾被写成错误域名」的项目行。

为什么需要它
------------
`gitee_project` 的三个地址列（`gitee_html_url` / `gitee_ssh_url` / `gitee_https_url`）
是**建仓那一刻的快照**：值来自 Gitee 接口响应，此后**没有任何刷新路径**
（全代码库仅 `GiteeRepoTaskHandler:98-100` 一处赋值，且只在新建成时执行）。
因此当环境曾指向本地桩 / 预发 Gitee，或被 Gitee 侧改名迁移之后，
这些链接会**永久失效**且平台无法自愈 —— 本工具就是补这一段。

安全约定
--------
- **默认干跑（dry-run）**：只打印将要发生的变更，不写库。必须显式 `--apply` 才落库。
- 只改这三个地址列，**不碰** owner / repo_name / 状态等业务字段。
- 生成规则与真实 Gitee 的返回形态一致：`{base}/{owner}/{repo}`、
  `git@{host}:{owner}/{repo}.git`；SSH 主机由 base 推导。
- 不做「模糊猜测」：只按 base 重写。若仓库在 Gitee 侧已改名，
  本工具修不了（需要调一次 `GET /repos/{owner}/{repo}` 重新拉取）——
  见报告里建议的「刷新仓库信息」接口。

用法
----
  python scripts/backfill_gitee_repo_urls.py --base https://gitee.com            # 干跑
  python scripts/backfill_gitee_repo_urls.py --base https://gitee.com --apply    # 落库
"""
import argparse
import sys

import pymysql


def urls_for(base: str, owner: str, repo: str):
    base = base.rstrip("/")
    host = base.split("://", 1)[-1].split("/", 1)[0]
    return (f"{base}/{owner}/{repo}",
            f"git@{host}:{owner}/{repo}.git",
            f"{base}/{owner}/{repo}.git")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="目标公网基址，如 https://gitee.com")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只干跑）")
    ap.add_argument("--tenant", type=int, default=None, help="仅处理某租户")
    args = ap.parse_args()

    conn = pymysql.connect(host="127.0.0.1", user="root", password="",
                           database="aioa", charset="utf8mb4", autocommit=False)
    cur = conn.cursor()

    q = ("SELECT id,tenant_id,gitee_owner,gitee_repo,gitee_html_url,gitee_ssh_url,gitee_https_url "
         "FROM gitee_project WHERE deleted_at IS NULL AND gitee_owner IS NOT NULL "
         "AND gitee_repo IS NOT NULL")
    if args.tenant:
        q += " AND tenant_id=%s"
        cur.execute(q, (args.tenant,))
    else:
        cur.execute(q)
    rows = cur.fetchall()

    print(f"扫描 {len(rows)} 个项目（base={args.base}）")
    plan = []
    for pid, tid, owner, repo, h, s, ht in rows:
        want = urls_for(args.base, owner, repo)
        if (h, s, ht) != want:
            plan.append((pid, tid, owner, repo, (h, s, ht), want))

    if not plan:
        print("无需回填：所有项目地址已是目标域名形态。")
        return 0

    print(f"\n需要回填 {len(plan)} 项：")
    for pid, tid, owner, repo, old, new in plan:
        print(f"  #{pid} (tenant {tid}) {owner}/{repo}")
        print(f"      html : {old[0]}  ->  {new[0]}")
        print(f"      ssh  : {old[1]}  ->  {new[1]}")
        print(f"      https: {old[2]}  ->  {new[2]}")

    if not args.apply:
        print("\n[干跑] 未写库。确认无误后加 --apply 执行。")
        return 0

    for pid, tid, owner, repo, old, new in plan:
        cur.execute("UPDATE gitee_project SET gitee_html_url=%s, gitee_ssh_url=%s, "
                    "gitee_https_url=%s, updated_at=NOW(6) WHERE id=%s", (new[0], new[1], new[2], pid))
    conn.commit()
    print(f"\n[已落库] 回填 {len(plan)} 个项目。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
