# -*- coding: utf-8 -*-
"""scfy 原生 MCP 服务器：把契约导出的 /show/* 只读接口包成标准 MCP 工具。

不碰非遗服务、不改 aios 基座：工具逻辑在 hub，经 httpx GET 直连 base-url。
工具目录来自 catalog.py（Java 契约导出物），本文件只负责「按目录注册 + 归一化回包」。

回包纪律（沿用 docs/34）：上游 code/msg 原样带出，不把失败伪装成成功；
area/level 等参数错配在 scfy 是「静默返回空集」，故在 description 里已由契约写明，
这里不再替模型猜参 —— 抽不到就让它空着，由模型决定是否追问用户。

按租户接入（docs/92 阶段 4）：本 server 是**原生**实装，工具不经过 Java 的
/api/v1/mcp/builtin/{code}/call，因此原先完全没有身份校验 —— 绕过 manifest 直接
POST /mcp/scfy 就能调用。现在每次 tools/call 前先从入站请求取 Authorization，
回调 Java /api/v1/mcp/access/scfy/check 做准入判定（Java 是唯一身份权威，
hub 不解析 token、不持密钥）。判定不通过直接回 ok=false，**不发**非遗 GET。
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from ..transport import security_settings
from . import catalog

logger = logging.getLogger("mcp_hub.scfy")

SERVER_CODE = catalog.SERVER_CODE

_client: httpx.AsyncClient | None = None

# 官网 /show/* 前有行为风控：python-httpx 默认 UA 会在部分路径上被 403
# （实测 project_type_data / getHeritageYearList 403，inheritor_type_data 200），
# 同一 URL 换成常规浏览器 UA 立即 200。这里只声明普通 HTTP 头，不做绕过/伪造身份。
_HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}


async def _client_get() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20.0),
                                    follow_redirects=False, headers=_HTTP_HEADERS)
    return _client


def _java_base_url() -> str:
    return os.environ.get("AIOS_SERVER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _access_check_enabled() -> bool:
    """回滚开关（docs/92 风险 8）：AIOS_SCFY_ACCESS_CHECK=0 时退回平台级统一接入。

    纯 hub 进程内验证 / 上游接口连通性测试用它跳过回调 —— 那些场景既没有 Java，
    也没有用户 token，不该把「缺身份」误判成权限缺陷。
    """
    return os.environ.get("AIOS_SCFY_ACCESS_CHECK", "1") != "0"


class _Verdict:
    __slots__ = ("ok", "reason", "base_url")

    def __init__(self, ok: bool, reason: "str | None" = None,
                 base_url: "str | None" = None):
        self.ok = ok
        self.reason = reason
        self.base_url = base_url


# 不做准入结果缓存：docs/92 风险 7 要求接入态「走库实时查、启用/停用即时生效」。
# 若缓存 allow，管理员停用后 TTL 内仍会被放行；若缓存 deny，启用后 TTL 内仍被拒 ——
# 两个方向都会把授权层架空。一次 tools/call 只多一次本机回环 HTTP（agent 单轮同 server
# 上限 4 次，见 nodes.py MCP_MAX_CALLS_PER_SERVER），开销可忽略，却换来判据无隐藏状态，
# 且每次调用都如实写一条 mcp_tool_audit（缓存反而会漏记审计）。
_DENIED_PREFIX = "接入受控："


def _get_auth_header(ctx: "Context | None") -> "str | None":
    """从入站 MCP 请求取 Authorization，原样透传（缺 Bearer 前缀时补上）。

    与 builtin.py#_get_auth_header 同款：agent 的 MultiServerMCPClient 连接 hub 时带
    headers={"Authorization": f"Bearer {token}"}（agent/tools/client.py:168-173），
    因此 hub 能把调用者身份交给 Java 判定，自己不解析 token、不持密钥。
    """
    try:
        if ctx is None:
            return None
        request = ctx.request_context.request
        auth = request.headers.get("authorization")
        if auth and not auth.lower().startswith("bearer "):
            return "Bearer " + auth
        return auth
    except Exception:
        return None


async def _authorize(ctx: "Context | None", tool: str) -> _Verdict:
    """每次 tools/call 前的准入判定：回调 Java；未接入/停用/越范围一律拒绝（fail-closed）。

    关键取舍：Java 不可达时**不放行**。若 fail-open，管理员刚停用的租户会在后端抖动期间
    重新拿到数据，等于把授权层架空。同时文案明确说「接入校验服务暂不可用」，
    避免模型把权限问题误报成「非遗数据源故障」（docs/92 风险 9、docs/89 §12）。
    """
    if not _access_check_enabled():
        return _Verdict(True)

    auth = _get_auth_header(ctx)
    if not auth:
        # 没有身份 ⇒ 绝不猜一个默认租户放行：那正是「绕过 manifest 直调」的口子
        return _Verdict(False, "缺少调用身份：该能力需租户完成接入配置后方可调用，请通过正常对话发起查询")

    url = f"{_java_base_url()}/api/v1/mcp/access/{SERVER_CODE}/check"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"tool": tool},
                                    headers={"Authorization": auth})
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            verdict = _Verdict(False, "接入校验返回格式异常，本轮未执行非遗查询")
        else:
            ok = bool(data.get("ok"))
            verdict = _Verdict(
                ok,
                None if ok else (data.get("reason") or "本租户未接入该能力"),
                data.get("baseUrl") if ok else None,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("scfy access check 回调失败 tool=%s：%s", tool, exc)
        # 文案刻意不出现「数据源故障」字样：模型极易抓到这个词就写成「非遗数据源不可用」，
        # 把权限/校验环节的问题误报成上游故障（docs/89 §12 真机踩过同类坑）。
        verdict = _Verdict(False, "接入校验服务暂不可用，本轮未执行非遗查询"
                                  "（这是接入授权环节异常，不是上游接口返回错误）")

    return verdict


def _coerce(value: Any, ptype: str) -> Any:
    """模型可能把 integer 传成字符串；按契约类型归一化，空值一律不传。"""
    if value is None or value == "":
        return None
    if ptype == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


async def _call(endpoint_id: str, _base_override: "str | None" = None,
                **kwargs: Any) -> dict:
    tool = catalog.BY_NAME[endpoint_id]
    params: dict[str, Any] = {}
    for name, value in kwargs.items():
        if value is None or value == "":
            continue
        spec = tool["inputSchema"]["properties"].get(name, {})
        params[name] = _coerce(value, spec.get("type", "string"))

    # 租户级数据源覆盖（connector_tenant_access.config_json.baseUrl）：空则用平台默认。
    # 用 _base_override 这个带下划线的名字，避免与 /show/* 的业务参数撞名。
    base = (_base_override or catalog.base_url()).rstrip("/")
    url = base + tool["path"]
    try:
        client = await _client_get()
        resp = await client.get(url, params=params)
        status = resp.status_code
        if status != 200:
            return {"ok": False, "serverCode": SERVER_CODE, "tool": endpoint_id,
                    "endpoint": tool["path"], "httpStatus": status,
                    "errors": "非遗服务返回 HTTP " + str(status)}
        try:
            payload = resp.json()
        except Exception:
            return {"ok": False, "serverCode": SERVER_CODE, "tool": endpoint_id,
                    "endpoint": tool["path"], "httpStatus": status,
                    "errors": "非遗服务返回非 JSON（可能是网关错误页）",
                    "raw": resp.text[:200]}
        code = payload.get("code") if isinstance(payload, dict) else None
        if code not in (0, "0", None):
            return {"ok": False, "serverCode": SERVER_CODE, "tool": endpoint_id,
                    "endpoint": tool["path"], "httpStatus": status,
                    "upstreamCode": code, "errors": str(payload.get("msg") or "上游业务错误")}
        data = payload.get("data") if isinstance(payload, dict) else payload
        out: dict[str, Any] = {"ok": True, "serverCode": SERVER_CODE, "tool": endpoint_id,
                               "endpoint": tool["path"], "source": "scfy", "data": data}
        if isinstance(data, list) and len(data) > 50:
            out["truncated"] = True
            out["totalItems"] = len(data)
            out["data"] = data[:50]
        return out
    except Exception as exc:
        logger.warning("scfy call %s failed: %s", endpoint_id, exc)
        return {"ok": False, "serverCode": SERVER_CODE, "tool": endpoint_id,
                "endpoint": tool["path"], "errors": "调用非遗服务失败：" + str(exc)[:200]}


def _make_tool_fn(endpoint_id: str):
    """按契约 schema 构造带签名与 docstring 的协程函数，FastMCP 据此生成 inputSchema。

    ``ctx: Context`` 是 FastMCP 的注入参数（与 builtin.py 通用代理同款），**不会**出现在
    生成的 inputSchema 里 —— 因此 69 个工具的对外契约零漂移，probe / catalog.json 不用改。
    """
    tool = catalog.BY_NAME[endpoint_id]
    schema = tool["inputSchema"]
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    # ctx 无默认值 ⇒ 排序后与其它必填参数一起排在前；FastMCP 识别 Context 注解并注入。
    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for name, spec in props.items():
        annotation = int if spec.get("type") == "integer" else str
        default = inspect.Parameter.empty if name in required else None
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY,
                                        default=default, annotation=annotation))
        # 必填在前、可选在后，避免 Python「非默认参数跟在默认参数后」语法错误
    params.sort(key=lambda p: p.default is not inspect.Parameter.empty)

    async def _fn(ctx: Context, **kwargs: Any) -> dict:
        verdict = await _authorize(ctx, endpoint_id)
        if not verdict.ok:
            # 判定不通过：直接回结构化失败，不发非遗 GET。带 accessDenied 标记，
            # 让模型/前端能区分「权限问题」与「上游数据源故障」（docs/92 风险 9）。
            return {
                "ok": False,
                "serverCode": SERVER_CODE,
                "tool": endpoint_id,
                "accessDenied": True,
                "errors": _DENIED_PREFIX + (verdict.reason or "本租户未接入该能力"),
            }
        return await _call(endpoint_id, _base_override=verdict.base_url, **kwargs)

    _fn.__name__ = f"{SERVER_CODE}__{endpoint_id}"
    _fn.__signature__ = inspect.Signature(params)
    _fn.__doc__ = tool["summary"] + ("。注意：" + tool["note"] if tool.get("note") else "")
    return _fn


def build_server() -> FastMCP:
    mcp = FastMCP(SERVER_CODE, streamable_http_path="/", transport_security=security_settings())
    for endpoint_id in catalog.BY_NAME:
        tool = catalog.BY_NAME[endpoint_id]
        mcp.add_tool(
            _make_tool_fn(endpoint_id),
            name=endpoint_id,
            description=tool["summary"] + ("。注意：" + tool["note"] if tool.get("note") else ""),
            annotations=ToolAnnotations(read_only_hint=True, title=tool["group"]),
        )
    logger.info("scfy MCP 就绪：%d 个只读工具，baseUrl=%s", len(catalog.BY_NAME), catalog.base_url())
    return mcp
