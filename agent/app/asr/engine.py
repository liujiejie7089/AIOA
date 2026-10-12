"""离线 ASR 引擎（faster-whisper）。

三条口径：
  * **懒加载 + 单例**：第一次用到才把模型读进内存，之后常驻；启动时后台预热一次
    （``warmup()``），避免「用户第一次说话等十几秒」。
  * **离线优先**：内网默认不通外网 ⇒ 默认置 ``HF_HUB_OFFLINE=1``，只认本地模型目录。
    要临时从镜像下载，显式设 ``AIOA_ASR_ALLOW_DOWNLOAD=1``（配合 ``HF_ENDPOINT``）。
  * **不可用就报错**：依赖没装 / 模型没就位一律抛 ``AsrUnavailable``，
    **绝不返回空文本冒充识别成功**。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

# ★ 必须先 import config：main.py 里本模块比 app.config 先被导入，
#   而 .env 是在 app.config 导入时才注入 os.environ 的。
#   少了这一行，写在 agent/.env 里的 AIOA_ASR_* 全部读不到（静默用默认值）。
import app.config  # noqa: F401  isort:skip

logger = logging.getLogger("aioa.agent.asr")

# agent 根目录（agent/），默认模型落在 agent/.models
_AGENT_ROOT = Path(__file__).resolve().parents[2]

MODEL_NAME = os.getenv("AIOA_ASR_MODEL", "small")
MODEL_DIR = os.getenv("AIOA_ASR_MODEL_DIR", str(_AGENT_ROOT / ".models"))
DEVICE = os.getenv("AIOA_ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("AIOA_ASR_COMPUTE_TYPE", "int8")
ALLOW_DOWNLOAD = os.getenv("AIOA_ASR_ALLOW_DOWNLOAD", "0") == "1"


def _resolve_model_ref() -> str:
    """模型引用解析，顺序：显式路径 → ``MODEL_DIR/<名字>`` 本地目录 → 名字本身（走 HF 下载）。

    中间那一档是为了「离线落地零配置」：把模型摊平到 ``agent/.models/small``
    （含 model.bin / config.json / tokenizer.json / vocabulary.txt）即可，
    不必再设 AIOA_ASR_MODEL，也不会触发任何联网行为。
    """
    if os.path.isdir(MODEL_NAME):
        return MODEL_NAME
    local = os.path.join(MODEL_DIR, MODEL_NAME)
    if os.path.isfile(os.path.join(local, "model.bin")):
        return local
    return MODEL_NAME


_lock = threading.Lock()
_model = None
_error: str | None = None


class AsrUnavailable(RuntimeError):
    """ASR 不可用（依赖缺失 / 模型未就绪）。**不静默降级**。"""


class AsrBadAudio(ValueError):
    """音频解不开：多半是调用方发来的根本不是音频 / 容器格式不支持。→ 400。"""


class AsrTooLong(ValueError):
    """音频时长超过上限。→ 422。"""


def _is_decode_error(exc: BaseException) -> bool:
    """判断是不是「音频解不开」（调用方问题），而不是引擎自身故障。

    faster-whisper 用 PyAV 解码，PyAV 的异常模块名一律以 ``av`` 开头；
    个别版本会把底层错误再包一层，所以补一个消息特征兜底。
    目的：把「用户传了个坏文件」和「引擎真的坏了」分成 400 与 500，
    而不是一律 500 并把内部异常文本（含临时文件路径）回给调用方。
    """
    mod = type(exc).__module__ or ""
    if mod == "av" or mod.startswith("av."):
        return True
    return "invalid data found" in str(exc).lower()


def _load():
    """加载并缓存模型；失败时缓存错误原因，后续调用快速失败（不再重试读盘）。"""
    global _model, _error
    with _lock:
        if _model is not None:
            return _model
        if _error:
            raise AsrUnavailable(_error)
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            _error = f"未安装 faster-whisper（pip install faster-whisper）：{exc}"
            raise AsrUnavailable(_error) from exc

        if not ALLOW_DOWNLOAD:
            # 离线：不去外网拉模型，模型必须已在 MODEL_DIR
            os.environ.setdefault("HF_HUB_OFFLINE", "1")

        ref = _resolve_model_ref()
        try:
            _model = WhisperModel(ref, device=DEVICE, compute_type=COMPUTE_TYPE,
                                  download_root=MODEL_DIR)
        except Exception as exc:  # noqa: BLE001
            _error = f"模型 {ref} 未就绪（模型目录 {MODEL_DIR}）：{exc}"
            raise AsrUnavailable(_error) from exc

        logger.info("asr model loaded: %s (%s/%s) roots=%s", ref, DEVICE, COMPUTE_TYPE, MODEL_DIR)
        return _model


def warmup() -> None:
    """启动预热：失败只记日志，不影响进程启动（真正不可用时由接口返回 503）。"""
    try:
        _load()
    except AsrUnavailable as exc:
        logger.warning("asr warmup skipped: %s", exc)


def status() -> dict:
    """诊断用：报「能不能用」以及为什么不能用（不伪装可用）。"""
    try:
        _load()
        available = True
    except AsrUnavailable:
        available = False
    return {
        "engine": "faster-whisper",
        "model": _resolve_model_ref(),
        "modelDir": MODEL_DIR,
        "device": DEVICE,
        "computeType": COMPUTE_TYPE,
        "allowDownload": ALLOW_DOWNLOAD,
        "available": available,
        "error": _error,
    }


def transcribe(path: str, lang: str | None = "zh", max_seconds: int | None = None) -> dict:
    """把音频文件转成文字。``path`` 为本地临时文件（webm/opus、mp4/aac、wav 均可）。

    ``max_seconds`` 用于**在识别前**掐掉超长音频。注意能省的和不能省的：

      * **省得掉**：whisper 的编码/解码推理那几趟 —— 长音频的主要开销。
      * **省不掉**：音频解码本身。``model.transcribe()`` 是普通函数（非生成器），
        进函数体就先把整段音频解成 PCM，``info.duration`` 正是
        ``audio.shape[0] / sampling_rate``（见 faster_whisper/transcribe.py）。
        所以「超长」这个判断最早也只能在这一步之后做出。

    失败按归因分类抛出（供路由翻成不同 HTTP 码），**绝不返回空文本冒充识别成功**：
      * 音频解不开  → :class:`AsrBadAudio`（调用方问题，400）
      * 时长超上限  → :class:`AsrTooLong`（422）
      * 模型/依赖没就位 → :class:`AsrUnavailable`（503）
    """
    model = _load()
    try:
        segments, info = model.transcribe(
            path,
            language=(lang or None),
            vad_filter=True,                 # 掐掉前后静音，短语音更稳
            beam_size=5,
            condition_on_previous_text=False,
        )
        duration = float(getattr(info, "duration", 0) or 0)
        if max_seconds and duration > max_seconds:
            raise AsrTooLong(f"音频 {duration:.0f}s 超过上限 {max_seconds}s")
        text = "".join(s.text for s in segments).strip()
    except AsrTooLong:
        raise
    except Exception as exc:  # noqa: BLE001
        if _is_decode_error(exc):
            raise AsrBadAudio("音频无法解码，请确认上传的是有效的音频文件") from exc
        raise
    return {
        "text": text,
        "lang": getattr(info, "language", lang) or lang,
        "durationMs": int(duration * 1000),
        "model": MODEL_NAME,
    }
