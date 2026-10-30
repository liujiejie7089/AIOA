# -*- coding: utf-8 -*-
"""企业微信群机器人连接器（原生 MCP 服务器，/mcp/wecom_group）。

与 wechat_work 的区别：不需要 OAuth、不需要用户连接态，只要一份**租户级 webhook key**
（管理员在管理端填），AI 就能往那个群发消息。这条通道不要求可信 IP / 域名。

凭据来源：`connectors.vault`（provider=vault），按 tenant_id 隔离；进程内不缓存 key。
工具只做两件事：发文本、发 markdown（含 @ 手机号）。
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import group, identity

logger = logging.getLogger("mcp_hub.wecom")

SERVER_CODE = "wecom_group"
SERVER_NAME = "企业微信群机器人"

# 工具目录（唯一事实源：/internal/mcp/probe 与 /mcp/wecom_group 都读这里）
#
# ★ 描述是**给模型看**的提示词，必须把「目标群已由 webhook 绑定」这件事讲死。
#   2026-10-30 实测：描述只写「往企业微信群发送消息」时，MiniMax 拿到 2 个工具却
#   不调用，反问用户「请提供群名称或群ID」—— 因为它以为缺一个必填的群参数。
#   工具压根没有群参数（群由 key 决定），所以描述的**第一句**就要消掉这个歧义，
#   并明确「用户说发群里就直接发、不要反问」。
TOOLS: list[dict] = [
    {
        "name": "send_group_text",
        "description": (
            "往「管理员已用 Webhook 绑定好的那个企业微信群」发送纯文本消息。"
            "目标群由 Webhook Key 决定：**本工具没有、也不需要群名称/群ID/接收人参数**。"
            "所以用户说「发到群里 / 群里通知一下 / 给群里发条消息」时，直接用用户给的正文调用本工具，"
            "不要反问群名或群 ID。群机器人通道不要求可信 IP / 可信域名。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string",
                            "description": "消息正文（用户已给出内容时原样传入，不要自行改写），UTF-8 最长 2048 字节"},
                "atMobiles": {"type": "string",
                              "description": "要 @ 的手机号，多个用逗号分隔；填 @all 提醒所有人；可空"},
            },
            "required": ["content"],
        },
        "read_only": False,
    },
    {
        "name": "send_group_markdown",
        "description": (
            "往「管理员已用 Webhook 绑定好的那个企业微信群」发送 markdown 消息"
            "（支持 **加粗**、> 引用、[链接](url)、<font color=\"info\">彩色字</font>）。"
            "目标群由 Webhook Key 决定：**本工具没有、也不需要群名称/群ID 参数**，"
            "用户说「发到群里」时直接调用，不要反问群名。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string",
                            "description": "markdown 正文（用户已给出内容时原样传入，不要自行改写）"},
                "atMobiles": {"type": "string",
                              "description": "要 @ 的手机号，多个用逗号分隔；可空"},
            },
            "required": ["content"],
        },
        "read_only": False,
    },
]

# 参数类型（用于构造签名，让 FastMCP 推断出与 TOOLS 一致的 JSON Schema）
_PARAMS: dict[str, list[tuple[str, Any, Any]]] = {
    "send_group_text": [("content", str, None), ("atMobiles", str, "")],
    "send_group_markdown": [("content", str, None), ("atMobiles", str, "")],
}


async def _webhook_key(ctx: Context) -> str:
    """取本租户的 webhook key；缺失时抛错（由工具包成 isError，绝不静默）。"""
    # 延迟导入：避免 connectors 包初始化期间与本模块互相 import
    from ..connectors import vault

    ident = await identity.resolve(ctx)
    values = await vault.get_values(ident.tenant_id, SERVER_CODE)
    key = (values.get("webhookKey") or "").strip()
    if not key:
        raise RuntimeError(
            "管理员尚未配置「企业微信群机器人」的 Webhook Key："
            "管理端 → 连接器配置 → 企业微信群机器人 → 填 webhook 地址里 key= 之后的部分"
        )
    return key


def _mobiles(raw: str) -> list[str]:
    if not raw:
        return []
    if raw.strip().lower() == "@all":
        return ["@all"]
    return [s.strip() for s in raw.split(",") if s.strip()]


async def _send(ctx: Context, msgtype: str, content: str, at_mobiles: str) -> CallToolResult:
    try:
        key = await _webhook_key(ctx)
    except identity.IdentityError as e:
        return CallToolResult(isError=True, content=[TextContent(type="text", text=f"身份解析失败：{e}")])
    except RuntimeError as e:
        return CallToolResult(isError=True, content=[TextContent(type="text", text=str(e))])

    if not content or not content.strip():
        return CallToolResult(isError=True, content=[TextContent(type="text", text="content 不能为空")])

    result = await group.send(key, msgtype, content, _mobiles(at_mobiles))
    if result["ok"]:
        payload = {"sent": True, "msgtype": msgtype, "chars": len(content)}
        return CallToolResult(content=[TextContent(
            type="text", text=json.dumps(payload, ensure_ascii=False))])
    return CallToolResult(isError=True, content=[TextContent(
        type="text", text=f"发送失败（errcode={result['errcode']}）：{result['errmsg']}")])


def _make_tool_fn(tool_name: str, props: list[tuple[str, Any, Any]]):
    async def _fn(ctx: Context, **kwargs):
        return await _send(ctx, "markdown" if tool_name == "send_group_markdown" else "text",
                           kwargs.get("content", ""), kwargs.get("atMobiles", ""))

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for pname, ptype, default in props:
        # 坑：default=None 会被 inspect 当成必填 ⇒ 可选参数必须给真默认值（"" 等）
        if default is None:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=ptype))
        else:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY,
                                            default=default, annotation=ptype))
    _fn.__name__ = f"{SERVER_CODE}__{tool_name}"
    _fn.__signature__ = inspect.Signature(params)
    _fn.__doc__ = f"{SERVER_CODE}.{tool_name}"
    return _fn


def build_server() -> FastMCP:
    """构建群机器人原生服务器（streamable_http_path='/'，与其它服务器一致）。"""
    mcp = FastMCP(SERVER_CODE, streamable_http_path="/")
    for tool in TOOLS:
        name = tool["name"]
        mcp.add_tool(
            _make_tool_fn(name, _PARAMS[name]),
            name=name,
            description=tool["description"],
            annotations=ToolAnnotations(read_only_hint=tool["read_only"]),
        )
    return mcp


def tool_count() -> int:
    return len(TOOLS)
