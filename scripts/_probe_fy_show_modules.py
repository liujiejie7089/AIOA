# -*- coding: utf-8 -*-
"""
目标：判断 /scfy/show/ 下是否存在**接口文档未列、但线上真部署**的业务模块。

方法（对照法）：
  对每个候选模块名 M，请求 /scfy/show/M/__probe_no_such_method__
  - 若 M 存在：Spring 找到该 Controller 前缀，通常返回业务信封（code=404/500 或 JSON）
  - 若 M 不存在：网关/容器返回 BWS 404 HTML 或 Spring 的 NOT_FOUND JSON
  再用两个已知基线校准：
    已知存在模块 project + 假方法  → 基线 A
    已知不存在模块 zzz_nope + 假方法 → 基线 B
  凡响应形态等于 A、且明显不等于 B 的，判为「模块存在」。
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
FAKE = "__probe_no_such_method__"


def call(path, timeout=10):
    req = urllib.request.Request(HOST + path, headers={
        "User-Agent": "Mozilla/5.0 aioa-probe/1.0",
        "Accept": "application/json, text/html, */*",
    })
    try:
        with urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX)).open(req, timeout=timeout) as r:
            return r.status, r.read(1200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(1200).decode("utf-8", "replace")
        except Exception:
            return e.code, ""
    except Exception as e:
        return -1, repr(e)[:100]


def shape(st, body):
    """把响应压成可比较的形状"""
    if st == 404 and "BWS" in body:
        return "GATEWAY_404"
    if st == 404:
        return "APP_404"
    try:
        j = json.loads(body)
        if isinstance(j, dict):
            return f"JSON code={j.get('code')} status={j.get('status')}"
    except Exception:
        pass
    return f"{st} {body[:40]}"


print("=" * 104)
print("基线校准")
print("=" * 104)
st, b = call(f"/scfy/show/project/{FAKE}")
BASE_EXIST = shape(st, b)
print(f"  存在模块 project + 假方法   -> [{BASE_EXIST}]")
st, b = call(f"/scfy/show/zzznope_xyz/{FAKE}")
BASE_MISS = shape(st, b)
print(f"  不存在模块 zzznope_xyz + 假方法 -> [{BASE_MISS}]")

# 候选模块名：文档已列的 + 非遗业务里可能另有其名的
CANDIDATES = [
    # 文档已列（应判「存在」，用于验证方法有效性）
    "project", "inheritor", "workshop", "ecologicalArea", "travel",
    # 可能另有（猜测）
    "activity", "activities", "venue", "venues", "commodity", "goods",
    "course", "courses", "base", "bases", "expert", "experts",
    "video", "videos", "news", "article", "articles", "museum", "museums",
    "common", "dict", "dictionary", "area", "city", "cities", "statistic",
    "statistics", "count", "index", "home", "banner", "file", "upload",
    "nonheritage", "feiyi", "scfy", "exhibition", "perform", "performance",
    "study", "route", "routes", "scenic", "shop", "product", "products",
]

print()
print("=" * 104)
print("逐模块探测")
print("=" * 104)
exists, unknown = [], []
for m in CANDIDATES:
    st, b = call(f"/scfy/show/{m}/{FAKE}")
    sh = shape(st, b)
    tag = "存在?" if sh == BASE_EXIST else ("无  " if sh == BASE_MISS else "待看")
    if sh == BASE_EXIST:
        exists.append(m)
    elif sh != BASE_MISS:
        unknown.append((m, sh))
    print(f"  [{tag}] {sh:<48} {m}")

print()
print("=" * 104)
print("汇总")
print("=" * 104)
print(f"  形态=存在基线（模块很可能部署）: {exists or '无'}")
print(f"  形态两者都不是（需人工看）: {unknown or '无'}")
