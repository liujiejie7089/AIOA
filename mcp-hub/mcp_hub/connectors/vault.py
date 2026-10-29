# -*- coding: utf-8 -*-
"""通用连接器凭证保险库（应用级凭据）。

与 wecom 的加密存储复用同一套东西：同一个 SQLite 文件、同一把 AES-256-GCM 密钥、
同一种 `enc:` 密文格式 —— 保证「一份备份能同时恢复企微与其它连接器的配置」。

表结构刻意做成 (tenant, connector, field) 的窄表，而不是每个连接器一张宽表：
- 新增连接器只登记 manifest，不动 DDL；
- 字段增删不需要迁移；
- 哨兵可以只扫这一个表断言「无明文」。

掩码纪律（与 Java ConnectorTenantConfigService 同口径）：
- GET 只回掩码；sensitive 字段只回「已配置」布尔；
- PUT 提交空串或掩码值 = 保留旧值，绝不把掩码当新值写库。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Iterable

from ..wecom import crypto, store

logger = logging.getLogger("mcp_hub.connectors")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def init() -> None:
    """建表。幂等；依赖 wecom store 已初始化（同一把密钥、同一个库文件）。"""
    global _conn
    with _lock:
        if _conn is not None:
            return
        path = store.db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS connector_credential (
                tenant_id      TEXT NOT NULL,
                connector_code TEXT NOT NULL,
                field          TEXT NOT NULL,
                value_enc      TEXT NOT NULL,
                updated_by     TEXT,
                updated_at     TEXT,
                PRIMARY KEY (tenant_id, connector_code, field)
            );
            """
        )
        conn.commit()
        _conn = conn


def _db() -> sqlite3.Connection:
    if _conn is None:
        init()
    assert _conn is not None
    return _conn


def _load(tenant_id: str, code: str) -> dict[str, str]:
    key = store.key()
    rows = _db().execute(
        "SELECT field, value_enc FROM connector_credential WHERE tenant_id=? AND connector_code=?",
        (str(tenant_id), code),
    ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        try:
            out[row["field"]] = crypto.decrypt(row["value_enc"], key)
        except crypto.CryptoError as e:
            logger.warning("[vault] %s/%s 字段 %s 解密失败：%s", tenant_id, code, row["field"], e)
    return out


async def get_values(tenant_id: str, code: str) -> dict[str, str]:
    """取明文（仅服务端内部使用，绝不直接返回给 HTTP 层）。"""
    return await asyncio.to_thread(lambda: _load(str(tenant_id), code))


def _is_masked_or_blank(v: str | None) -> bool:
    if v is None:
        return True
    s = v.strip()
    return s == "" or "*" in s or "•" in s


async def put_values(tenant_id: str, code: str, values: dict[str, str],
                     updated_by: str = "", required: Iterable[str] = ()) -> dict[str, str]:
    """保存。空串/掩码值 ⇒ 保留旧值；required 中任一项最终为空 ⇒ 抛 ValueError。"""
    tenant_id = str(tenant_id)

    def _work() -> dict[str, str]:
        key = store.key()
        old = _load(tenant_id, code)
        merged: dict[str, str] = dict(old)
        for k, v in (values or {}).items():
            if _is_masked_or_blank(v):
                continue
            merged[k] = v.strip()

        missing = [k for k in required if not merged.get(k)]
        if missing:
            raise ValueError("以下字段必填：" + "、".join(missing))

        now = _utcnow()
        conn = _db()
        with conn:
            for k, v in merged.items():
                conn.execute(
                    "INSERT INTO connector_credential (tenant_id, connector_code, field, value_enc, updated_by, updated_at)"
                    " VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(tenant_id, connector_code, field) DO UPDATE SET"
                    " value_enc=excluded.value_enc, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                    (tenant_id, code, k, crypto.encrypt(v, key), updated_by, now),
                )
        logger.info("[vault] 连接器凭据已保存 tenant=%s code=%s fields=%s by=%s",
                    tenant_id, code, sorted(merged), updated_by)
        return merged

    return await asyncio.to_thread(_work)


async def clear(tenant_id: str, code: str) -> int:
    tenant_id = str(tenant_id)

    def _work() -> int:
        conn = _db()
        with conn:
            cur = conn.execute(
                "DELETE FROM connector_credential WHERE tenant_id=? AND connector_code=?",
                (tenant_id, code),
            )
        logger.info("[vault] 连接器凭据已清除 tenant=%s code=%s rows=%d", tenant_id, code, cur.rowcount)
        return cur.rowcount

    return await asyncio.to_thread(_work)


def mask_view(values: dict[str, str], fields: list[dict]) -> dict:
    """按 schema 生成掩码视图：sensitive 只回布尔，其余回前 4 位掩码。"""
    out: dict[str, object] = {}
    for f in fields:
        name = f["name"]
        v = values.get(name, "")
        if f.get("sensitive"):
            out[name] = ""
            out[f"{name}Set"] = bool(v)
        else:
            out[name] = crypto.mask(v, keep=4) if v else ""
    return out
