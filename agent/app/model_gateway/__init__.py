"""模型网关：provider 解析与配置（M2）。

统一模型网关双模式（设计：架构第 3/4 层）：
  - 云端 API：DeepSeek / 通义百炼（OpenAI 兼容协议）
  - 私有化：本地 vLLM / Ollama（OpenAI 兼容协议）
  - echo：本地回声（开发与离线演示兜底）

provider 注册表内置，全部参数可经环境变量覆盖（{KEY}_API_KEY / {KEY}_BASE_URL / {KEY}_MODEL）；
敏感凭据只走环境变量或 agent/.env（不入库、不入 git）。

解析规则（resolve）：
  1. model_ref 未指定 -> 取 MODEL_DEFAULT（默认 echo）
  2. 显式指定的未知 ref -> 记警告并回退默认，保证服务可用
  3. 隐式默认（model_ref 为空）解析到 openai_compatible 且未配 api_key ->
     自动降级 echo（服务可用性优先，日志可见）
  4. 显式指定 openai_compatible 但缺 api_key -> 原样返回，
     由 agent_runtime 产出 MODEL_PROVIDER_NOT_CONFIGURED 干净错误事件
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger("aioa.agent.gateway")


@dataclass(frozen=True)
class Provider:
    """一个可调用模型的接入描述。"""

    key: str            # 注册名：deepseek / dashscope / vllm / ollama / echo
    driver: str         # echo | openai_compatible
    base_url: str       # OpenAI 兼容根路径（不含 /chat/completions）
    model: str          # 请求体里的 model 名
    api_key_env: str    # api_key 所在环境变量名

    def api_key(self) -> str:
        """实时读取环境变量（便于测试注入与运行期改配）。"""
        return os.getenv(self.api_key_env, "").strip()


# 内置注册表：base_url / model 均可被 {KEY}_BASE_URL / {KEY}_MODEL 覆盖
_REGISTRY_SPEC: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "vllm": {
        "base_url": "http://127.0.0.1:8001/v1",
        "model": "Qwen2.5-7B-Instruct",
        "api_key_env": "VLLM_API_KEY",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "api_key_env": "OLLAMA_API_KEY",
    },
    "echo": {
        "base_url": "internal://echo",
        "model": "echo",
        "api_key_env": "ECHO_API_KEY",
    },
}


def _build_provider(key: str) -> Provider:
    spec = _REGISTRY_SPEC[key]
    return Provider(
        key=key,
        driver="echo" if key == "echo" else "openai_compatible",
        base_url=os.getenv(f"{key.upper()}_BASE_URL", spec["base_url"]),
        model=os.getenv(f"{key.upper()}_MODEL", spec["model"]),
        api_key_env=spec["api_key_env"],
    )


class GatewayError(RuntimeError):
    """网关解析失败（未知且无法回退）。"""


# 管理端下发的运行期覆盖：禁用集合与默认模型（V13 模型管理热加载）
_DISABLED_KEYS: set[str] = set()
_DEFAULT_OVERRIDE: str | None = None


def apply_overrides(entries: list[dict], default_key: str | None = None) -> int:
    """应用管理端「模型管理」下发的配置：更新/新增/禁用 provider，调整默认模型。

    entries: [{key, baseUrl, model, apiKeyEnv, enabled, isDefault}]
    返回应用的条数。管理端保存后调用，变更即时生效（无需重启 agent）。
    """
    global _DEFAULT_OVERRIDE
    applied = 0
    for entry in entries or []:
        key = str(entry.get("key") or "").strip().lower()
        if not key:
            continue
        if entry.get("enabled") is False:
            _DISABLED_KEYS.add(key)
            applied += 1
            continue
        _DISABLED_KEYS.discard(key)
        base_url = str(entry.get("baseUrl") or "").strip()
        if base_url and base_url != "internal://echo" or key == "echo":
            _REGISTRY_SPEC[key] = {
                "base_url": base_url or _REGISTRY_SPEC.get(key, {}).get("base_url", "internal://echo"),
                "model": str(entry.get("model") or _REGISTRY_SPEC.get(key, {}).get("model", key)),
                "api_key_env": str(entry.get("apiKeyEnv") or _REGISTRY_SPEC.get(key, {}).get("api_key_env", f"{key.upper()}_API_KEY")),
            }
        if entry.get("isDefault"):
            _DEFAULT_OVERRIDE = key
        applied += 1
    if default_key:
        _DEFAULT_OVERRIDE = str(default_key).strip().lower()
    logger.info("model overrides applied: %d entries, default=%s", applied, _DEFAULT_OVERRIDE or "unset")
    return applied


def resolve(model_ref: str | None = None) -> Provider:
    """按 model_ref 解析 provider；未指定时走默认，必要时降级 echo。"""
    default_key = (_DEFAULT_OVERRIDE or settings.model_default or "echo").strip().lower()
    ref = (model_ref or "").strip().lower()
    explicit = bool(ref)

    if ref and (ref not in _REGISTRY_SPEC or ref in _DISABLED_KEYS):
        logger.warning("unknown/disabled model_ref '%s', fallback to default '%s'", ref, default_key)
        ref = default_key
        explicit = False
    if not ref or ref in _DISABLED_KEYS:
        ref = default_key
    if ref not in _REGISTRY_SPEC or ref in _DISABLED_KEYS:
        logger.warning("default '%s' unavailable, fallback to echo", ref)
        ref = "echo"

    provider = _build_provider(ref)
    if provider.driver != "echo" and not provider.api_key():
        if explicit:
            # 显式点名却缺 key：交由 agent_runtime 产出干净的未配置错误
            return provider
        # 隐式默认缺 key：静默降级 echo，保证会话链路始终可用
        logger.warning(
            "provider '%s' has no api_key (env %s unset), fallback to echo",
            ref, provider.api_key_env,
        )
        return _build_provider("echo")
    return provider


def configured_providers() -> list[dict[str, str]]:
    """运维观测：当前注册表与各 provider 配置状态（key 只暴露「是否已配置」）。"""
    out: list[dict[str, str]] = []
    for key in _REGISTRY_SPEC:
        p = _build_provider(key)
        out.append({
            "key": p.key,
            "driver": p.driver,
            "model": p.model,
            "api_key_configured": "yes" if p.api_key() else "no",
        })
    return out
