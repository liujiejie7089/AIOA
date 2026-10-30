# -*- coding: utf-8 -*-
"""连接器共享 SQLite 底座：库文件路径 + 主密钥。

<b>这里不存业务数据</b>。原来的租户配置 / 用户连接态 / OAuth 一次性 state 三张表
（{@code wecom_tenant_config} / {@code wecom_connection} / {@code wecom_oauth_state}）
随旧企微通道一并删除（2026-10-30，见 docs/64 §9.7）。

保留职责只有两件，且都必须先于任何加密读写完成：
1. 决定库文件位置（默认 `mcp-hub/data/wecom.db`，可用 `WECOM_DB_PATH` 覆盖；data/ 不进 git）；
2. 取 AES-256-GCM 主密钥 —— **生产缺密钥在这里 fail fast**，不让服务带着空密钥起来。

`connectors/vault.py` 复用同一个库文件与同一把密钥，保证「一份备份同时恢复全部连接器凭据」。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading

from . import crypto

logger = logging.getLogger("mcp_hub.wecom")

_DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "wecom.db")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()
_key: bytes | None = None


def _db_path() -> str:
    return os.environ.get("WECOM_DB_PATH", _DEFAULT_DB)


def db_path() -> str:
    """公开别名：通用连接器凭证库（connectors/vault.py）复用同一个 SQLite 文件与同一把密钥。"""
    return _db_path()


def is_mock() -> bool:
    """mock 开关：默认关闭；显式 WECOM_MOCK=1 才开（哨兵与本地联调用）。"""
    return os.environ.get("WECOM_MOCK", "0") == "1"


def init() -> None:
    """打开库文件 + 取密钥。幂等；启动时调用一次。

    仍然建库文件（而不是懒打开），是为了让「目录不可写 / 密钥缺失」在启动阶段就暴露，
    而不是等到用户第一次点连接才报错。
    """
    global _conn, _key
    with _lock:
        if _conn is not None:
            return
        path = _db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _conn = conn
        _key = crypto.load_key(mock=is_mock())


def key() -> bytes:
    if _key is None:
        init()
    assert _key is not None
    return _key
