# -*- coding: utf-8 -*-
"""管理端「项目文档上传」500 修复的活体验收（docs/44 §3）。

缺陷（已修）：`PmDocService.createDocument` 旧实现把 sizeBytes 写成一行三元：
    d.setSizeBytes(contentText.isEmpty() ? asLong(body.get("sizeBytes"))
                                         : (long) contentText.getBytes().length)
Java 三元要做「数值提升」：另一支是基本类型 `long`，会把这一支的包装类型 `Long` 一并拆箱。
上传路径 `contentText` 为空、前端也不传 `sizeBytes` ⇒ `asLong(null)` 返回 null ⇒
`NullPointerException` ⇒ 接口回 500。实测（2026-10-10，修复前）：管理端「上传文档」100% 失败。

**负向对照（铁律 12 —— 先证明判据会红，否则无法区分「真通过」与「判据无效」）**：
  · 修复前的 A/B 对照（已留在会话记录里）：同一请求
      - 不带 sizeBytes、不传 contentText → HTTP 500（这就是 V5 判据在修复前的样子）
      - 带 sizeBytes、不传 contentText   → code:0
    即 V5 不是恒真断言：它明确区分了带/不带 sizeBytes 两种输入。
  · 本脚本自带 `--selftest`：把危险三元重新注入源码文本，静态判据 V12 必须报红。

**为什么判据不止「接口回 200」**：
  「接口成功」不等于「数据对」。V6 回到事实源 `sys_file.size` 复核，而不是读接口自己
 返回的 sizeBytes —— 否则渲染层/服务层读错字段也会一起绿（铁律 12 的教训）。

用法：
    python scripts/_verify_pm_doc_upload.py             # 活体验收（需 8080 在线 + V71~V77 已应用）
    python scripts/_verify_pm_doc_upload.py --selftest  # 静态判据自检（注入危险三元，必须报红）

退出码：0 = 全过；1 = 有失败。
"""
import io
import os
import re
import sys
import time
import argparse

import httpx
import pymysql

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
# 允许指向另一个端口（用于「不动用户正在跑的 8080，用新构建的 jar 另起 8081 验收」）
USER, PWD = "dsj_admin", "User@123"
HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = os.path.join(HERE, "..", "server", "aioa-project", "src", "main", "java",
                       "cn", "aioa", "project", "service", "PmDocService.java")
DB = dict(host="127.0.0.1", port=3306, user="root", password="",
          database="aioa", charset="utf8mb4")

C = httpx.Client(timeout=60, trust_env=False)
RES = []


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def login(name, pwd=PWD):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd,
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}（环境漂移？铁律 15）")
    return d["data"]["accessToken"]


def call(method, path, h, **kw):
    return getattr(C, method)(f"{API}{path}", headers=h, **kw).json()


# ----------------------------------------------------------------------
# 静态判据：危险三元（会发生数值提升 / 拆箱）不得存在
# ----------------------------------------------------------------------

def static_violations(src):
    """返回 [(行号, 代码)]：同一行里同时出现 `? :` 、`(long)` 强转 与 `asLong(` 调用。

    这正是本条缺陷的形态：一支是基本类型 `(long) ...`，另一支是返回包装类型 `Long` 的
    `asLong(...)` ⇒ 三元整体被提升为 long ⇒ asLong 结果为 null 时拆箱 NPE。
    """
    bad = []
    for i, line in enumerate(src.splitlines(), 1):
        code = line.split("//")[0]
        if "?" in code and ":" in code and "(long)" in code and "asLong(" in code:
            bad.append((i, line.strip()))
    return bad


def check_static(src):
    bad = static_violations(src)
    chk("V12 ★静态：PmDocService 不存在会拆箱的危险三元（`? asLong(..) : (long) ..`）",
        not bad, bad)
    has_ref = "aiRefMapper.fileSize(" in src
    chk("V12b 静态：sizeBytes 的事实源路径存在（走 aiRefMapper.fileSize 回查 sys_file）",
        has_ref, "" if has_ref else "未找到 aiRefMapper.fileSize 调用")
    has_local = re.search(r"\bLong\s+sizeBytes\s*;", src) is not None
    chk("V12c 静态：sizeBytes 落在可空的局部变量 `Long sizeBytes;`（保可空语义、不拆箱）",
        has_local, "" if has_local else "未找到 `Long sizeBytes;`")


def selftest():
    """把危险三元注入源码文本，静态判据 V12 必须真报红。"""
    src = open(SERVICE, encoding="utf-8").read()
    base = static_violations(src)
    if base:
        print("[FAIL] 自检前置不成立：当前源码已含危险三元 %s" % base)
        return 1
    injected = src.replace(
        "        Long sizeBytes;",
        '        Long sizeBytes;\n'
        '        d.setSizeBytes(contentText.isEmpty() ? asLong(body.get("sizeBytes")) '
        ': (long) contentText.getBytes(StandardCharsets.UTF_8).length);')
    if injected == src:
        print("[FAIL] 自检突变未生效：锚点 `Long sizeBytes;` 已漂移，请同步本判据")
        return 1
    fired = static_violations(injected)
    if not fired:
        print("[FAIL] 注入危险三元后静态判据**未报红** ⇒ 判据失效（V12 是恒真断言）")
        return 1
    print("[PASS] 自检：注入危险三元后 V12 真报红 %s ⇒ 判据有效" % (fired,))
    return 0


# ----------------------------------------------------------------------
# 活体验收
# ----------------------------------------------------------------------

def cleanup(h, created):
    ok = True
    for p in created:
        r = call("delete", f"/pm/projects/{p}", h)
        if r.get("code") != 0:
            ok = False
            print("    清理失败 id=%s: %s" % (p, r.get("message")))
    chk("V13 临时项目已全部软删（自净，铁律 11）", ok, created)


def main():
    stamp = time.strftime("%m%d-%H%M%S")
    src = open(SERVICE, encoding="utf-8").read()
    check_static(src)

    h = {"Authorization": "Bearer " + login(USER)}
    chk("V1 dsj_admin 登录成功", True)

    created = []
    db = pymysql.connect(**DB)
    cur = db.cursor(pymysql.cursors.DictCursor)

    def file_size(file_id):
        cur.execute("SELECT `size` FROM sys_file WHERE id=%s", (file_id,))
        row = cur.fetchone()
        return int(row["size"]) if row else None

    try:
        # ---- 对照组：业务项目能建出来（证明请求通路 / 鉴权没问题）
        r = call("post", "/pm/projects", h, json={
            "projectNo": "VDOC-A-" + stamp, "name": "验收-文档上传A " + stamp,
            "projectType": "BUSINESS", "budgetAmount": 1})
        pid = (r.get("data") or {}).get("id")
        if not chk("V2 业务项目创建成功（对照组）", r.get("code") == 0 and bool(pid), r):
            raise SystemExit("无法建项目，后续判据无意义")
        created.append(pid)

        # ---- 另一个项目，用于「文件夹跨项目」负向
        r = call("post", "/pm/projects", h, json={
            "projectNo": "VDOC-B-" + stamp, "name": "验收-文档上传B " + stamp,
            "projectType": "BUSINESS", "budgetAmount": 1})
        pid2 = (r.get("data") or {}).get("id")
        chk("V3 第二个业务项目创建成功", r.get("code") == 0 and bool(pid2), r)
        if pid2:
            created.append(pid2)

        # ---- 文件夹
        r = call("post", f"/pm/projects/{pid}/docs/folders", h, json={"name": "验收夹 " + stamp})
        fid = (r.get("data") or {}).get("id")
        if not chk("V4 项目文件夹创建成功", r.get("code") == 0 and bool(fid), r):
            raise SystemExit("无 folderId，无法继续")
        others = []
        if pid2:
            r2 = call("post", f"/pm/projects/{pid2}/docs/folders", h, json={"name": "他项夹 " + stamp})
            if (r2.get("data") or {}).get("id"):
                others.append(r2["data"]["id"])

        # ---- 真实上传一份文件，拿到 fileId 与真实字节数
        payload = ("AIOA 文档上传验收 " + stamp).encode("utf-8")
        up = C.post(f"{API}/files/upload", headers=h,
                    files={"file": ("验收-%s.txt" % stamp, io.BytesIO(payload), "text/plain")}).json()
        file_id = (up.get("data") or {}).get("id")
        real_size = file_size(file_id) if file_id else None
        if not chk("V4b 真实文件上传成功且能从 sys_file 读到字节数",
                   up.get("code") == 0 and file_id is not None and real_size == len(payload),
                   "fileId=%s real=%s expect=%s" % (file_id, real_size, len(payload))):
            raise SystemExit("无法上传文件，V5/V6 无法进行")

        # ---- V5 ★主判据：不带 sizeBytes 登记文档（修复前 = 500）
        r = call("post", f"/pm/projects/{pid}/docs/documents", h, json={
            "folderId": fid, "name": "不带sizeBytes " + stamp,
            "source": "UPLOAD", "fileId": file_id})
        doc_id = (r.get("data") or {}).get("id")
        chk("V5 ★不带 sizeBytes 登记上传文档 → code:0（修复前此处 NPE→500）",
            r.get("code") == 0 and bool(doc_id),
            "code=%s msg=%s" % (r.get("code"), r.get("message")))
        chk("V5b 该返回体 sizeBytes 非空（NPE 的直接症状是这一步为空/500）",
            (r.get("data") or {}).get("sizeBytes") is not None, r.get("data"))

        # ---- V6 ★同源：sizeBytes 必须等于事实源 sys_file.size（不读接口副本自证）
        chk("V6 ★sizeBytes 与 sys_file.size 同源（不带 sizeBytes 路径）",
            (r.get("data") or {}).get("sizeBytes") == real_size,
            "resp=%s sys_file=%s" % ((r.get("data") or {}).get("sizeBytes"), real_size))

        # ---- V5c/V6b 前端真实路径：带 sizeBytes（PmProjectDetailView 传 f.size）
        r = call("post", f"/pm/projects/{pid}/docs/documents", h, json={
            "folderId": fid, "name": "带sizeBytes " + stamp,
            "source": "UPLOAD", "fileId": file_id, "sizeBytes": real_size})
        chk("V5c 带 sizeBytes 登记上传文档 → code:0（与前端一致）",
            r.get("code") == 0, r)
        chk("V6b ★带 sizeBytes 路径的 sizeBytes 仍等于 sys_file.size（两端不漂移）",
            (r.get("data") or {}).get("sizeBytes") == real_size,
            "resp=%s sys_file=%s" % ((r.get("data") or {}).get("sizeBytes"), real_size))

        # ---- V7 AI 源：sizeBytes 取正文 UTF-8 字节数，且忽略 body.sizeBytes
        text = "数字人正文 speed check " + stamp
        expect = len(text.encode("utf-8"))
        r = call("post", f"/pm/projects/{pid}/docs/documents", h, json={
            "folderId": fid, "name": "AI正文 " + stamp,
            "source": "AI", "contentText": text, "sizeBytes": 999999})
        chk("V7 ★AI 源 sizeBytes = 正文 UTF-8 字节数（且忽略 body 里的 999999）",
            r.get("code") == 0 and (r.get("data") or {}).get("sizeBytes") == expect,
            "resp=%s expect=%s" % ((r.get("data") or {}).get("sizeBytes"), expect))

        # ---- 负向 N 组：证明端点不是「来什么都说 ok」
        if others:
            r = call("post", f"/pm/projects/{pid}/docs/documents", h, json={
                "folderId": others[0], "name": "跨项夹 " + stamp,
                "source": "UPLOAD", "fileId": file_id})
            chk("VN1 负向：用**另一个项目**的 folderId → 被拒（证明归属守卫活着）",
                r.get("code") not in (0, None) and "不属于本项目" in str(r.get("message")), r)

        r = call("post", f"/pm/projects/{pid}/docs/documents", h, json={
            "name": "无夹 " + stamp, "source": "UPLOAD", "fileId": file_id})
        chk("VN2 负向：不传 folderId → 400 被拒",
            r.get("code") not in (0, None) and "folderId" in str(r.get("message")), r)

        r = call("post", f"/pm/projects/{pid}/docs/documents", h, json={
            "folderId": fid, "name": "长" * 201, "source": "UPLOAD", "fileId": file_id})
        chk("VN3 负向：名称 201 字 → 业务错误（400），**不得是 500**",
            r.get("code") not in (0, None, 500) and "过长" in str(r.get("message")),
            "code=%s msg=%s" % (r.get("code"), r.get("message")))

        # ---- 只读终态：DRAFT → ARCHIVED（PmProjectStatus 允许一步直达），写入必须被拒
        r = call("post", f"/pm/projects/{pid2}/status", h, json={"status": "ARCHIVED"}) if pid2 else {"code": None}
        if chk("VN4a 项目可置为只读终态 ARCHIVED", r.get("code") == 0, r):
            r2 = call("post", f"/pm/projects/{pid2}/docs/folders", h, json={"name": "只读后建的夹"})
            chk("VN4b ★只读终态下建文件夹被拒，文案含「归档」（requireWrite 单一判定点）",
                r2.get("code") not in (0, None) and "归档" in str(r2.get("message")), r2)
            r3 = call("post", f"/pm/projects/{pid2}/docs/documents", h, json={
                "folderId": fid, "name": "只读后建的文档", "source": "UPLOAD", "fileId": file_id})
            chk("VN4c ★只读终态下登记文档被拒（不得静默成功）",
                r3.get("code") not in (0, None), r3)
        else:
            print("  SKIP VN4 无法把项目置为 ARCHIVED，只读判据未验证")

    finally:
        try:
            cleanup(h, created)
        finally:
            cur.close()
            db.close()

    n = len(RES)
    bad = [c for c, ok in RES if not ok]
    print("\n" + "=" * 70)
    print("=== 文档上传验收 %d/%d 通过 ===" % (n - len(bad), n))
    if bad:
        print("失败项：" + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="静态判据自检（注入危险三元，必须报红）")
    ap.add_argument("--base", default=API, help="接口前缀，默认 http://127.0.0.1:8080/api/v1")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    API = args.base
    sys.exit(main())
