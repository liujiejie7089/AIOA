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
_SESSION = ".qr-session"   # 本次扫码会话的起点（epoch 秒），写在用户基目录里
_QR_TIMEOUT = 20.0     # 等 PNG 落盘的上限
_procs: dict[str, asyncio.subprocess.Process] = {}
_locks: dict[str, asyncio.Lock] = {}

# 「未完成」的四种原因必须分开报，否则用户不知道该重扫还是该解绑。
_BIND_HINT = {
    "no-session": "还没有发起扫码：请点「连接」重新获取二维码",
    "no-credential": "企业微信尚未完成扫码授权：请用手机扫描当前二维码",
    "stale-credential": "检测到以前的授权残留，但这次扫码没有完成：请重新扫码",
    "cli-unauthorized": "授权文件在，但 CLI 自报未授权：请重新扫码（或先解绑再扫）",
}


def _mark_session(own: Path) -> None:
    """记下「这一次扫码从什么时候开始」。

    存在的唯一理由：**防「没扫也说完成了」**。判断扫码完成不能只看 `credentials.enc`
    在不在 —— ①共享兜底目录（`AIOS_WECOM_CLI_SHARED_PROFILE`）里本来就有别人的凭据；
    ②上一次授权遗留下来的旧凭据也一直在。两种情况下文件都"已经在了"，只看存在性就会
    在用户点开二维码的第一次轮询就宣布完成。要求「凭据 mtime 晚于本次会话起点」才能
    把「这次真扫了」和「以前就有」分开。

    写失败只降级为日志：宁可让用户多扫一次，也不要因为标记写不了而让绑定永远失败。
    """
    try:
        (own / _SESSION).write_text("%.3f" % time.time(), encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        logger.info("写入扫码会话标记失败（本次会话可能被判成已完成）：%s", e)


def _session_start(own: Path) -> float:
    try:
        return float((own / _SESSION).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


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
    """发起扫码，返回 (PNG 路径, 是否已在授权中)。同一用户并发点两次不会起两个进程。

    ⚠️ 这里有两个坑都是实测踩出来的（2026-10-30）：
      ① **不能先 unlink 再判断能否复用**。原先的顺序是"删图 → 看有没有活进程 → 有就等图"，
         而 `auth init` 只在启动时写一次 PNG、之后一直阻塞等扫码。于是用户点「重新获取」
         （旧进程还活着）时，图被删掉、等 20s 也长不回来，接口 400「二维码生成超时」——
         而二维码明明就在 20 秒前刚生成过。
      ② **会话起点只在真的起新进程时写**。复用同一进程时重写起点，会
         「刚扫完、前端还没轮到轮询」被判成未完成（凭据 mtime 早于新起点）。
    """
    d = profiles.ensure(tenant_id, user_id)
    png = qr_path(d)

    async with _lock(d):
        proc = _procs.get(str(d))
        if proc is not None and proc.returncode is None and png.is_file():
            # 进程在等扫码、图也在：直接复用。会话起点不动（见上面 ②）。
            return png, True
        if proc is not None and proc.returncode is None:
            # 进程还在但图没了（上一轮的图被删或前端已过期待重取）：必须换一个新进程。
            # 留着它等是没用的 —— 它这辈子不会再写第二张图。
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            _procs.pop(str(d), None)
            logger.info("旧扫码进程无图可用，已回收（tenant=%s user=%s）", tenant_id, user_id)
        try:
            png.unlink()          # 只在确定要起新进程时才删，避免毁掉还能用的图
        except OSError:
            pass
        # 先记会话起点，再起子进程：子进程写 credentials.enc 必然晚于此刻。
        _mark_session(d)
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


async def session_state(tenant_id, user_id) -> dict:
    """**本次扫码会话**是否真的完成 —— 只认本人目录，绝不碰共享兜底。

    返回 `{authorized, accountLabel, reason}`，`reason ∈ ok / no-session /
    no-credential / stale-credential / cli-unauthorized`。

    为什么不能复用 {@link status} + {@link profiles.resolve}（2026-10-30 线上实测）：
    `resolve()` 在本人目录没凭据时会回落到 `AIOS_WECOM_CLI_SHARED_PROFILE`，于是
    「用户刚点开二维码、一个像素都没扫」时 `auth show --status` 就已经回 authorized
    （读的是别人的凭据）⇒ 前端第一次轮询就调 `/qr-bind` ⇒ 库里落 CONNECTED、名字还是
    那个共享账号的。用户看到的正是「二维码自己扫码完成了」。

    所以完成的判据必须是三重的：**本人目录** + **凭据 mtime 晚于本次会话起点** +
    **CLI 自报 authorized**。三者缺一都算未完成。
    """
    own = profiles.dir_for(tenant_id, user_id)
    start = _session_start(own)
    if start <= 0:
        return {"authorized": False, "accountLabel": None, "reason": "no-session"}
    cred = profiles.cred_file(own)
    try:
        mtime = cred.stat().st_mtime
    except OSError:
        return {"authorized": False, "accountLabel": None, "reason": "no-credential"}
    if mtime <= start:
        return {"authorized": False, "accountLabel": None, "reason": "stale-credential"}
    if await status(own) != "authorized":
        return {"authorized": False, "accountLabel": None, "reason": "cli-unauthorized"}
    label = profiles.account_label(tenant_id, user_id)
    if not label:
        try:
            label = (await whoami(own)).get("userName")
        except runner.CliError:
            label = None
    return {"authorized": True, "accountLabel": label, "reason": "ok"}


async def bind(tenant_id, user_id) -> dict:
    """确认**本次扫码**已完成并取到显示名；成功返回 {accountLabel, botName, shared}。

    ⚠️ 判据是 {@link session_state}，不是 `profiles.resolve()`。用后者会出现「没扫码也
    能绑上、且绑成了别人」—— 共享兜底目录让授权态从一开始就是 true。
    """
    own = profiles.dir_for(tenant_id, user_id)
    st = await session_state(tenant_id, user_id)
    if not st["authorized"]:
        raise runner.CliError(_BIND_HINT.get(st["reason"], "企业微信尚未完成扫码授权"))
    names = await whoami(own)
    label = names.get("userName") or ""
    profiles.set_account_label(own, label)
    await finish(tenant_id, user_id)
    return {"accountLabel": label, "botName": names.get("botName"), "shared": False}
