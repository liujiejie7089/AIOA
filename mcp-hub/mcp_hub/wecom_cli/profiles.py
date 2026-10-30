# -*- coding: utf-8 -*-
"""按用户解析 CLI 配置目录（「一人一账号」的落地处）。

布局：
    <root>/<tenantId>/<userId>/personal/credentials.enc

- `root` 取 env `AIOS_WECOM_CLI_ROOT`，默认仓库根下 `data/wecom-cli`。
- 「已绑定」的判据是 **该目录里存在 credentials.enc**，不是内存标记、也不是数据库标记：
  文件在=真授权过，文件没了=已解绑。数据库只是它的投影（供 manifest 闸门读）。

开发态兜底（**生产必须不设**）：
    env `AIOS_WECOM_CLI_SHARED_PROFILE=<一个已授权的目录>`
    当该用户还没有自己的目录时复用它，并打警告。
    存在的理由：dev 机器上只有一个真人扫过码，没法凭空造出第二份授权；
    没有它就没法在本地验「提问→返回企微数据」这条链路。
    副作用很明确：多个用户会共用同一个人的企微身份 —— 所以它只允许在 mock/开发环境开。

⚠️ **它只影响「工具执行时到哪儿取凭据」，绝不影响「扫码绑定是否完成」**。
   扫码完成的判据在 `auth.session_state`：只看本人目录 + 凭据晚于本次会话起点。
   早先 `bind()` 用了本函数的 `resolve()`，于是共享目录里别人的凭据让「用户根本没扫码」
   也被判成已授权 —— 现象是二维码刚弹出来就自己跳到「已连接」，且绑成了别人的身份。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("mcp_hub.wecom_cli")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ROOT = _REPO_ROOT / "data" / "wecom-cli"
_CRED = "credentials.enc"

_shared_warned = False


class NotBound(RuntimeError):
    """该用户还没有绑定企业微信。文案要能直接给用户看（会原样进工具结果）。"""


def root() -> Path:
    return Path(os.environ.get("AIOS_WECOM_CLI_ROOT") or _DEFAULT_ROOT)


def dir_for(tenant_id, user_id) -> Path:
    # 用纯数字拼路径前先挡一下：调用方身份来自 Java，正常是数字主键；
    # 但 mock 身份（mock-tenant/mock-user）不是 —— 直接拼会造出一堆垃圾目录。
    return root() / _safe(tenant_id) / _safe(user_id)


def _safe(v) -> str:
    s = str(v).strip()
    if not s or not all(c.isalnum() or c in "-_" for c in s):
        raise NotBound(f"调用方身份不能用作目录名：{s!r}（企业微信绑定需要真实账号）")
    return s


def cli_dir(base: Path) -> Path:
    """CLI 真正读写的目录，即 `WECOM_CLI_CONFIG_DIR` 的值。

    实测（CLI 1.3.4）：`credentials.enc`、`.encryption_key`、`cache/` **直接**落在
    `WECOM_CLI_CONFIG_DIR` 下 —— CLI 不会自己再套一层 `personal/`。
    证据：把变量指向一个空目录，`auth show --status` 回 `unauthorized` 且目录里什么都不生成；
    指向 WorkBuddy 自己的 `.../wecom-cli/personal`（里面有 credentials.enc）回 `authorized`；
    指向它的上一级 `.../wecom-cli` 又回 `unauthorized`。

    因此本项目的布局 `.../<tenant>/<user>/personal/credentials.enc` 需要我们自己补这一层。
    但也要认得出「调用方直接给了 CLI 目录」的情况（`AIOS_WECOM_CLI_SHARED_PROFILE` 就是指向
    WorkBuddy 的 personal 目录），否则会套成 `personal/personal` 而永远判未授权。
    """
    if (base / _CRED).is_file():
        return base
    return base / "personal"


def cred_file(base: Path) -> Path:
    """该基目录下的凭据文件（自动补 `personal/` 那层）。**判断「真的授权过」只看这个文件。**"""
    return cli_dir(base) / _CRED


def is_authorized(base: Path) -> bool:
    return cred_file(base).is_file()


def resolve(tenant_id, user_id) -> tuple[Path, bool]:
    """返回 (配置目录, 是否用的共享兜底目录)。未绑定抛 NotBound。"""
    global _shared_warned
    mine = dir_for(tenant_id, user_id)
    if is_authorized(mine):
        return mine, False
    shared = (os.environ.get("AIOS_WECOM_CLI_SHARED_PROFILE") or "").strip()
    if shared:
        sp = Path(shared).expanduser()
        if is_authorized(sp):
            if not _shared_warned:
                logger.warning(
                    "正在使用共享企微授权目录（AIOS_WECOM_CLI_SHARED_PROFILE=%s）——"
                    "仅限开发/演示：多个用户会共用同一个人的企微身份，生产必须清空该变量", sp)
                _shared_warned = True
            return sp, True
    raise NotBound(
        "还没有绑定企业微信。请在「连接器 → 企业微信（扫码）」里点连接并扫码授权后再试。")


def ensure(tenant_id, user_id) -> Path:
    """为扫码准备目录（不要求已授权）。返回**基目录**，CLI 目录由 {@link cli_dir} 决定。"""
    d = dir_for(tenant_id, user_id)
    cd = d / "personal"
    cd.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(cd, 0o700)   # Windows 上无效但无害；POSIX 上必须
    except OSError:
        pass
    return d


def wipe(tenant_id, user_id) -> bool:
    """解绑：删掉该用户的整个目录（含 CLI 凭据）。返回是否真的删了东西。"""
    d = dir_for(tenant_id, user_id)
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return not d.exists()


def account_label(tenant_id, user_id) -> "str | None":
    """缓存下来的显示名（存在基目录的 label.txt，避免每次 whoami 都起子进程）。"""
    f = dir_for(tenant_id, user_id) / "label.txt"
    if not f.is_file():
        return None
    try:
        return f.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def set_account_label(d: Path, label: str) -> None:
    try:
        (d / "label.txt").write_text(label or "", encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        logger.info("写入 label.txt 失败（不影响使用）：%s", e)
