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
