# -*- coding: utf-8 -*-
"""wecom_cli —— 用官方 `wecom-cli` 接入企业微信（扫码绑定，一人一账号）。

与 `wecom/`（自建应用 OAuth + IMAP 邮箱）的关系见 `docs/64`：

- `wecom/`：管理员配 corpId/agentId/corpSecret，用户走网页授权。**卡在备案域名**（无域名就没有可信 IP）。
- `wecom_cli/`：不碰自建应用。用官方 CLI 的「机器人 + 真人扫码」通道，**本机扫码即用**，
  凭据按用户隔离在各自的 `WECOM_CLI_CONFIG_DIR` 里。

隔离模型（这是本包最要紧的一条）：
    一个用户 = 一个配置目录 = 一份 credentials.enc
因此「用户 A 的提问只会读到 A 自己绑定的企微数据」是由**目录**保证的，不是由参数保证的 ——
任何工具都不接受 tenant/user 入参，身份一律从 Authorization 解析后落到目录路径上。
"""

from . import catalog, profiles, runner  # noqa: F401
