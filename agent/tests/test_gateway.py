"""模型网关解析规则单元测试（不依赖网络与真实 key）。

覆盖：
  - 未指定 model_ref -> MODEL_DEFAULT（echo）
  - 显式指定已注册 provider 且无 key -> 原样返回（由上层报未配置错误）
  - 显式未知 ref -> 回退默认
  - 隐式默认指向 openai_compatible 但缺 key -> 自动降级 echo
  - 隐式默认指向未知 key -> 回退 echo
"""
from __future__ import annotations

import os

from app.config import settings
from app.model_gateway import resolve


def _no_keys(monkeypatch):
    for k in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "VLLM_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_default_is_echo(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve(None)
    assert p.driver == "echo"
    assert p.model == "echo"


def test_explicit_provider_without_key_kept(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("deepseek")
    assert p.key == "deepseek"          # 不降级，由 agent_runtime 报干净错误
    assert p.driver == "openai_compatible"
    assert p.api_key() == ""


def test_unknown_ref_falls_back(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("no-such-provider")
    assert p.key == "echo"


def test_implicit_default_without_key_degrades_to_echo(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "deepseek")
    p = resolve(None)                   # 隐式默认 deepseek 但无 key -> echo
    assert p.key == "echo"
    assert p.driver == "echo"


def test_implicit_default_unknown_degrades_to_echo(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "who-am-i")
    p = resolve(None)
    assert p.key == "echo"


def test_explicit_with_key_used(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("deepseek")
    assert p.key == "deepseek"
    assert p.model == os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    assert p.api_key() == "test-key"


# ---------- 运行期凭证（2026-11-03，docs/71 §6） ----------

def test_credential_overrides_base_url_model_and_key(monkeypatch):
    """用户自带账号：base_url / model / api_key 三项全部以凭证为准。"""
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("deepseek", credential={
        "credentialId": 7, "providerKey": "deepseek",
        "baseUrl": "https://api.deepseek.com/v2", "model": "deepseek-reasoner",
        "apiKey": "sk-mine", "ownerType": "PERSONAL",
    })
    assert p.key == "deepseek"
    assert p.base_url == "https://api.deepseek.com/v2"
    assert p.model == "deepseek-reasoner"
    assert p.api_key() == "sk-mine"


def test_credential_falls_back_to_registry_for_missing_fields(monkeypatch):
    """凭证只填 Key：base_url / model 回落注册表，不能因为少填就打成空。"""
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("deepseek", credential={"apiKey": "sk-mine"})
    assert p.base_url == os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    assert p.model == "deepseek-chat"


def test_credential_without_api_key_is_ignored(monkeypatch):
    """凭证没配 Key（只选了口径）：忽略它，按注册表解析，行为与改动前一致。"""
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("deepseek", credential={"credentialId": 7, "providerKey": "deepseek"})
    assert p.api_key() == ""
    assert p.base_url == os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def test_credential_beats_admin_pushed_key(monkeypatch):
    """凭证优先于管理端推送的平台 Key：用户自己配的账号被平台 Key 顶掉等于白配。"""
    from aios_ai import llm as llm_pkg
    llm_pkg._API_KEY_OVERRIDES["deepseek"] = "sk-platform"
    try:
        monkeypatch.setattr(settings, "model_default", "echo")
        p = resolve("deepseek", credential={"apiKey": "sk-mine"})
        assert p.api_key() == "sk-mine"
    finally:
        llm_pkg._API_KEY_OVERRIDES.pop("deepseek", None)


def test_credential_does_not_leak_into_registry(monkeypatch):
    """凭证只作用于本次 Provider 对象：下一个用户不能捡到上一个用户的 Key。"""
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    resolve("deepseek", credential={"apiKey": "sk-mine", "baseUrl": "https://x.example"})
    p2 = resolve("deepseek")
    assert p2.api_key() == ""
    assert p2.base_url == os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def test_credential_switches_provider_when_key_differs(monkeypatch):
    """凭证指向另一个 provider（ref=dashscope、凭证是 deepseek）：跟着凭证走，
    否则会把 A 供应商的 Key 打到 B 供应商的 base_url 上。"""
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "model_default", "echo")
    p = resolve("dashscope", credential={"providerKey": "deepseek", "apiKey": "sk-mine"})
    assert p.key == "deepseek"
    assert p.base_url == os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
