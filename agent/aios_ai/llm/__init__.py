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

 运行期凭证（2026-11-03，docs/71）：resolve(credential=...) 可把**用户自己注册的账号**
 覆盖到本次调用上（base_url / model / api_key 三项）。它只作用于返回的 Provider 对象，
 不写全局注册表、不落盘 —— 否则下一个用户的 run 会被上一个用户的 Key 污染。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from aios_ai.config import settings

logger = logging.getLogger("aios.agent.gateway")


@dataclass(frozen=True)
class Provider:
    """一个可调用模型的接入描述。

    2026-11-04（docs/72）：采样与传输参数从「两个」扩到「九个」，
    两端（平台模型 / 用户模型账号）字段同名同义，换厂家新模型只改 model 名即可。
    """

    key: str            # 注册名：deepseek / dashscope / vllm / ollama / echo / minimax
    driver: str         # echo | openai_compatible
    base_url: str       # OpenAI 兼容根路径（不含 /chat/completions）
    model: str          # 请求体里的 model 名
    api_key_env: str    # api_key 所在环境变量名
    temperature: float = 0.3   # 采样温度（管理端可配；专家配置优先级更高）
    max_context: int = 0       # 最大上下文（token）；0=不限制
    # ---- 采样参数（None / 0 = 不下发，沿用供应商默认） ----
    top_p: float | None = None
    max_tokens: int = 0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    # ---- 传输参数 ----
    timeout_seconds: int = 120  # 单次上游请求超时
    retry_attempts: int = 3     # 总尝试次数（含首次）；仅对可重试错误生效
    stream_enabled: bool = True # 关掉后走非流式（兼容不支持 SSE 的网关）
    # 运行期凭证（2026-11-03，docs/71）：用户自己注册的模型账号，随本次请求下发。
    # 只存在于本对象里（内存），不写任何全局状态、不落盘 —— 否则会污染后续别人的 run。
    api_key_value: str = ""

    def api_key(self) -> str:
        """本次运行用的 Key。

        优先级：**本对象的运行期凭证**（用户自己注册的账号）> 管理端推送的平台 Key
        > 环境变量。

        凭证排在管理端 Key 之前：平台 Key 是「默认通道」，用户显式配了自己的账号
        是更明确的意图，被平台 Key 顶掉等于用户白配一次（docs/71 §6）。

        三条来源都必须只读不落盘：管理端推送的 Key 仅存在于本进程内存，
        用户凭证只存在于本次请求的 Provider 对象里。
        """
        if self.api_key_value:
            return self.api_key_value
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
        # 2026-11-04：MiniMax-Text-01 已被厂商下线（/models 返回 404），这里只作为
        # 「库里没配模型名」时的最后默认值，必须与 PlatformConfig/ModelConfigService 的预设同源。
        "model": "MiniMax-M3.1-Flash",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "echo": {
        "base_url": "internal://echo",
        "model": "echo",
        "api_key_env": "ECHO_API_KEY",
    },
}


# ---------- 参数规范化（两端同一套范围，非法值一律不落进注册表） ----------

#: 采集参数范围：(最小, 最大, 默认)。与 Java 侧 ModelConfigController / ModelCredentialService 同源。
PARAM_RANGES: dict[str, tuple[float, float, float]] = {
    "temperature": (0.0, 2.0, 0.3),
    "topP": (0.0, 1.0, 0.0),          # 0 视为「未设置」⇒ 不下发
    "maxTokens": (0, 65536, 0),
    "maxContext": (0, 1048576, 0),
    "presencePenalty": (-2.0, 2.0, 0.0),
    "frequencyPenalty": (-2.0, 2.0, 0.0),
    "timeoutSeconds": (5, 600, 120),
    "retryAttempts": (1, 5, 3),
}


def _clamp_num(raw: object, name: str) -> float | None:
    """把下发值转成范围内的数字；None/空串返回 None（表示「未设置」）。

    越界不抛错而是**拒绝整条配置**（见 apply_overrides）：静默截断会让
    「管理端填 5.0 的温度」变成悄悄用 2.0 跑，运维以为配上了。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    lo, hi, _ = PARAM_RANGES[name]
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name}={raw!r} 不是数字")
    if v < lo or v > hi:
        raise ValueError(f"{name}={v} 超出范围 {lo:g}~{hi:g}")
    return v


def _build_provider(key: str) -> Provider:
    spec = _REGISTRY_SPEC[key]
    # 优先级（2026-11-04 修正）：**管理端下发的配置 > 环境变量 > 内置默认**。
    #
    # 旧实现无条件读 {KEY}_MODEL 环境变量，导致「管理端把模型名改成 deepseek-reasoner
    # 保存后仍然跑 deepseek-chat」（.env 里有同名变量），用户看到的配置与生效值不一致。
    # 现在给下发过的 spec 打 _from_admin 标记：管理员显式保存的就是最终值，
    # 只有从未被管理端配置过的 provider 才继续吃环境变量（纯 env 部署仍然可用）。
    from_admin = bool(spec.get("_from_admin"))
    temp = spec.get("temperature")
    max_ctx = spec.get("max_context")
    top_p = spec.get("top_p")
    max_tokens = spec.get("max_tokens")

    def _env_or_spec(field: str, env_name: str, fallback):
        if from_admin and spec.get(field) not in (None, ""):
            return spec.get(field)
        return os.getenv(env_name, spec.get(field, fallback))

    return Provider(
        key=key,
        driver="echo" if key == "echo" else "openai_compatible",
        base_url=str(_env_or_spec("base_url", f"{key.upper()}_BASE_URL", "internal://echo")),
        model=str(_env_or_spec("model", f"{key.upper()}_MODEL", key)),
        api_key_env=str(spec.get("api_key_env", f"{key.upper()}_API_KEY")),
        # 注意：不能用 `or 0.3`——温度 0 是合法配置（完全确定输出），会被误吞成默认值
        temperature=float(0.3 if temp is None else temp),
        max_context=int(0 if max_ctx is None else max_ctx),
        top_p=(None if top_p in (None, "") else float(top_p)),
        max_tokens=int(0 if max_tokens is None else max_tokens),
        presence_penalty=float(spec.get("presence_penalty") or 0.0),
        frequency_penalty=float(spec.get("frequency_penalty") or 0.0),
        timeout_seconds=int(spec.get("timeout_seconds") or 120),
        retry_attempts=int(spec.get("retry_attempts") or 3),
        stream_enabled=bool(spec.get("stream_enabled", True)),
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


def _spec_of(key: str, entry: dict) -> dict:
    """由一条下发配置算出它的注册表规格；非法值抛 ValueError（调用方整条拒绝）。"""
    base_url = str(entry.get("baseUrl") or "").strip()
    old = _REGISTRY_SPEC.get(key, {})
    spec: dict[str, object] = {
        "base_url": base_url or old.get("base_url", "internal://echo"),
        "model": str(entry.get("model") or old.get("model", key)),
        "api_key_env": str(entry.get("apiKeyEnv") or old.get("api_key_env", f"{key.upper()}_API_KEY")),
    }
    # 采样 / 传输参数：**未传就沿用旧值**，传了才覆盖 ——
    # 否则「只改模型名」的一次推送会把已配好的温度、超时全部打回默认。
    for field, json_key in (("temperature", "temperature"), ("max_context", "maxContext"),
                            ("top_p", "topP"), ("max_tokens", "maxTokens"),
                            ("presence_penalty", "presencePenalty"),
                            ("frequency_penalty", "frequencyPenalty"),
                            ("timeout_seconds", "timeoutSeconds"),
                            ("retry_attempts", "retryAttempts")):
        raw = entry.get(json_key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if field in old:
                spec[field] = old[field]
            continue
        val = _clamp_num(raw, json_key)
        if val is None:
            continue
        spec[field] = int(val) if json_key in ("maxTokens", "maxContext",
                                               "timeoutSeconds", "retryAttempts") else val
    if "streamEnabled" in entry and entry.get("streamEnabled") is not None:
        spec["stream_enabled"] = bool(entry.get("streamEnabled"))
    elif "stream_enabled" in old:
        spec["stream_enabled"] = old["stream_enabled"]
    if key == "echo":
        spec["base_url"] = "internal://echo"
    # 标记「这条规格来自管理端显式下发」：_build_provider 据此决定让 env 让位，
    # 否则管理员在界面上改的模型名会被 {KEY}_MODEL 环境变量悄悄盖掉。
    spec["_from_admin"] = True
    return spec


def apply_overrides(entries: list[dict], default_key: str | None = None) -> dict:
    """应用管理端「模型管理」下发的配置：更新/新增/禁用 provider，调整默认模型。

    entries: [{key, providerType, baseUrl, model, apiKeyEnv, apiKey, temperature, maxContext,
               topP, maxTokens, presencePenalty, frequencyPenalty, timeoutSeconds,
               retryAttempts, streamEnabled, enabled, isDefault}]
    返回 {applied, rejected:[{key,reason}], default}。

    **两阶段提交（2026-11-04，docs/72 §4）**：先把整批配置算进一份「暂存态」，
    任一条非法只把该条记进 rejected（保留它上一次生效的规格），
    全部处理完再一次性替换全局注册表 —— 因此一次错误的推送不可能把 agent
    留在「一半新一半旧」的状态，也不需要重启回滚。
    """
    global _DEFAULT_OVERRIDE
    rejected: list[dict] = []
    staged_spec: dict[str, dict] = dict(_REGISTRY_SPEC)
    staged_disabled: set[str] = set(_DISABLED_KEYS)
    staged_keys: dict[str, str] = dict(_API_KEY_OVERRIDES)
    staged_default = _DEFAULT_OVERRIDE
    seen: set[str] = set()
    applied = 0

    for entry in entries or []:
        key = str(entry.get("key") or "").strip().lower()
        if not key:
            rejected.append({"key": "", "reason": "key 为空"})
            continue
        try:
            spec = _spec_of(key, entry)
        except ValueError as exc:
            logger.warning("模型配置 %s 被拒绝，保留上一次生效值：%s", key, exc)
            rejected.append({"key": key, "reason": str(exc)})
            continue
        seen.add(key)
        staged_spec[key] = spec
        # 禁用集合与规格注册**解耦**：停用的模型也要先注册，
        # 否则「先保存（停用）→ 再点启动」这条主流程会因为模型未注册而永远校验失败。
        if entry.get("enabled") is False:
            staged_disabled.add(key)
        else:
            staged_disabled.discard(key)
        # 管理端填写的 Key 只进内存；传空串表示「清掉覆盖，回到环境变量」
        pushed_key = str(entry.get("apiKey") or "").strip()
        if pushed_key:
            staged_keys[key] = pushed_key
        else:
            staged_keys.pop(key, None)
        if entry.get("isDefault"):
            staged_default = key
        applied += 1

    # 下发是全量的：不在本次列表里、又不是内置键的，就是管理端已删除的模型，
    # 必须一并清掉规格与内存 Key —— 否则删掉的模型还会被显式 model_ref 命中。
    for stale in list(staged_spec):
        if stale not in seen and stale not in _BUILTIN_KEYS:
            staged_spec.pop(stale, None)
            staged_keys.pop(stale, None)
            staged_disabled.discard(stale)
            logger.info("model '%s' removed from registry (deleted in admin)", stale)
    if default_key:
        staged_default = str(default_key).strip().lower()

    # —— 提交（就地修改，别处持有的是同一个对象引用）——
    _REGISTRY_SPEC.clear()
    _REGISTRY_SPEC.update(staged_spec)
    _DISABLED_KEYS.clear()
    _DISABLED_KEYS.update(staged_disabled)
    _API_KEY_OVERRIDES.clear()
    _API_KEY_OVERRIDES.update(staged_keys)
    _DEFAULT_OVERRIDE = staged_default

    logger.info("model overrides applied: %d entries (%d rejected), default=%s",
                applied, len(rejected), _DEFAULT_OVERRIDE or "unset")
    return {"applied": applied, "rejected": rejected, "default": current_default_key()}


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


def resolve(model_ref: str | None = None,
            credential: "object | None" = None) -> Provider:
    """按 model_ref 解析 provider；未指定时走默认，必要时降级 echo。

    credential（可选，ModelCredential 或 dict）：本次运行要用**谁的凭证**。
    非空且带 api_key 时，返回一个带运行期凭证的 Provider：
    base_url / model 取凭证里填的（缺项回落注册表），api_key 取凭证里的那把。

    **为什么凭证优先于 _API_KEY_OVERRIDES**：管理端推送的是「平台默认 Key」，
    用户自己注册的账号是更明确的意图，被平台 Key 顶掉就等于用户白配了一次。

    credential 里没有 api_key（例如只选了口径没配 Key）时忽略它、按注册表解析，
    行为与改动前逐字一致。
    """
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
    overridden = _apply_credential(provider, credential)
    provider = overridden or provider
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


def _apply_credential(provider: Provider, credential: object | None) -> Provider | None:
    """把账号凭证覆盖到 provider 上（返回新对象，不改原注册表）。

    返回 None = 凭证不可用（没填 Key / 类型不对），调用方按原样走注册表。
    """
    if credential is None:
        return None
    data = credential if isinstance(credential, dict) else getattr(credential, "__dict__", None)
    if not isinstance(data, dict):
        return None
    api_key = str(data.get("apiKey") or data.get("api_key") or "").strip()
    if not api_key:
        return None
    base_url = str(data.get("baseUrl") or data.get("base_url") or "").strip()
    model = str(data.get("model") or data.get("modelName") or data.get("model_name") or "").strip()
    # provider 不同（用户换了供应商）时不能用原注册表的 base_url/model，
    # 否则「选了 deepseek 的凭证、ref 却是 dashscope」会打到别的供应商上去。
    key = str(data.get("providerKey") or data.get("provider_key") or "").strip().lower()
    if key and key in _REGISTRY_SPEC:
        provider = _build_provider(key)

    def _num(name: str, fallback):
        """凭证里带了才覆盖，没带沿用平台注册表的值（两端结构一致，缺省即继承）。"""
        raw = data.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return fallback
        try:
            return float(raw)
        except (TypeError, ValueError):
            return fallback

    top_p_raw = data.get("topP")
    return Provider(
        key=provider.key,
        driver=provider.driver,
        base_url=base_url or provider.base_url,
        model=model or provider.model,
        api_key_env=provider.api_key_env,
        temperature=_num("temperature", provider.temperature),
        max_context=int(_num("maxContext", provider.max_context)),
        top_p=(None if top_p_raw in (None, "") else _num("topP", provider.top_p or 0.0)),
        max_tokens=int(_num("maxTokens", provider.max_tokens)),
        presence_penalty=_num("presencePenalty", provider.presence_penalty),
        frequency_penalty=_num("frequencyPenalty", provider.frequency_penalty),
        timeout_seconds=int(_num("timeoutSeconds", provider.timeout_seconds)),
        retry_attempts=int(_num("retryAttempts", provider.retry_attempts)),
        stream_enabled=bool(data.get("streamEnabled", provider.stream_enabled)),
        api_key_value=api_key,
    )


def configured_providers() -> list[dict[str, object]]:
    """运维观测：当前注册表与各 provider 配置状态（key 只暴露「是否已配置」）。

    2026-11-04 起把生效中的采样/传输参数一并回显：管理端保存后靠它确认
    「热更新真的进了内存」，而不是只看推送接口返回 200。
    """
    out: list[dict[str, object]] = []
    for key in _REGISTRY_SPEC:
        p = _build_provider(key)
        out.append({
            "key": p.key,
            "driver": p.driver,
            "model": p.model,
            "base_url": p.base_url,
            "api_key_configured": "yes" if p.api_key() else "no",
            "temperature": p.temperature,
            "max_context": p.max_context,
            "top_p": p.top_p,
            "max_tokens": p.max_tokens,
            "presence_penalty": p.presence_penalty,
            "frequency_penalty": p.frequency_penalty,
            "timeout_seconds": p.timeout_seconds,
            "retry_attempts": p.retry_attempts,
            "stream_enabled": p.stream_enabled,
            "enabled": key not in _DISABLED_KEYS,
        })
    return out
