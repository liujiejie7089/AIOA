# -*- coding: utf-8 -*-
"""
探测本地后台测试服务 http://127.0.0.1:16060 —— 只做只读探测，不改任何数据。
目的：确认上下文路径、是否暴露 /show/* 免登录接口、登录端点形态。
"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:16060"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call(method, path, data=None, timeout=10, follow=True):
    url = BASE + path
    body = data.encode("utf-8") if isinstance(data, str) else data
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": "aioa-probe/1.0",
                                          "Accept": "application/json, text/html, */*"})
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(6000).decode("utf-8", "replace")
            return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        raw = e.read(6000).decode("utf-8", "replace") if hasattr(e, "read") else ""
        return e.code, dict(e.headers or {}), raw
    except Exception as e:
        return -1, {}, repr(e)[:200]


def show(tag, r):
    code, hdr, raw = r
    loc = hdr.get("Location") or hdr.get("location") or ""
    print(f"  {tag:<58} -> {code} {('Location: ' + loc) if loc else ''}")
    if raw:
        print(f"      {raw[:260].replace(chr(10), ' ')}")


print("=" * 104)
print("1) 上下文路径与重定向")
print("=" * 104)
show("GET /scfy (不跟随重定向)", call("GET", "/scfy", follow=False))
show("GET /scfy/", call("GET", "/scfy/"))
show("GET /scfy/login", call("GET", "/scfy/login"))
show("GET /scfy/index", call("GET", "/scfy/index"))
show("GET /scfy/swagger-ui.html", call("GET", "/scfy/swagger-ui.html"))

print()
print("=" * 104)
print("2) 免登录只读接口（文档 6.x 的 /show/*）")
print("=" * 104)
for p in ["/scfy/show/ecologicalArea/getAreasNum",
          "/scfy/show/project/getProjectCountByArea",
          "/scfy/show/inheritor/getAreaInheritorData"]:
    show(f"GET {p}", call("GET", p))

print()
print("=" * 104)
print("3) 登录端点形态（文档 3.1：/sso/shiro/ajaxLogin，表单 username/password）")
print("=" * 104)
show("POST /scfy/sso/shiro/ajaxLogin (空参)", call("POST", "/scfy/sso/shiro/ajaxLogin", data=""))
show("GET  /scfy/sso/shiro/ajaxLogin", call("GET", "/scfy/sso/shiro/ajaxLogin"))
show("POST /scfy/login (空参)", call("POST", "/scfy/login", data="username=&password="))

print()
print("=" * 104)
print("4) 探服务标识（响应头/错误体里常有框架与上下文线索）")
print("=" * 104)
code, hdr, raw = call("GET", "/scfy/")
print("  headers:", json.dumps({k: v for k, v in hdr.items()
                               if k.lower() in ("server", "content-type", "x-application-context",
                                                "set-cookie", "www-authenticate")}, ensure_ascii=False)[:400])
print("  body  :", raw[:600].replace("\n", " ")[:600])
