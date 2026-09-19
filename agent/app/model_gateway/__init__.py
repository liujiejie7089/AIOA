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

    key: str            # 注册名：deepseek / dashscope / vllm / ollama / echo / minimax
    driver: str         # echo | openai_compatible
    base_url: str       # OpenAI 兼容根路径（不含 /chat/completions）
    model: str          # 请求体里的 model 名
    api_key_env: str    # api_key 所在环境变量名
    temperature: float = 0.3   # 采样温度（管理端可配；专家配置优先级更高）
    max_context: int = 0       # 最大上下文（token）；0=不限制

    def api_key(self) -> str:
        """运行期覆盖（管理端填写并推送下来的）优先，其次环境变量。

        两条来源都必须只读不落盘：管理端推送的 Key 仅存在于本进程内存。
        """
        override = _API_KEY_OVERRIDES.get(self.key, "").strip()
        if override:
            return override
        return os.getenv(self.api_key_env, "").strip()


# 内置注册表：base_url / model 均可被 {KEY}_BASE_URL / {KEY}_MODEL 覆盖
_REGISTRY_SPEC: dict[str, dict[str, object]] = {
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
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-Text-01",
        "api_key_env": "MINIMAX_API_KEY",
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
        base_url=str(os.getenv(f"{key.upper()}_BASE_URL", spec.get("base_url", "internal://echo"))),
        model=str(os.getenv(f"{key.upper()}_MODEL", spec.get("model", key))),
        api_key_env=str(spec.get("api_key_env", f"{key.upper()}_API_KEY")),
        temperature=float(spec.get("temperature", 0.3) or 0.3),
        max_context=int(spec.get("max_context", 0) or 0),
    )


class GatewayError(RuntimeError):
    """网关解析失败（未知且无法回退）。"""


# 内置键：全量下发时用于识别「管理端已删除」的模型（内置键不参与清理）
_BUILTIN_KEYS: set[str] = set(_REGISTRY_SPEC)

# 管理端下发的运行期覆盖：禁用集合、默认模型、内存态 API Key（V13 模型管理热加载）
_DISABLED_KEYS: set[str] = set()
_DEFAULT_OVERRIDE: str | None = None
# 管理端「手动添加模型」填写的 Key：只驻留本进程内存，不落盘、不写日志
_API_KEY_OVERRIDES: dict[str, str] = {}


def apply_overrides(entries: list[dict], default_key: str | None = None) -> int:
    """应用管理端「模型管理」下发的配置：更新/新增/禁用 provider，调整默认模型。

    entries: [{key, providerType, baseUrl, model, apiKeyEnv, apiKey, temperature, maxContext,
               enabled, isDefault}]
    返回应用的条数。管理端保存后调用，变更即时生效（无需重启 agent）。
    """
    global _DEFAULT_OVERRIDE
    applied = 0
    seen: set[str] = set()
    for entry in entries or []:
        key = str(entry.get("key") or "").strip().lower()
        if not key:
            continue
        seen.add(key)
        base_url = str(entry.get("baseUrl") or "").strip()
        if base_url and base_url != "internal://echo" or key == "echo":
            spec: dict[str, object] = {
                "base_url": base_url or _REGISTRY_SPEC.get(key, {}).get("base_url", "internal://echo"),
                "model": str(entry.get("model") or _REGISTRY_SPEC.get(key, {}).get("model", key)),
                "api_key_env": str(entry.get("apiKeyEnv") or _REGISTRY_SPEC.get(key, {}).get("api_key_env", f"{key.upper()}_API_KEY")),
            }
            # 温度 / 最大上下文：管理端配置了才覆盖，否则沿用注册表缺省（0.3 / 0=不限制）
            temp = entry.get("temperature")
            if temp not in (None, ""):
                try:
                    spec["temperature"] = float(temp)
                except (TypeError, ValueError):
                    logger.warning("provider '%s' temperature=%r 非法，忽略", key, temp)
            max_ctx = entry.get("maxContext")
            if max_ctx not in (None, ""):
                try:
                    spec["max_context"] = int(max_ctx)
                except (TypeError, ValueError):
                    logger.warning("provider '%s' maxContext=%r 非法，忽略", key, max_ctx)
            _REGISTRY_SPEC[key] = spec
        # 禁用集合与规格注册**解耦**：停用的模型也要先注册，
        # 否则「先保存（停用）→ 再点启动」这条主流程会因为模型未注册而永远校验失败。
        if entry.get("enabled") is False:
            _DISABLED_KEYS.add(key)
        else:
            _DISABLED_KEYS.discard(key)
        # 管理端填写的 Key 只进内存；传空串表示「清掉覆盖，回到环境变量」
        pushed_key = str(entry.get("apiKey") or "").strip()
        if pushed_key:
            _API_KEY_OVERRIDES[key] = pushed_key
        else:
            _API_KEY_OVERRIDES.pop(key, None)
        if entry.get("isDefault"):
            _DEFAULT_OVERRIDE = key
        applied += 1
    # 下发是全量的：不在本次列表里、又不是内置键的，就是管理端已删除的模型，
    # 必须一并清掉规格与内存 Key —— 否则删掉的模型还会被显式 model_ref 命中。
    for stale in list(_REGISTRY_SPEC):
        if stale not in seen and stale not in _BUILTIN_KEYS:
            _REGISTRY_SPEC.pop(stale, None)
            _API_KEY_OVERRIDES.pop(stale, None)
            _DISABLED_KEYS.discard(stale)
            logger.info("model '%s' removed from registry (deleted in admin)", stale)
    if default_key:
        _DEFAULT_OVERRIDE = str(default_key).strip().lower()
    logger.info("model overrides applied: %d entries, default=%s", applied, _DEFAULT_OVERRIDE or "unset")
    return applied


def get_provider(key: str) -> Provider | None:
    """按 key 直接取 provider，**忽略禁用集合**；未注册返回 None。

    连通性校验要能测「还没启用」的模型：resolve() 会把已禁用的 key 回退到默认，
    用它做校验会测到别的模型上。
    """
    k = (key or "").strip().lower()
    if k not in _REGISTRY_SPEC:
        return None
    return _build_provider(k)


def current_default_key() -> str:
    """当前生效的默认模型（管理端覆盖优先，其次环境变量 MODEL_DEFAULT）。"""
    return (_DEFAULT_OVERRIDE or settings.model_default or "echo").strip().lower()


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
            "temperature": p.temperature,
            "max_context": p.max_context,
        })
    return out
