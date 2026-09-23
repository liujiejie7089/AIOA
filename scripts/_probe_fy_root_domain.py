# -*- coding: utf-8 -*-
"""
探测非遗域名 https://szbhpt.tsichuan.com/ 下的业务前缀可达性（只发 GET，无写操作）。

背景：
- 已知 https://szbhpt.tsichuan.com/scfy/show/* 可达且免登录（55 个查询接口已实测）。
- 但域名根路径此前只测到「302 → http://szbhpt.tsichuan.com:16060/scfy/ → 502」，
  未系统排查过**其他业务前缀**。
- 候选前缀取自接口文档正文出现过的那几个：/scfy、/scfy-zigong、/web/api、/zytf/api、
  /nmch/ccss、/sys、/sso、/applet、/upload_image，外加常见探查点（swagger/actuator/doc）。

判定口径：
- 200 + JSON/code 字段 → 有业务响应（可读）
- 401/403 → 服务在，需鉴权（也是一种「可达」）
- 404 / 502 / 000 → 不可达或无此路径，并区分「服务不存在」与「网关无上游」
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call(path, params=None, timeout=12, follow=True, host=HOST):
    url = host + path
    if params:
        url += "?" + urllib.parse.urlencode(params, encoding="utf-8")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) aioa-probe/1.0",
        "Accept": "application/json, text/html, */*",
    })
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(1500).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(1500).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, dict(e.headers or {}), body
    except Exception as e:
        return -1, {}, repr(e)[:110]


def line(tag, status, hdr, body):
    loc = hdr.get("Location") or hdr.get("location") or ""
    ct = (hdr.get("Content-Type") or hdr.get("content-type") or "").split(";")[0]
    flag = {200: "OK ", 302: "-> ", 401: "鉴权", 403: "拒绝", 404: "无  ", 500: "500", 502: "网关"}.get(status, "?  ")
    extra = f" -> {loc}" if loc else ""
    snippet = body[:150].replace("\n", " ").replace("\r", " ")
    print(f"  [{flag}] {status:>4} {ct:<28} {tag}{extra}")
    if snippet:
        print(f"          {snippet}")


BASE_PATHS = [
    "/",
    "/scfy",
    "/scfy/",
    "/scfy/show/ecologicalArea/getAreasNum",
    "/scfy/sso/shiro/ajaxLogin",
    "/scfy-zigong/",
    "/show/ecologicalArea/getAreasNum",
    "/swagger-ui.html",
    "/scfy/swagger-ui.html",
    "/v2/api-docs",
    "/scfy/v2/api-docs",
    "/scfy/v3/api-docs",
    "/actuator/health",
    "/scfy/actuator/health",
    "/sys/",
    "/sso/",
    "/sso/shiro/ajaxLogin",
    "/web/",
    "/web/api/",
    "/zytf/",
    "/zytf/api/",
    "/nmch/",
    "/nmch/ccss/",
    "/applet/",
    "/applet/appletexhibition/",
    "/upload_image",
    "/api/",
    "/api/scfy/",
    "/fy/",
    "/portal/",
    "/index.html",
    "/favicon.ico",
]

print("=" * 104)
print("一、根域名下的候选前缀（默认跟随重定向）")
print("=" * 104)
reachable = []
for p in BASE_PATHS:
    st, hdr, body = call(p)
    line(p, st, hdr, body)
    if st in (200, 401, 403, 500) or "code" in body[:60]:
        reachable.append((p, st))

print()
print("=" * 104)
print("二、根路径重定向链（不跟随，逐跳看）")
print("=" * 104)
cur = "/"
for _ in range(4):
    st, hdr, body = call(cur, follow=False)
    loc = hdr.get("Location") or hdr.get("location")
    line(cur, st, hdr, body)
    if not loc:
        break
    if loc.startswith("http"):
        nxt = urllib.parse.urlparse(loc)
        cur = nxt.path or "/"
        print(f"          （下一跳为绝对地址，主机 {nxt.scheme}://{nxt.netloc}）")
    else:
        cur = loc

print()
print("=" * 104)
print("三、重定向指向的 16060 端口（http / https 各试一次）")
print("=" * 104)
for host in ("http://szbhpt.tsichuan.com:16060", "https://szbhpt.tsichuan.com:16060"):
    for p in ("/scfy/", "/scfy/show/ecologicalArea/getAreasNum", "/"):
        st, hdr, body = call(p, host=host, timeout=8)
        line(f"{host}{p}", st, hdr, body)

print()
print("=" * 104)
print("四、确认已接入通道仍正常（带真实业务参数）")
print("=" * 104)
for p, prm in [
    ("/scfy/show/project/getProjectCountByArea", {"area": "成都市"}),
    ("/scfy/show/ecologicalArea/getAreasNum", None),
    ("/scfy/show/travel/getRoutesTopFewList", {"topNum": 3}),
]:
    st, hdr, body = call(p, prm)
    line(f"{p} {prm or ''}", st, hdr, body)

print()
print("=" * 104)
print("五、汇总：有业务响应的路径")
print("=" * 104)
for p, st in reachable:
    print(f"  {st}  {p}")
