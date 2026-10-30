# -*- coding: utf-8 -*-
"""`wecom-cli` 子进程封装：定位可执行文件、注入配置目录、超时、结果解析。

为什么不用 `node bin/wecom.js`：那个壳只是按平台转发到 `@wecom/cli-<platform>/bin/wecom-cli`。
直接跑原生 exe 少一层 node 启动（每次调用省 ~200ms），也少一个「node 不在 PATH」的故障面。

纪律：
- 每个用户一个 `WECOM_CLI_CONFIG_DIR`，**只有**这一处能决定身份，命令里不接受任何身份参数。
- 环境变量里剔除 WorkBuddy 连接器注入的 `WECOM_CLI_ADDITIONAL_HEADERS_*`：
  那是「连接器自身」的请求头，串进用户调用会变成两种身份混用。
- 输出按 JSON 解析；解析失败不吞错，把原始前 200 字符带出去（否则排查时只剩「未知错误」）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from . import profiles

logger = logging.getLogger("mcp_hub.wecom_cli")

TIMEOUT = float(os.environ.get("AIOS_WECOM_CLI_TIMEOUT", "30"))
MAX_OUTPUT = 4 * 1024 * 1024

_PKG_ROOT = Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages"


class CliError(RuntimeError):
    pass


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return m


def _candidates() -> list[Path]:
    plat = {"win32": "win32", "darwin": "darwin"}.get(sys.platform, "linux")
    exe = "wecom-cli.exe" if sys.platform == "win32" else "wecom-cli"
    return [
        _PKG_ROOT / "node_modules" / "@wecom" / "cli" / "node_modules" / "@wecom"
        / f"cli-{plat}-{_arch()}" / "bin" / exe,
        _PKG_ROOT / exe,   # npm 生成的 shim（.cmd），兜底用
    ]


_bin_cache: "str | None" = None


def bin_path() -> str:
    """定位可执行文件。显式 env 优先（部署时用），其次 WorkBuddy 包内置，最后 PATH。"""
    global _bin_cache
    if _bin_cache:
        return _bin_cache
    env = (os.environ.get("AIOS_WECOM_CLI_BIN") or "").strip()
    if env:
        _bin_cache = env
        return _bin_cache
    for c in _candidates():
        if c.is_file():
            _bin_cache = str(c)
            logger.info("wecom-cli 可执行文件：%s", _bin_cache)
            return _bin_cache
    found = shutil.which("wecom-cli")
    if found:
        _bin_cache = found
        return _bin_cache
    raise CliError("未找到 wecom-cli。请执行 `npm i -g @wecom/cli`，"
                   "或设置 AIOS_WECOM_CLI_BIN 指向可执行文件")


def _env(profile_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("WECOM_CLI_ADDITIONAL_HEADERS_")}
    # 注意方向：`profile_dir` 是**本项目**的基目录（<root>/<t>/<u>），
    # 而 CLI 要的 WECOM_CLI_CONFIG_DIR 是其中真正放 credentials.enc 的那一层。
    # 直接塞 profile_dir 会让 CLI 把凭据写到别处，而 profiles.is_authorized 永远读不到
    # —— 现象是「扫码成功了，但系统一直说未绑定」。见 profiles.cli_dir 的实测记录。
    env["WECOM_CLI_CONFIG_DIR"] = str(profiles.cli_dir(profile_dir))
    env.setdefault("NO_COLOR", "1")
    return env


def _parse(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 分页命令会输出 NDJSON：逐行解析后拼成数组，别把整段当坏数据丢掉
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows = []
            break
    if rows:
        return rows
    raise CliError(f"输出不是合法 JSON：{text[:200]}")


async def run(args: list[str], profile_dir: Path, timeout: float | None = None) -> Any:
    """执行一条 CLI 命令并返回解析后的 JSON。失败抛 CliError（中文，可直接展示）。"""
    cmd = [bin_path(), *args]
    t = timeout or TIMEOUT
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env(profile_dir),
        cwd=str(profile_dir),
        limit=MAX_OUTPUT,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=t)
    except asyncio.TimeoutError:
        proc.kill()
        raise CliError(f"企业微信接口超时（{int(t)}s）：{args[0]} {' '.join(args[1:2])}")
    stdout = out.decode("utf-8", "replace")
    stderr = err.decode("utf-8", "replace")
    if proc.returncode != 0:
        detail = (stderr or stdout).strip().replace("\n", " ")[:200]
        if "unauthorized" in detail.lower() or "授权" in detail:
            raise CliError("企业微信授权已失效，请到「连接器 → 企业微信」重新扫码绑定")
        raise CliError(f"企业微信命令失败：{detail or f'exit {proc.returncode}'}")
    return _parse(stdout)


async def run_text(args: list[str], profile_dir: Path, timeout: float | None = None) -> str:
    """执行命令并返回**原始 stdout**。

    存在的理由：`auth show --status` 输出的是裸文本 `authorized` / `unauthorized`，不是 JSON。
    用 `run()` 会把它当坏数据抛错 —— 而「未授权」恰恰是正常状态，不该走异常路径。
    """
    cmd = [bin_path(), *args]
    t = timeout or TIMEOUT
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env(profile_dir),
        cwd=str(profile_dir),
        limit=MAX_OUTPUT,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=t)
    except asyncio.TimeoutError:
        proc.kill()
        raise CliError(f"企业微信接口超时（{int(t)}s）：{' '.join(args[:2])}")
    text = out.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        detail = (err.decode("utf-8", "replace") or text).strip().replace("\n", " ")[:200]
        raise CliError(f"企业微信命令失败：{detail or f'exit {proc.returncode}'}")
    return text


async def spawn(args: list[str], profile_dir: Path) -> asyncio.subprocess.Process:
    """起一个长驻命令（用于 `auth init` 扫码，它要阻塞等人工扫码）。调用方负责收尾。"""
    return await asyncio.create_subprocess_exec(
        bin_path(), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env(profile_dir),
        cwd=str(profile_dir),
        limit=MAX_OUTPUT,
    )
