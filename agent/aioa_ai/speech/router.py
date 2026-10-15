"""ASR 内部端点：只给 Java 后端（aioa-server）内网调用，不经浏览器。

契约（与其它 ``/internal/v1/*`` 略有不同：这里需要让调用方区分错误，
所以统一回 ``{code, data|message}`` 信封）：

    GET  /internal/v1/asr/status
    POST /internal/v1/asr/transcribe?lang=zh     Content-Type: audio/webm
         body = 音频原始字节（不做 multipart）

音频**用完即删**：落一个临时文件、识别完就 unlink，不留存、不入库。
"""
from __future__ import annotations

import logging
import os
import tempfile

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from aioa_ai.speech import engine

logger = logging.getLogger("aioa.agent.asr")

router = APIRouter(prefix="/internal/v1/asr", tags=["asr"])

MAX_BYTES = int(os.getenv("AIOA_ASR_MAX_BYTES", str(10 * 1024 * 1024)))
MAX_SECONDS = int(os.getenv("AIOA_ASR_MAX_SECONDS", "60"))

# 容器格式按 Content-Type 判；识别引擎按容器头自解析，后缀只是给解码器的提示
_SUFFIX = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aac": ".aac",
    "audio/3gpp": ".3gp",
}


def _bad(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


@router.get("/status")
async def status() -> dict:
    """能不能用、用的什么模型、不能用是为什么（不伪装可用）。"""
    return engine.status()


@router.post("/transcribe")
async def transcribe(request: Request, lang: str = "zh"):
    raw = await request.body()
    if not raw:
        return _bad(400, "BAD_REQUEST", "音频为空")
    if len(raw) > MAX_BYTES:
        return _bad(413, "AUDIO_TOO_LARGE", f"音频超过 {MAX_BYTES // 1048576}MB")

    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=_SUFFIX.get(ctype, ".webm"))
    path = tmp.name
    try:
        tmp.write(raw)
        tmp.close()
        try:
            # 时长上限交给引擎在「识别前」判：不这么做的话，一个 10 分钟的上传会先被
            # 完整识别一遍才被拒，白烧 CPU、白让用户等。
            # 注意：音频解码这一步省不掉（faster-whisper 的 duration 取自解码后的样本数），
            # 省掉的是 whisper 的编码/解码推理那几趟 —— 那才对长音频是大头。
            data = await run_in_threadpool(engine.transcribe, path, lang, MAX_SECONDS)
        except engine.AsrBadAudio as exc:
            logger.warning("asr bad audio (%d bytes): %s", len(raw), exc)
            return _bad(400, "AUDIO_UNDECODABLE", str(exc))
        except engine.AsrTooLong as exc:
            return _bad(422, "AUDIO_TOO_LONG", str(exc))
        except engine.AsrUnavailable as exc:
            # 503 不回内部异常文本（原实现会把 /app/.models 这类内部路径带回给调用方，
            # 经后端透传到 H5）；完整原因只进日志，便于排障。信封形状保持 {code, message} 不变。
            logger.warning("asr unavailable: %s", exc)
            return _bad(503, "ASR_UNAVAILABLE", "语音识别服务暂不可用，请稍后再试")
        except Exception:  # noqa: BLE001
            # 500 不回内部异常文本（原实现会把临时文件路径带回给调用方）；详情只进日志
            logger.exception("asr failed")
            return _bad(500, "ASR_FAILED", "语音识别失败，请稍后重试")

        logger.info("asr ok: %d bytes -> %.1fs -> %d chars",
                    len(raw), data["durationMs"] / 1000.0, len(data["text"]))
        return {"code": 0, "data": data}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
