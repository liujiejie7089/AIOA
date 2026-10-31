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


def _env_seconds(name: str, default: float) -> float:
    """读一个「秒数」型环境变量，**配置写错时给一句人话**而不是裸 traceback。

    原来直接 `float(os.environ.get(...))`：`.env` 里写成 `AIOS_WECOM_CLI_TIMEOUT=30s`
    或者多打一个引号，hub 会在 **import 阶段**抛 `ValueError: could not convert string to
    float` —— 现象是容器起不来，日志里只有一个跟业务毫无关系的栈。
    现在仍然 fail-fast（配置错就该拒绝启动），但错因和改法写在异常里。
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        raise RuntimeError(
            f"环境变量 {name}={raw!r} 不是数字。请在 deploy/.env 里写成纯数字秒数，"
            f"例如 {name}={int(default)}（不要带引号或单位）") from None
    if val <= 0:
        raise RuntimeError(f"环境变量 {name}={val} 必须大于 0（单位：秒）")
    return val


TIMEOUT = _env_seconds("AIOS_WECOM_CLI_TIMEOUT", 30.0)
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
        # ⚠️ 不能直接信 env。compose 里给了默认值 `/data/wecom-cli-bin/wecom-cli`，
        # 而宿主目录不存在时 Docker 会**静默建一个空目录**再挂进来 ⇒
        # 路径恒有、文件恒无。原先这里直接 return，于是
        # `create_subprocess_exec` 抛裸 `FileNotFoundError`：
        #   · `cli_auth.status()` 只 catch CliError ⇒ 异常穿透到 REST 面变 500；
        #   · 或者（catch 到别的）被当成「未授权」⇒ 界面显示「没有可用的企业微信连接」，
        #     而真实原因是 CLI 根本没装。—— 2026-10-31 生产现场即此。
        if os.path.isfile(env) and os.access(env, os.X_OK):
            _bin_cache = env
            return _bin_cache
        raise CliError(
            f"未找到企微 CLI：{env} 不存在或不可执行。"
            f"请把官方 wecom-cli（原生可执行文件）放到**仓库内**目录 "
            f"（compose 里是 ${{AIOS_WECOM_CLI_BIN_DIR:-../data/wecom-cli-bin}}，"
            f"挂到容器 /data/wecom-cli-bin），或把 AIOS_WECOM_CLI_BIN 指到容器内正确路径。")
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


def probe() -> dict:
    """排障用：**不抛异常**地报告「CLI 到底在不在」。

    为什么要单独有它：`bin_path()` 一抛就被 `cli_auth.status()` 吞成
    「unauthorized」，界面上只剩一句「没有可用的企业微信连接」，
    分不清是「没扫码」还是「CLI 没装」。让 `GET /api/v1/wecom_cli/status`
    直接把这段带出去，一条 curl 就能定位。
    """
    try:
        return {"path": bin_path(), "ok": True, "error": None}
    except CliError as e:
        return {"path": (os.environ.get("AIOS_WECOM_CLI_BIN") or "").strip() or None,
                "ok": False, "error": str(e)}


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


async def _communicate(proc: asyncio.subprocess.Process, timeout: float,
                       what: str) -> tuple[bytes, bytes]:
    """等子进程输出，并保证**任何退出路径都不留活进程 / 不挂 fd**。

    2026-11-01 加固前这里有三个洞：
      ① `wait_for` 超时后只 `kill()` 不 `await proc.wait()` ⇒ 传输层没关，
         每超时一次泄漏一对管道 fd，压测下最终 `Too many open files`；
      ② 没接 `CancelledError`：客户端断开时 FastAPI 会 cancel 这个协程，
         `wait_for` 抛 `CancelledError` 直接穿透 ⇒ **子进程变成孤儿继续跑**
         （企微 CLI 是长驻进程，一次断开泄漏一个），
      ③ 超时/取消时 `PIPE` 里的残留没人读，子进程若还在写就会：

    统一收口成：kill → await wait() → 再抛。`finally` 兜最后一道。
    """
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        raise CliError(f"企业微信接口超时（{int(timeout)}s）：{what}")
    finally:
        if proc.returncode is None:
            # 走到这里说明是超时 / 取消 / 别的异常：必须亲手收尸，别指望 GC
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.shield(proc.wait())
            except (asyncio.CancelledError, ProcessLookupError, RuntimeError):
                pass


async def _exec(args: list[str], profile_dir: Path, timeout: float | None,
                what: str) -> tuple[bytes, bytes, int | None]:
    """起子进程 + 收输出，收口所有异常路径（见 `_communicate` 的注释）。"""
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
    out, err = await _communicate(proc, t, what)
    return out, err, proc.returncode


async def run(args: list[str], profile_dir: Path, timeout: float | None = None) -> Any:
    """执行一条 CLI 命令并返回解析后的 JSON。失败抛 CliError（中文，可直接展示）。"""
    what = f"{args[0]} {' '.join(args[1:2])}".strip()
    out, err, rc = await _exec(args, profile_dir, timeout, what)
    stdout = out.decode("utf-8", "replace")
    stderr = err.decode("utf-8", "replace")
    if rc != 0:
        detail = (stderr or stdout).strip().replace("\n", " ")[:200]
        if "unauthorized" in detail.lower() or "授权" in detail:
            raise CliError("企业微信授权已失效，请到「连接器 → 企业微信」重新扫码绑定")
        raise CliError(f"企业微信命令失败：{detail or f'exit {rc}'}")
    return _parse(stdout)


async def run_text(args: list[str], profile_dir: Path, timeout: float | None = None) -> str:
    """执行命令并返回**原始 stdout**。

    存在的理由：`auth show --status` 输出的是裸文本 `authorized` / `unauthorized`，不是 JSON。
    用 `run()` 会把它当坏数据抛错 —— 而「未授权」恰恰是正常状态，不该走异常路径。
    """
    what = " ".join(args[:2])
    out, err, rc = await _exec(args, profile_dir, timeout, what)
    text = out.decode("utf-8", "replace").strip()
    if rc != 0:
        detail = (err.decode("utf-8", "replace") or text).strip().replace("\n", " ")[:200]
        raise CliError(f"企业微信命令失败：{detail or f'exit {rc}'}")
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
