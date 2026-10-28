# -*- coding: utf-8 -*-
"""SQLite 持久化：租户配置 / 用户连接态 / OAuth 一次性 state。

设计约束：
- 单文件 SQLite（默认 mcp-hub/data/wecom.db，可用 WECOM_DB_PATH 覆盖），data/ 不进 git。
- 所有凭据字段（corp_secret、client_password、access_token、user_ticket）一律 enc: 密文落库；
  库里不允许出现明文凭据（哨兵 S8 直接扫库文件字节断言）。
- 连接态主键 (tenant_id, user_id)；软删不适用——断开即物理删除，避免唯一键被占位
  （Java 侧 uk 不含 deleted_at 的坑在这里重演一遍没有意义）。
- sqlite3 连接跨线程共用，全部操作经 asyncio.to_thread + 进程内 Lock 串行化。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

from . import crypto
from .models import (
    MODE_A,
    MODE_AB,
    MODE_B,
    STATE_TTL_MINUTES,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    Connection,
    TenantConfig,
)

logger = logging.getLogger("mcp_hub.wecom")

_DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "wecom.db")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()
_key: bytes | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _db_path() -> str:
    return os.environ.get("WECOM_DB_PATH", _DEFAULT_DB)


def is_mock() -> bool:
    """mock 开关：默认关闭；显式 WECOM_MOCK=1 才开（哨兵与本地联调用）。"""
    return os.environ.get("WECOM_MOCK", "0") == "1"


def init() -> None:
    """建表 + 取密钥。幂等；启动时调用一次。"""
    global _conn, _key
    with _lock:
        if _conn is not None:
            return
        path = _db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wecom_tenant_config (
                tenant_id   TEXT PRIMARY KEY,
                corp_id     TEXT NOT NULL,
                corp_secret TEXT NOT NULL,
                agent_id    TEXT NOT NULL,
                redirect_uri TEXT,
                updated_by  TEXT,
                updated_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS wecom_connection (
                tenant_id     TEXT NOT NULL,
                user_id       TEXT NOT NULL,
                mode          TEXT NOT NULL,
                status        TEXT NOT NULL,
                a_credential  TEXT,
                b_credential  TEXT,
                account_label TEXT,
                created_at    TEXT,
                updated_at    TEXT,
                PRIMARY KEY (tenant_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS wecom_oauth_state (
                state      TEXT PRIMARY KEY,
                tenant_id  TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                mode       TEXT NOT NULL,
                payload    TEXT,
                created_at TEXT,
                expires_at TEXT,
                consumed   INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_wecom_state_expires ON wecom_oauth_state(expires_at);
            """
        )
        conn.commit()
        _conn = conn
        _key = crypto.load_key(mock=is_mock())


def key() -> bytes:
    if _key is None:
        init()
    assert _key is not None
    return _key


def _enc_json(obj: dict) -> str:
    return crypto.encrypt(json.dumps(obj, ensure_ascii=False), key())


def _dec_json(token: str | None) -> dict | None:
    if not token:
        return None
    return json.loads(crypto.decrypt(token, key()))


# ---------- 租户配置 ----------


async def get_tenant_config(tenant_id: str) -> TenantConfig | None:
    def _q():
        row = _conn.execute(
            "SELECT * FROM wecom_tenant_config WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        return row

    row = await asyncio.to_thread(_q)
    if row is None:
        return None
    return TenantConfig(
        tenant_id=row["tenant_id"],
        corp_id=crypto.decrypt(row["corp_id"], key()),
        corp_secret=crypto.decrypt(row["corp_secret"], key()),
        agent_id=crypto.decrypt(row["agent_id"], key()),
        redirect_uri=row["redirect_uri"],
        updated_by=row["updated_by"],
    )


async def upsert_tenant_config(
    tenant_id: str, corp_id: str, corp_secret: str, agent_id: str,
    redirect_uri: str | None, updated_by: str,
) -> None:
    def _w():
        _conn.execute(
            """
            INSERT INTO wecom_tenant_config
                (tenant_id, corp_id, corp_secret, agent_id, redirect_uri, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id) DO UPDATE SET
                corp_id=excluded.corp_id, corp_secret=excluded.corp_secret,
                agent_id=excluded.agent_id, redirect_uri=excluded.redirect_uri,
                updated_by=excluded.updated_by, updated_at=excluded.updated_at
            """,
            (
                tenant_id,
                crypto.encrypt(corp_id, key()),
                crypto.encrypt(corp_secret, key()),
                crypto.encrypt(agent_id, key()),
                redirect_uri,
                updated_by,
                _utcnow(),
            ),
        )
        _conn.commit()

    await asyncio.to_thread(_w)


# ---------- 用户连接态 ----------


async def get_connection(tenant_id: str, user_id: str) -> Connection | None:
    def _q():
        return _conn.execute(
            "SELECT * FROM wecom_connection WHERE tenant_id = ? AND user_id = ?",
            (tenant_id, user_id),
        ).fetchone()

    row = await asyncio.to_thread(_q)
    if row is None:
        return None
    return Connection(
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        mode=row["mode"],
        status=row["status"],
        account_label=row["account_label"],
        a_credential=_dec_json(row["a_credential"]),
        b_credential=_dec_json(row["b_credential"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def save_connection(conn: Connection) -> None:
    def _w():
        now = _utcnow()
        _conn.execute(
            """
            INSERT INTO wecom_connection
                (tenant_id, user_id, mode, status, a_credential, b_credential,
                 account_label, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, user_id) DO UPDATE SET
                mode=excluded.mode, status=excluded.status,
                a_credential=excluded.a_credential, b_credential=excluded.b_credential,
                account_label=excluded.account_label, updated_at=excluded.updated_at
            """,
            (
                conn.tenant_id,
                conn.user_id,
                conn.mode,
                conn.status,
                _enc_json(conn.a_credential) if conn.a_credential else None,
                _enc_json(conn.b_credential) if conn.b_credential else None,
                conn.account_label,
                now,
                now,
            ),
        )
        _conn.commit()

    await asyncio.to_thread(_w)


async def delete_connection(tenant_id: str, user_id: str) -> None:
    def _w():
        _conn.execute(
            "DELETE FROM wecom_connection WHERE tenant_id = ? AND user_id = ?",
            (tenant_id, user_id),
        )
        _conn.commit()

    await asyncio.to_thread(_w)


# ---------- OAuth 一次性 state ----------


async def issue_state(tenant_id: str, user_id: str, mode: str, payload: dict) -> str:
    state = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=STATE_TTL_MINUTES)

    def _w():
        _conn.execute(
            """
            INSERT INTO wecom_oauth_state
                (state, tenant_id, user_id, mode, payload, created_at, expires_at, consumed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (state, tenant_id, user_id, mode, json.dumps(payload, ensure_ascii=False),
             now.isoformat(timespec="milliseconds"), expires.isoformat(timespec="milliseconds")),
        )
        _conn.commit()

    await asyncio.to_thread(_w)
    return state


async def consume_state(state: str) -> dict | None:
    """一次性消费：未消费且未过期才返回 payload，同时置 consumed（防重放）。"""

    def _w():
        row = _conn.execute(
            "SELECT * FROM wecom_oauth_state WHERE state = ?", (state,)
        ).fetchone()
        if row is None or row["consumed"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        _conn.execute("UPDATE wecom_oauth_state SET consumed = 1 WHERE state = ?", (state,))
        _conn.commit()
        return {"tenant_id": row["tenant_id"], "user_id": row["user_id"],
                "mode": row["mode"], "payload": json.loads(row["payload"] or "{}")}

    return await asyncio.to_thread(_w)


async def purge_expired_states() -> int:
    def _w():
        cur = _conn.execute(
            "DELETE FROM wecom_oauth_state WHERE expires_at < ?", (_utcnow(),)
        )
        _conn.commit()
        return cur.rowcount

    return await asyncio.to_thread(_w)


# ---------- 连接态辅助操作（供 server.py 使用） ----------


def split_modes(mode: str | None) -> list[str]:
    """连接态模式串 → 基础模式列表。"AB" → ["A","B"]（唯一解析口径，各处共用）。"""
    if not mode:
        return []
    if mode == MODE_AB:
        return [MODE_A, MODE_B]
    return [mode]


def merge_mode(existing: str | None, add: str) -> str:
    """把新模式合并进已有连接态：A+B → AB。"""
    have = set(split_modes(existing))
    have.add(add)
    return MODE_AB if len(have) > 1 else next(iter(have))


def drop_mode(existing: str, remove: str) -> str | None:
    """从连接态里摘掉一个模式；返回 None 表示两个模式都没了（应删行）。"""
    parts = [p for p in split_modes(existing) if p != remove]
    if not parts:
        return None
    return MODE_AB if len(parts) > 1 else parts[0]


async def ensure_connection(tenant_id: str, user_id: str) -> Connection:
    conn = await get_connection(tenant_id, user_id)
    if conn is None:
        # mode 空串：尚未绑定任何模式，由 merge_mode 按实际绑定写入
        conn = Connection(tenant_id=tenant_id, user_id=user_id, mode="",
                          status=STATUS_DISCONNECTED)
    return conn


def connected_modes(conn: Connection | None) -> list[str]:
    if conn is None or conn.status != STATUS_CONNECTED:
        return []
    return split_modes(conn.mode)
