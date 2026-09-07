"""模型网关（M1 桩）：解析 model_ref → provider 配置。

M2 在此接入真实 chat/completions 调用（openai_compatible driver），
对外接口 `resolve()` 保持不变。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.config import settings

CONFIG_PATH = Path(__file__).with_name("providers.yaml")


class ProviderConfig(BaseModel):
    """单个 provider 的配置项。"""

    key: str
    type: str = "cloud"
    driver: str = "openai_compatible"
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    enabled: bool = False
    remark: str = ""

    def api_key(self) -> str:
        """从环境变量取密钥（密钥不入库）。"""
        return os.getenv(self.api_key_env, "") if self.api_key_env else ""


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _default_ref() -> str:
    """默认模型引用：env MODEL_DEFAULT 优先，其次 yaml 的 default_chat。"""
    return settings.model_default or _load_raw().get("default_chat") or "echo"


def resolve(model_ref: str | None = None) -> ProviderConfig:
    """解析模型引用为 provider 配置；未知引用回退到默认。"""
    raw = _load_raw()
    providers: dict = raw.get("providers") or {}
    ref = model_ref or _default_ref()
    cfg = providers.get(ref)
    if cfg is None:
        ref = _default_ref()
        cfg = providers.get(ref) or {}
    return ProviderConfig(key=ref, **cfg)


def default_ref() -> str:
    """当前默认模型引用。"""
    return _default_ref()
