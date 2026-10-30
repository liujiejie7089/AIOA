# -*- coding: utf-8 -*-
"""扫码授权：状态查询、身份查询、发起扫码（`auth init`）。

`auth init` 的实测行为（CLI 1.3.4）：
- `--noninteractive` 跳过交互选择，直接走扫码；
- `--no-browser` 不自动开浏览器（我们要自己把二维码给前端）；
- `--output-qrcode <path>` 把二维码落成 PNG —— **这是能被服务端接住的关键**，
  否则二维码只在终端里画字符，H5 根本拿不到；
- 命令**阻塞**直到有人扫码完成，成功后自行退出。

因此这里的做法是：起子进程 → 等 PNG 出现 → 把 PNG 交给前端 → 前端轮询 `status()`
→ 一旦 `authorized` 就收尾（进程通常已自己退出，这里再兜一次 kill）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from . import profiles, runner

logger = logging.getLogger("mcp_hub.wecom_cli")

_QR_NAME = "qr.png"
_QR_TIMEOUT = 20.0     # 等 PNG 落盘的上限
_procs: dict[str, asyncio.subprocess.Process] = {}
_locks: dict[str, asyncio.Lock] = {}


def _lock(d: Path) -> asyncio.Lock:
    key = str(d)
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def status(profile_dir: Path) -> str:
    """`authorized` / `unauthorized`。文件不在就别起子进程了（省一次 fork 且更可靠）。"""
    if not profiles.is_authorized(profile_dir):
        return "unauthorized"
    try:
        text = await runner.run_text(["auth", "show", "--status"], profile_dir, timeout=15)
    except runner.CliError as e:
        logger.info("auth show 失败，按未授权处理：%s", e)
        return "unauthorized"
    low = text.lower()
    if "authorized" in low and "unauthorized" not in low:
        return "authorized"
    return "unauthorized"


_NAME_RE = {
    "bot": re.compile(r"机器人身份：\s*\n?\s*名字：\s*([^\n\r]+)"),
    "user": re.compile(r"授权真人用户身份：\s*\n?\s*名字：\s*([^\n\r]+)"),
}


async def whoami(profile_dir: Path) -> dict:
    """返回 {botName, userName}。**只取名字**：ID 属内部标识，不进模型上下文（见 docs/64 §二）。"""
    data = await runner.run(["identity", "whoami"], profile_dir, timeout=20)
    raw = ""
    if isinstance(data, dict):
        raw = str(data.get("extra_identity_context") or "")
    out = {}
    for k, rx in _NAME_RE.items():
        m = rx.search(raw)
        if m:
            name = m.group(1).strip()
            # 名字后面常跟两个空格再接「ID：」——截断掉
            name = re.split(r"\s{2,}|ID：", name)[0].strip()
            if name:
                out[f"{k}Name"] = name
    if not out.get("userName"):
        raise runner.CliError("已授权但读不到真人身份，请重新扫码绑定")
    return out


def qr_path(profile_dir: Path) -> Path:
    return profile_dir / _QR_NAME


async def start_qr(tenant_id, user_id) -> tuple[Path, bool]:
    """发起扫码，返回 (PNG 路径, 是否已在授权中)。同一用户并发点两次不会起两个进程。"""
    d = profiles.ensure(tenant_id, user_id)
    png = qr_path(d)
    try:
        png.unlink()
    except OSError:
        pass

    async with _lock(d):
        proc = _procs.get(str(d))
        if proc is not None and proc.returncode is None:
            # 已有进程在等扫码：直接复用它的二维码（可能已生成）
            if png.is_file():
                return png, True
        else:
            proc = await runner.spawn(
                ["auth", "init", "--noninteractive", "--no-browser",
                 "--output-qrcode", str(png)], d)
            _procs[str(d)] = proc
            logger.info("已发起企微扫码（tenant=%s user=%s pid=%s）", tenant_id, user_id, proc.pid)

    deadline = time.monotonic() + _QR_TIMEOUT
    while time.monotonic() < deadline:
        if png.is_file() and png.stat().st_size > 0:
            return png, False
        p = _procs.get(str(d))
        if p is not None and p.returncode is not None and not png.is_file():
            raise runner.CliError("二维码生成失败：auth init 已退出但没有产出二维码，请查看 hub 日志")
        await asyncio.sleep(0.3)
    raise runner.CliError("二维码生成超时（20s），请重试或改用 `wecom-cli auth init --manual`")


async def finish(tenant_id, user_id) -> None:
    """扫码成功后收尾：杀掉可能还挂着的 auth init。"""
    d = profiles.dir_for(tenant_id, user_id)
    proc = _procs.pop(str(d), None)
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def bind(tenant_id, user_id) -> dict:
    """确认已授权并取到显示名；成功返回 {accountLabel, botName, shared}。"""
    d, shared = profiles.resolve(tenant_id, user_id)
    st = await status(d)
    if st != "authorized":
        raise runner.CliError("企业微信尚未完成扫码授权")
    names = await whoami(d)
    label = names.get("userName") or ""
    if not shared:
        profiles.set_account_label(d, label)
    await finish(tenant_id, user_id)
    return {"accountLabel": label, "botName": names.get("botName"), "shared": shared}
