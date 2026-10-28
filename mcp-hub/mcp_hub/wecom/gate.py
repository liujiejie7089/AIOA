# -*- coding: utf-8 -*-
"""模式闸门：连接态 → 工具白名单。

规则：
- lifecycle 工具（connect / disconnect / connection_status）任意状态可调；
- A 组工具要求连接态含 A（A 或 AB）；
- B 组工具要求连接态含 B（B 或 AB）；
- 未连接时只能调 lifecycle，其余一律拒绝并给出可读原因（H5 据此渲染「去连接」引导）。

模式串解析统一走 store.split_modes（"AB" → ["A","B"]），不各处 split 加深坑。
"""

from __future__ import annotations

from .catalog import TOOLS_BY_NAME
from .models import MODE_A, MODE_B
from .store import split_modes


def tools_for_mode(mode: str | None) -> set[str]:
    """该模式下可调的工具名集合。"""
    names = {t["name"] for t in TOOLS_BY_NAME.values() if not t["modes"]}
    modes = split_modes(mode)
    for tool in TOOLS_BY_NAME.values():
        if tool["modes"] and any(m in modes for m in tool["modes"]):
            names.add(tool["name"])
    return names


def check_tool(mode: str | None, tool_name: str) -> tuple[bool, str]:
    """返回 (是否放行, 拒绝原因)。"""
    tool = TOOLS_BY_NAME.get(tool_name)
    if tool is None:
        return False, f"未知工具 {tool_name}"
    if not tool["modes"]:
        return True, ""
    modes = split_modes(mode)
    if any(m in modes for m in tool["modes"]):
        return True, ""
    if not mode:
        return False, "尚未连接企业微信，请先调用 connect 完成授权"
    label = "企微 OAuth 授权" if tool["modes"][0] == MODE_A else "企业邮箱绑定"
    if MODE_A in modes and tool["modes"][0] == MODE_B:
        hint = "当前仅绑定了企微 OAuth（消息/通讯录），邮件工具需要再绑定企业邮箱（connect mode=B）"
    elif MODE_B in modes and tool["modes"][0] == MODE_A:
        hint = "当前仅绑定了企业邮箱（邮件），消息/通讯录工具需要再绑定企微 OAuth（connect mode=A）"
    else:
        hint = f"需要 {label}"
    return False, f"当前连接模式为 {mode}，不支持工具 {tool_name}：{hint}"
