"""语音转文字（ASR）：离线模型，供 Java 后端的内网调用使用。

对外只有两个函数：``status()`` 与 ``transcribe()``。
"""
from app.asr.engine import AsrBadAudio, AsrTooLong, AsrUnavailable, status, transcribe, warmup

__all__ = ["AsrBadAudio", "AsrTooLong", "AsrUnavailable", "status", "transcribe", "warmup"]
