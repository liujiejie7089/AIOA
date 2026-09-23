# -*- coding: utf-8 -*-
"""
目标：线上 swagger-ui.html 可打开（200），但 /scfy/v3/api-docs 返回 500（code=401）。
本脚本尝试多种 springdoc/swagger 元数据入口，看能否拿到**全量接口清单**，
用于回答「线上是否存在文档之外、我们尚未接入的查询接口」。

判定口径：
- 拿到 JSON（含 paths / apis / groups）→ 直接枚举接口，与契约 67 个对照
- 一律 401/404/000 → 说明线上接口清单不可匿名获取，只能以接口文档为准（结论也是结论）
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

HOST = "https://szbhpt.tsichuan.com"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def call(path, params=None, timeout=12):
    url = HOST + path
    if params:
        url += "?" + urllib.parse.urlencode(params, encoding="utf-8")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) aioa-probe/1.0",
        "Accept": "application/json, text/html, */*",
    })
    try:
        with urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX)).open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(20000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, dict(e.headers or {}), body
    except Exception as e:
        return -1, {}, repr(e)[:120]


# 常见元数据入口（springdoc / springfox / knife4j / 裸文档）
CANDIDATES = [
    ("/scfy/v3/api-docs/swagger-config", None),
    ("/scfy/v3/api-docs", None),
    ("/scfy/v3/api-docs", {"group": "default"}),
    ("/scfy/v3/api-docs/default", None),
    ("/scfy/v3/api-docs/1", None),
    ("/scfy/swagger-resources", None),
    ("/scfy/v2/api-docs", {"group": "default"}),
    ("/scfy/doc.html", None),
    ("/scfy/swagger-ui/index.html", None),
    ("/scfy/webjars/swagger-ui/index.html", None),
    ("/scfy/swagger-ui.html", None),
]

ALL = {}
print("=" * 104)
print("一、尝试获取线上接口清单元数据")
print("=" * 104)
for p, prm in CANDIDATES:
    st, hdr, body = call(p, prm)
    ct = (hdr.get("Content-Type") or "").split(";")[0]
    snip = body[:180].replace("\n", " ").replace("\r", " ")
    print(f"  [{st:>4}] {ct:<30} {p} {prm or ''}")
    print(f"          {snip}")
    # 尝试当 JSON 解析
    try:
        j = json.loads(body)
        if isinstance(j, dict) and (j.get("paths") or j.get("apis") or j.get("urls")):
            ALL[p] = j
            print("          >>> 拿到结构化文档！")
    except Exception:
        pass

print()
print("=" * 104)
print("二、若拿到 paths，则枚举接口（与契约对照）")
print("=" * 104)
paths = set()
for p, j in ALL.items():
    for k in (j.get("paths") or {}):
        paths.add(k)
    for a in (j.get("apis") or []):
        if isinstance(a, dict) and a.get("path"):
            paths.add(a["path"])
if paths:
    shows = sorted(x for x in paths if "/show/" in x)
    others = sorted(x for x in paths if "/show/" not in x)
    print(f"  共 {len(paths)} 条，其中 /show/ 查询类 {len(shows)} 条，其他 {len(others)} 条")
    print("  --- /show/ 查询类 ---")
    for s in shows:
        print("   ", s)
    print("  --- 其他（多为需登录的写/管理接口）---")
    for s in others:
        print("   ", s)
    open("docs/_incoming/_prod_api_paths.txt", "w", encoding="utf-8").write(
        "\n".join(sorted(paths)))
    print("  已写出 docs/_incoming/_prod_api_paths.txt")
else:
    print("  未取到任何结构化 paths —— 线上接口清单不可匿名获取")
