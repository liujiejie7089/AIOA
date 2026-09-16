#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gitee V5 OpenAPI 本地桩服务（端到端回归用）。

为什么需要它
------------
真实的 Gitee 有两个硬性约束让自动化回归无法稳定跑：
  1. 需要**有效的 OAuth 应用 + 有效令牌**（用户提供的试用令牌实测 401，见 docs/29 风险章节）；
  2. Webhook 回调地址必须是 **Gitee 能访问到的公网地址**，本机 127.0.0.1 不可达。

本桩服务把这两点都变成可控的：平台侧只要把 `aioa.gitee.base-url` / `web-base-url`
指向它，就走完了与真实 Gitee 完全相同的代码路径（HTTP 调用、错误处理、幂等、
退避重试），而**不需要任何真实凭据**。平台侧代码里没有任何 if-stub 分支 ——
换回真实地址即是生产形态。

已覆盖的端点（与 GiteeClient 一一对应）
--------------------------------------
OAuth：`GET /oauth/authorize`、`POST /oauth/token`（授权码 / 刷新令牌，**模拟 refresh_token 轮换**）
用户：`GET /api/v5/user`、`/user/orgs`、`/orgs/{org}`、`/orgs/{org}/members`
仓库：`POST /orgs/{org}/repos`、`POST /user/repos`、`GET|DELETE /repos/{o}/{r}`
钩子：`POST|GET /repos/{o}/{r}/hooks`、`DELETE /repos/{o}/{r}/hooks/{id}`
内容：`GET|POST|PUT /repos/{o}/{r}/contents/{path}`
其他：`GET /repos/{o}/{r}/branches`、`/commits`、`/teams`
协作者：`GET /repos/{o}/{r}/collaborators`、`PUT|DELETE .../collaborators/{username}`

控制端点（`/_stub/*`，仅测试使用，不对应任何 Gitee 能力）
----------------------------------------------------------
`GET  /_stub/state`            查看桩内部状态（仓库 / 钩子 / 协作者 / 提交 / 请求日志）
`POST /_stub/reset`            清空状态
`POST /_stub/ratelimit`        {"remaining": N} 让接下来 N 次 /api/v5 调用返回
                               403 Rate Limit Exceeded（用于验证退避重试与限流容忍）
`POST /_stub/token-ttl`        {"seconds": N} 设置新令牌有效期（用于验证自动刷新）
`POST /_stub/expire-tokens`    把现有 access_token 全部置为已过期（触发刷新路径）
`POST /_stub/emit`             {"owner","repo","event","payload"} 由桩**代替 Gitee**
                               投递 Webhook：自动带上该仓库钩子的明文密钥
                               （X-Gitee-Token）—— 因此能验证平台侧的真实校验逻辑
`POST /_stub/emit-raw`         {"url","token","event","payload"} 指定地址与密钥投递，
                               用于验证「密钥错误必须被拒绝」
`GET  /_stub/log`              最近 500 条请求（方法 + 路径 + 认证头是否存在）

启动
----
  python scripts/gitee_stub.py            # 默认 127.0.0.1:8090
  python scripts/gitee_stub.py 8091
"""
import hashlib
import json
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

STUB = {
    "repos": {},        # (owner, repo) -> repo dict
    "hooks": {},        # (owner, repo) -> [hook dict]
    "collabs": {},      # (owner, repo) -> [ {id, login, name, permissions} ]
    "files": {},        # (owner, repo) -> {path: {"sha","content_b64"}}
    "branches": {},     # (owner, repo) -> [{"name","commit":{"sha"}}]
    "commits": {},      # (owner, repo) -> [commit dict]
    "tokens": {},       # access_token -> {"uid","login","refresh","expires_at"}
    "refresh": {},      # refresh_token -> access_token
    "codes": {},        # code -> {"state","redirect_uri"}
    "rate_limit_left": 0,
    "token_ttl": 7200,
    "log": [],
    "seq": 0,
}

LOCK = threading.Lock()

ORG_MEMBERS = [
    {"id": 90001, "login": "znkjyf_admin", "name": "机构管理员"},
    {"id": 90002, "login": "znsfb_ldr", "name": "部门负责人"},
    {"id": 90003, "login": "znsfb_m01", "name": "算法部成员"},
]

app = FastAPI(title="Gitee V5 Stub")


# ======================================================================
# 基础设施
# ======================================================================

def _nxt() -> int:
    STUB["seq"] += 1
    return STUB["seq"]


def _fail(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": message})


def _auth(request: Request) -> Optional[Dict[str, Any]]:
    """解析 `Authorization: token xxx`（平台侧只走请求头）。"""
    h = request.headers.get("authorization") or ""
    if not h.lower().startswith("token "):
        return None
    tok = h[6:].strip()
    info = STUB["tokens"].get(tok)
    if not info:
        return None
    if info["expires_at"] and info["expires_at"] < time.time():
        return None
    return info


@app.middleware("http")
async def _log_and_ratelimit(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/_stub"):
        with LOCK:
            STUB["log"].append({
                "method": request.method, "path": path,
                "auth": bool(request.headers.get("authorization")),
                "t": time.strftime("%H:%M:%S"),
            })
            STUB["log"] = STUB["log"][-500:]
            if path.startswith("/api/v5") and STUB["rate_limit_left"] > 0:
                STUB["rate_limit_left"] -= 1
                return JSONResponse(status_code=403, content={"message": "Rate Limit Exceeded"})
    return await call_next(request)


# ======================================================================
# OAuth2
# ======================================================================

@app.get("/oauth/authorize")
def authorize(client_id: str = "", redirect_uri: str = "", response_type: str = "code",
              state: str = "", scope: str = "", login: str = ""):
    """授权页。

    `login` 是**桩特有的**参数（真实 Gitee 会忽略未知参数）：让测试可以指定这次授权
    对应哪个 Gitee 身份，从而在同一个平台租户里绑定多个不同 Gitee 账号（成员同步测试需要）。
    不传时按序号生成一个独立身份。
    """
    if not redirect_uri:
        return _fail(400, "redirect_uri required")
    code = "code_%d" % _nxt()
    who = login.strip() or ("gitee_dev_%d" % _nxt())
    uid = 42000 + (int(hashlib.md5(who.encode()).hexdigest()[:6], 16) % 1000)
    with LOCK:
        STUB["codes"][code] = {"state": state, "redirect_uri": redirect_uri,
                               "login": who, "uid": uid}
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}code={code}&state={state}", status_code=302)


@app.post("/oauth/token")
def token(request: Request,
          grant_type: str = Form(""),
          code: str = Form(""),
          refresh_token: str = Form(""),
          client_id: str = Form(""),
          client_secret: str = Form(""),
          redirect_uri: str = Form("")):
    if grant_type == "refresh_token":
        old = STUB["refresh"].get(refresh_token)
        if not old:
            # 与真实 Gitee 一致：失效/被轮换掉的 refresh_token 返回 invalid_grant
            return JSONResponse(status_code=400, content={"error": "invalid_grant",
                                                          "error_description": "refresh token 无效或已被轮换"})
        info = STUB["tokens"].get(old) or {}
        login = info.get("login", "unknown")
        uid = info.get("uid", 0)
        with LOCK:
            STUB["tokens"].pop(old, None)
            STUB["refresh"].pop(refresh_token, None)
        return JSONResponse(_issue(uid, login))

    entry = STUB["codes"].pop(code, None)
    if not entry:
        return JSONResponse(status_code=400, content={"error": "invalid_grant",
                                                      "error_description": "授权码无效或已使用"})
    return JSONResponse(_issue(entry["uid"], entry["login"]))


def _issue(uid: int, login: str) -> Dict[str, Any]:
    n = _nxt()
    at, rt = "at_%d_%d" % (uid, n), "rt_%d_%d" % (uid, n)
    with LOCK:
        # 真实 Gitee 对「同一应用 + 同一用户」重新授权会签发新令牌并让旧令牌失效，
        # 桩服务照此模拟：否则「重复绑定」之后桩侧会残留一堆旧令牌，
        # 让「平台是否只维护一条有效授权」这件事无法被断言。
        for old_at, info in list(STUB["tokens"].items()):
            if info.get("uid") == uid:
                STUB["refresh"].pop(info.get("refresh"), None)
                STUB["tokens"].pop(old_at, None)
        STUB["tokens"][at] = {"uid": uid, "login": login, "refresh": rt,
                              "expires_at": time.time() + STUB["token_ttl"]}
        STUB["refresh"][rt] = at
    return {"access_token": at, "refresh_token": rt,
            "expires_in": STUB["token_ttl"], "token_type": "bearer",
            "scope": "user_info projects pull_requests issues notes",
            "created_at": int(time.time())}


# ======================================================================
# 用户与组织
# ======================================================================

@app.get("/api/v5/user")
def user(request: Request):
    info = _auth(request)
    if not info:
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return {"id": info["uid"], "login": info["login"], "name": "机构管理员",
            "avatar_url": "https://gitee.com/assets/favicon.ico", "email": "dev@example.com"}


@app.get("/api/v5/user/orgs")
def user_orgs(request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return [{"id": 1, "login": "aioa-demo-org", "name": "AIOA 演示组织"}]


@app.get("/api/v5/orgs/{org}")
def get_org(org: str):
    return {"id": 1, "login": org, "name": org}


@app.get("/api/v5/orgs/{org}/members")
def org_members(org: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return ORG_MEMBERS


# 组织级 Team：Gitee 开放平台**没有**该 API（真实环境返回 HTML 404）。
# 桩服务显式返回 HTML 404，让平台侧的降级路径（命名空间 + 协作者）始终被真实走一遍，
# 避免以后有人误以为「Team 方案可用」。
@app.get("/api/v5/orgs/{org}/teams")
def org_teams_absent(org: str):
    return JSONResponse(status_code=404,
                        content={"message": "Not Found"},
                        media_type="text/html")


# ======================================================================
# 仓库
# ======================================================================

def _repo_key(owner: str, repo: str):
    return (owner, repo)


def _mk_repo(owner: str, name: str, path: str, description: str, private: bool) -> Dict[str, Any]:
    rid = 70000 + _nxt()
    repo = {
        "id": rid,
        "name": name,
        "path": path or name,
        "full_name": f"{owner}/{path or name}",
        "description": description or "",
        "private": bool(private),
        "html_url": f"http://127.0.0.1:{PORT}/{owner}/{path or name}",
        "ssh_url": f"git@127.0.0.1:{owner}/{path or name}.git",
        "https_url": f"http://127.0.0.1:{PORT}/{owner}/{path or name}.git",
        "default_branch": "master",
        "owner": {"login": owner, "id": 1},
    }
    key = _repo_key(owner, repo["path"])
    with LOCK:
        STUB["repos"][key] = repo
        STUB["hooks"].setdefault(key, [])
        STUB["collabs"].setdefault(key, [])
        STUB["files"].setdefault(key, {})
        STUB["branches"][key] = [{"name": "master", "commit": {"sha": "init0000"}}]
        STUB["commits"].setdefault(key, [{
            "sha": "init0000", "message": "Initial commit",
            "author": {"name": owner, "email": "init@example.com"},
            "timestamp": "2026-01-01T00:00:00+08:00",
        }])
    return repo


@app.post("/api/v5/orgs/{org}/repos")
def create_org_repo(org: str, request: Request, body: Dict[str, Any] = Body(default={})):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    path = body.get("path") or body.get("name")
    if _repo_key(org, path) in STUB["repos"]:
        # 与真实 Gitee 一致：路径被占用返回 422（平台侧应识别为「已存在」并改为认领）
        return JSONResponse(status_code=422,
                            content={"message": "Repository already exists, path has been used"})
    return _mk_repo(org, body.get("name", path), path, body.get("description", ""),
                    body.get("private", True))


@app.post("/api/v5/user/repos")
def create_user_repo(request: Request, body: Dict[str, Any] = Body(default={})):
    info = _auth(request)
    if not info:
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return _mk_repo(info["login"], body.get("name"), body.get("path") or body.get("name"),
                    body.get("description", ""), body.get("private", True))


@app.get("/api/v5/repos/{owner}/{repo}")
def get_repo(owner: str, repo: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    r = STUB["repos"].get(_repo_key(owner, repo))
    if not r:
        return _fail(404, "Not Found")
    return r


@app.delete("/api/v5/repos/{owner}/{repo}")
def delete_repo(owner: str, repo: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    if key not in STUB["repos"]:
        return _fail(404, "Not Found")
    with LOCK:
        for d in ("repos", "hooks", "collabs", "files", "branches", "commits"):
            STUB[d].pop(key, None)
    return JSONResponse(status_code=204, content=None)


# ======================================================================
# Webhook（含明文密钥 password）
# ======================================================================

@app.post("/api/v5/repos/{owner}/{repo}/hooks")
def create_hook(owner: str, repo: str, request: Request, body: Dict[str, Any] = Body(default={})):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    if key not in STUB["repos"]:
        return _fail(404, "Not Found")
    if not body.get("url"):
        return _fail(400, "url required")
    hook = {
        "id": 80000 + _nxt(),
        "url": body["url"],
        "password": body.get("password", ""),
        "push_events": body.get("push_events", True),
        "merge_requests_events": body.get("merge_requests_events", False),
        "issues_events": body.get("issues_events", False),
        "note_events": body.get("note_events", False),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    with LOCK:
        STUB["hooks"][key].append(hook)
    return hook


@app.get("/api/v5/repos/{owner}/{repo}/hooks")
def list_hooks(owner: str, repo: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return STUB["hooks"].get(_repo_key(owner, repo), [])


@app.delete("/api/v5/repos/{owner}/{repo}/hooks/{hook_id}")
def delete_hook(owner: str, repo: str, hook_id: int, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    lst = STUB["hooks"].get(key, [])
    for i, h in enumerate(lst):
        if h["id"] == hook_id:
            with LOCK:
                lst.pop(i)
            return JSONResponse(status_code=204, content=None)
    return _fail(404, "Not Found")


# ======================================================================
# 内容（分支 / 文件）
# ======================================================================

@app.get("/api/v5/repos/{owner}/{repo}/branches")
def list_branches(owner: str, repo: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return STUB["branches"].get(_repo_key(owner, repo), [])


@app.get("/api/v5/repos/{owner}/{repo}/commits")
def list_commits(owner: str, repo: str, request: Request, sha: str = "", per_page: int = 20):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return STUB["commits"].get(_repo_key(owner, repo), [])[:per_page]


@app.get("/api/v5/repos/{owner}/{repo}/contents/{path:path}")
@app.get("/api/v5/repos/{owner}/{repo}/contents")
def get_contents(owner: str, repo: str, request: Request, path: str = "", ref: str = ""):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    if key not in STUB["repos"]:
        return _fail(404, "Not Found")
    files = STUB["files"].get(key, {})
    path = (path or "").strip("/")
    if path and path in files:
        f = files[path]
        return {
            "type": "file", "name": path.split("/")[-1], "path": path,
            "size": len(f["content_b64"]), "sha": f["sha"],
            "encoding": "base64", "content": f["content_b64"],
            "download_url": f"http://127.0.0.1:{PORT}/raw/{owner}/{repo}/{path}",
        }
    # 目录：返回该前缀下的一级子项
    prefix = (path + "/") if path else ""
    seen, out = set(), []
    for p, f in files.items():
        if not p.startswith(prefix):
            continue
        rest = p[len(prefix):]
        if "/" in rest:
            name = rest.split("/")[0]
            if name in seen:
                continue
            seen.add(name)
            out.append({"type": "dir", "name": name, "path": prefix + name, "sha": "dir0"})
        else:
            out.append({"type": "file", "name": rest, "path": p,
                        "size": len(f["content_b64"]), "sha": f["sha"]})
    if not out:
        return _fail(404, "Not Found")
    return out


def _commit(key: str, path: str, b64: str, message: str, login: str) -> Dict[str, Any]:
    sha = hashlib.sha1((path + b64 + message + str(_nxt())).encode()).hexdigest()
    short = sha[:7]
    with LOCK:
        STUB["files"][key][path] = {"sha": short, "content_b64": b64}
        STUB["commits"][key].insert(0, {
            "sha": sha, "message": message,
            "author": {"name": login, "email": f"{login}@example.com"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        })
        STUB["branches"][key] = [{"name": "master", "commit": {"sha": sha}}]
    return {"sha": sha, "short": short}


@app.post("/api/v5/repos/{owner}/{repo}/contents/{path:path}")
@app.post("/api/v5/repos/{owner}/{repo}/contents")
def create_file(owner: str, repo: str, request: Request, path: str = "",
                body: Dict[str, Any] = Body(default={})):
    info = _auth(request)
    if not info:
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    if key not in STUB["repos"]:
        return _fail(404, "Not Found")
    path = (path or "").strip("/")
    if not path:
        return _fail(400, "path required")
    if path in STUB["files"].get(key, {}):
        # 已存在必须走 PUT（真实 Gitee 同样返回 422）
        return JSONResponse(status_code=422,
                            content={"message": "File already exists, please use PUT to update"})
    c = _commit(key, path, body.get("content", ""), body.get("message", ""), info["login"])
    return {"content": {"path": path, "sha": c["short"]},
            "commit": {"sha": c["sha"], "message": body.get("message", "")}}


@app.put("/api/v5/repos/{owner}/{repo}/contents/{path:path}")
@app.put("/api/v5/repos/{owner}/{repo}/contents")
def update_file(owner: str, repo: str, request: Request, path: str = "",
                body: Dict[str, Any] = Body(default={})):
    info = _auth(request)
    if not info:
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    if key not in STUB["repos"]:
        return _fail(404, "Not Found")
    path = (path or "").strip("/")
    cur = STUB["files"].get(key, {}).get(path)
    if not cur:
        return _fail(404, "Not Found")
    if body.get("sha") and body["sha"] != cur["sha"]:
        return _fail(409, "sha 不匹配，文件已被他人修改")
    c = _commit(key, path, body.get("content", ""), body.get("message", ""), info["login"])
    return {"content": {"path": path, "sha": c["short"]},
            "commit": {"sha": c["sha"], "message": body.get("message", "")}}


# ======================================================================
# 协作者
# ======================================================================

@app.get("/api/v5/repos/{owner}/{repo}/collaborators")
def list_collaborators(owner: str, repo: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return STUB["collabs"].get(_repo_key(owner, repo), [])


@app.put("/api/v5/repos/{owner}/{repo}/collaborators/{username}")
def add_collaborator(owner: str, repo: str, username: str, request: Request,
                     body: Dict[str, Any] = Body(default={})):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    if key not in STUB["repos"]:
        return _fail(404, "Not Found")
    perm = (body.get("permission") or "write").lower()
    lst = STUB["collabs"].setdefault(key, [])
    for c in lst:
        if c["login"] == username:
            with LOCK:
                c["permissions"] = perm
            return JSONResponse(status_code=204, content=None)
    with LOCK:
        lst.append({"id": 60000 + _nxt(), "login": username, "name": username,
                    "permissions": perm})
    return JSONResponse(status_code=204, content=None)


@app.delete("/api/v5/repos/{owner}/{repo}/collaborators/{username}")
def remove_collaborator(owner: str, repo: str, username: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    key = _repo_key(owner, repo)
    lst = STUB["collabs"].get(key, [])
    for i, c in enumerate(lst):
        if c["login"] == username:
            with LOCK:
                lst.pop(i)
            return JSONResponse(status_code=204, content=None)
    return _fail(404, "Not Found")


@app.get("/api/v5/repos/{owner}/{repo}/teams")
def list_repo_teams(owner: str, repo: str, request: Request):
    if not _auth(request):
        return _fail(401, "401 Unauthorized: Access token does not exist")
    return []


# ======================================================================
# 控制端点
# ======================================================================

@app.get("/_stub/state")
def stub_state():
    return {
        "repos": [r for r in STUB["repos"].values()],
        # 钩子里的 password 是明文共享密钥，**不外泄**：只回报「是否已设置 + 长度」
        "hooks": {f"{k[0]}/{k[1]}": [
            {"id": h["id"], "url": h["url"], "passwordSet": bool(h.get("password")),
             "passwordLen": len(h.get("password") or ""),
             "push": h.get("push_events"), "mr": h.get("merge_requests_events"),
             "issue": h.get("issues_events"), "note": h.get("note_events")}
            for h in v] for k, v in STUB["hooks"].items()},
        "collabs": {f"{k[0]}/{k[1]}": v for k, v in STUB["collabs"].items()},
        "files": {f"{k[0]}/{k[1]}": sorted(v.keys()) for k, v in STUB["files"].items()},
        "commits": {f"{k[0]}/{k[1]}": [c["message"] for c in v] for k, v in STUB["commits"].items()},
        "tokens": list(STUB["tokens"].keys()),
        "refresh": list(STUB["refresh"].keys()),
        "rate_limit_left": STUB["rate_limit_left"],
    }


@app.post("/_stub/grant")
def stub_grant(body: Dict[str, Any] = Body(default={})):
    """模拟「有人在 Gitee 网页端手工加了协作者」——用于验证校准能把外部协作者纳入平台。"""
    key = _repo_key(body["owner"], body["repo"])
    if key not in STUB["repos"]:
        return {"ok": False, "reason": "仓库不存在"}
    lst = STUB["collabs"].setdefault(key, [])
    login = body["login"]
    with LOCK:
        for c in lst:
            if c["login"] == login:
                return {"ok": True, "already": True}
        lst.append({"id": 60000 + _nxt(), "login": login, "name": login,
                    "permissions": body.get("permission", "write")})
    return {"ok": True}


@app.post("/_stub/reset")
def stub_reset():
    with LOCK:
        for d in ("repos", "hooks", "collabs", "files", "branches", "commits", "tokens", "refresh"):
            STUB[d] = {}
        STUB["codes"] = {}
        STUB["rate_limit_left"] = 0
        STUB["token_ttl"] = 7200
        STUB["log"] = []
    return {"reset": True}


@app.post("/_stub/ratelimit")
def stub_ratelimit(body: Dict[str, Any] = Body(default={})):
    STUB["rate_limit_left"] = int(body.get("remaining", 1))
    return {"rate_limit_left": STUB["rate_limit_left"]}


@app.post("/_stub/token-ttl")
def stub_token_ttl(body: Dict[str, Any] = Body(default={})):
    STUB["token_ttl"] = int(body.get("seconds", 7200))
    return {"token_ttl": STUB["token_ttl"]}


@app.post("/_stub/expire-tokens")
def stub_expire():
    n = 0
    with LOCK:
        for info in STUB["tokens"].values():
            info["expires_at"] = time.time() - 10
            n += 1
    return {"expired": n}


@app.post("/_stub/emit")
def stub_emit(body: Dict[str, Any] = Body(default={})):
    """代替 Gitee 投递 Webhook：自动带上该仓库钩子里的明文密钥。"""
    owner, repo = body.get("owner"), body.get("repo")
    key = _repo_key(owner, repo)
    hooks = STUB["hooks"].get(key, [])
    if not hooks:
        return {"delivered": 0, "reason": "该仓库没有已配置的 Webhook"}
    event = body.get("event", "Push Hook")
    payload = body.get("payload", {})
    out = []
    with httpx.Client(timeout=30, trust_env=False) as c:
        for h in hooks:
            try:
                r = c.post(h["url"], json=payload, headers={
                    "Content-Type": "application/json",
                    "X-Gitee-Event": event,
                    "X-Gitee-Token": h.get("password", ""),
                    "X-Gitee-Request-Id": "req-%d" % _nxt(),
                })
                out.append({"url": h["url"], "status": r.status_code,
                            "body": _safe_json(r.text)})
            except Exception as e:  # noqa: BLE001
                out.append({"url": h["url"], "status": 0, "body": str(e)})
    return {"delivered": len(out), "results": out}


@app.post("/_stub/emit-raw")
def stub_emit_raw(body: Dict[str, Any] = Body(default={})):
    """按指定地址与密钥投递（用于验证「密钥错误必须被拒绝」）。"""
    with httpx.Client(timeout=30, trust_env=False) as c:
        r = c.post(body["url"], json=body.get("payload", {}), headers={
            "Content-Type": "application/json",
            "X-Gitee-Event": body.get("event", "Push Hook"),
            "X-Gitee-Token": body.get("token", ""),
        })
    return {"status": r.status_code, "body": _safe_json(r.text)}


@app.get("/_stub/log")
def stub_log():
    return {"items": STUB["log"][-500:], "total": len(STUB["log"])}


def _safe_json(t: str):
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        return t[:400]


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
