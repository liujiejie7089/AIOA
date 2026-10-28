# -*- coding: utf-8 -*-
"""AES-256-GCM 加密封装。

格式与 Java SecretCodec 一致：`enc:` + base64(nonce(12) + ciphertext+tag)，
便于两套实现互相导出口径（Python 加密的串 Java 能解，反之亦然——只要同 key）。

密钥来源：环境变量 WECOM_CONNECTOR_KEY（base64，解码后须 32 字节）。
- 生产（WECOM_MOCK=0）：缺失即启动失败（fail fast，绝不静默用临时密钥）。
- 开发（WECOM_MOCK=1）：缺失时生成进程内临时密钥并大声告警（重启后旧数据不可解，仅限联调）。
"""

from __future__ import annotations

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("mcp_hub.wecom")

KEY_ENV = "WECOM_CONNECTOR_KEY"
PREFIX = "enc:"
_NONCE_BYTES = 12

_ephemeral_key: bytes | None = None


class CryptoError(RuntimeError):
    pass


def _from_env() -> bytes | None:
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as e:
        raise CryptoError(f"{KEY_ENV} 不是合法 base64：{e}") from e
    if len(key) != 32:
        raise CryptoError(f"{KEY_ENV} 解码后须为 32 字节，实际 {len(key)}")
    return key


def load_key(mock: bool) -> bytes:
    """取加密密钥。mock=true 允许临时密钥；mock=false 缺失即抛错。"""
    global _ephemeral_key
    key = _from_env()
    if key is not None:
        return key
    if mock:
        if _ephemeral_key is None:
            _ephemeral_key = AESGCM.generate_key(bit_length=256)
            logger.warning(
                "[wecom] %s 未设置，已生成进程内临时密钥（重启后旧密文不可解，仅限开发联调）", KEY_ENV
            )
        return _ephemeral_key
    raise CryptoError(f"生产模式必须设置 {KEY_ENV}（base64 编码的 32 字节密钥）")


def generate_key_b64() -> str:
    """生成一把新密钥的 base64 串（供部署时一次性产出）。"""
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()


def encrypt(plaintext: str, key: bytes) -> str:
    if plaintext is None:
        raise CryptoError("encrypt 不接受 None")
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str, key: bytes) -> str:
    if not token or not token.startswith(PREFIX):
        raise CryptoError("不是 enc: 格式的密文")
    try:
        blob = base64.b64decode(token[len(PREFIX):], validate=True)
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
    except CryptoError:
        raise
    except Exception as e:
        raise CryptoError(f"解密失败（密钥不匹配或数据损坏）：{type(e).__name__}") from e


def is_encrypted(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def mask(value: str | None, keep: int = 2) -> str:
    """掩码视图：保留前 keep 位，其余打星。空值返回空串（不泄露'是否已配置'以外的信息由 configured 字段承担）。"""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)
