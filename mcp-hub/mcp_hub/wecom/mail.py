# -*- coding: utf-8 -*-
"""方案B 后端：企业邮箱（IMAP/SMTP，客户端专用密码）。

Mock（WECOM_MOCK=1）：进程内虚拟邮箱，每个邮箱地址一个 mailbox，
预置 3 封收件箱邮件；草稿/发送走内存队列，send_draft 按 requestId 幂等。

实装（WECOM_MOCK=0）：P2 落地（imaplib + smtplib，SSL 993/465）。
P0 的 RealMailBackend 直接抛出带排查指引的 MailError——宁可显式失败，
也不给出「假装成功」的空结果。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from . import store

logger = logging.getLogger("mcp_hub.wecom")


class MailError(RuntimeError):
    def __init__(self, reason: str, code: str = "MAIL_ERROR"):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class MailBackend(Protocol):
    async def probe(self, email: str, password: str) -> dict[str, Any]: ...
    async def list_folders(self, email: str, password: str) -> list[dict[str, Any]]: ...
    async def list_messages(self, email: str, password: str, folder: str, limit: int, unread_only: bool) -> list[dict[str, Any]]: ...
    async def read_message(self, email: str, password: str, uid: int, folder: str) -> dict[str, Any]: ...
    async def search_messages(self, email: str, password: str, query: str, folder: str, limit: int) -> list[dict[str, Any]]: ...
    async def create_draft(self, email: str, password: str, to: str, subject: str, body: str, cc: str | None) -> dict[str, Any]: ...
    async def send_draft(self, email: str, password: str, draft_id: int, request_id: str) -> dict[str, Any]: ...


# ---------- Mock ----------


class _Mailbox:
    def __init__(self, email: str):
        self.email = email
        self.folders = ["INBOX", "Sent", "Drafts", "Trash"]
        self.messages: dict[str, list[dict[str, Any]]] = {
            "INBOX": [
                {"uid": 1, "from": "hr@mock-corp.com", "subject": "欢迎入职",
                 "date": "2026-10-20T09:00:00+08:00", "unread": True,
                 "body": "欢迎加入！请完成企微激活与邮箱客户端密码设置。"},
                {"uid": 2, "from": "lisi@mock-corp.com", "subject": "周会纪要 10-27",
                 "date": "2026-10-27T17:30:00+08:00", "unread": True,
                 "body": "本周完成连接器联调；下周进入方案B 邮箱绑定。"},
                {"uid": 3, "from": "no-reply@mock-corp.com", "subject": "安全提醒",
                 "date": "2026-10-26T08:00:00+08:00", "unread": False,
                 "body": "检测到新设备登录，如非本人操作请修改密码。"},
            ],
            "Sent": [],
            "Drafts": [],
            "Trash": [],
        }
        self.next_uid = 4
        self.drafts: dict[int, dict[str, Any]] = {}
        self.next_draft_id = 1
        self.sent_request_ids: set[str] = set()

    def probe(self) -> None:
        if self.email.endswith("@blocked.com"):
            raise MailError("邮箱域被 Mock 拒绝（模拟未开启 IMAP 服务）", "MAIL_NOT_ENABLED")


_MOCK_BOXES: dict[str, _Mailbox] = {}


def _box(email: str) -> _Mailbox:
    box = _MOCK_BOXES.get(email)
    if box is None:
        box = _Mailbox(email)
        _MOCK_BOXES[email] = box
    return box


class MockMailBackend:
    async def _auth(self, email: str, password: str) -> _Mailbox:
        if not email or "@" not in email:
            raise MailError("邮箱地址格式不正确", "MAIL_BAD_ADDRESS")
        if not password:
            raise MailError("客户端专用密码不能为空", "MAIL_BAD_PASSWORD")
        box = _box(email)
        if password != f"pwd-{email}":
            raise MailError("客户端专用密码错误（请在邮箱设置中重新生成）", "MAIL_AUTH_FAILED")
        box.probe()
        return box

    async def probe(self, email: str, password: str) -> dict[str, Any]:
        box = await self._auth(email, password)
        return {"ok": True, "email": email, "folders": box.folders}

    async def list_folders(self, email: str, password: str) -> list[dict[str, Any]]:
        box = await self._auth(email, password)
        return [{"name": f} for f in box.folders]

    async def list_messages(self, email: str, password: str, folder: str, limit: int,
                            unread_only: bool) -> list[dict[str, Any]]:
        box = await self._auth(email, password)
        if folder not in box.messages:
            raise MailError(f"文件夹不存在：{folder}", "MAIL_NO_FOLDER")
        rows = box.messages[folder]
        if unread_only:
            rows = [m for m in rows if m.get("unread")]
        return [{k: m.get(k) for k in ("uid", "from", "subject", "date", "unread")}
                for m in rows[: max(1, min(limit, 30))]]

    async def read_message(self, email: str, password: str, uid: int, folder: str) -> dict[str, Any]:
        box = await self._auth(email, password)
        if folder not in box.messages:
            raise MailError(f"文件夹不存在：{folder}", "MAIL_NO_FOLDER")
        for m in box.messages[folder]:
            if m["uid"] == uid:
                return dict(m)
        raise MailError(f"邮件不存在：{folder}#{uid}", "MAIL_NO_MESSAGE")

    async def search_messages(self, email: str, password: str, query: str, folder: str,
                              limit: int) -> list[dict[str, Any]]:
        box = await self._auth(email, password)
        if folder not in box.messages:
            raise MailError(f"文件夹不存在：{folder}", "MAIL_NO_FOLDER")
        q = (query or "").lower()
        hits = [m for m in box.messages[folder]
                if q in str(m.get("subject", "")).lower() or q in str(m.get("body", "")).lower()]
        return [{k: m.get(k) for k in ("uid", "from", "subject", "date", "unread")}
                for m in hits[: max(1, min(limit, 30))]]

    async def create_draft(self, email: str, password: str, to: str, subject: str,
                           body: str, cc: str | None) -> dict[str, Any]:
        box = await self._auth(email, password)
        if not to or "@" not in to:
            raise MailError("收件人邮箱格式不正确", "MAIL_BAD_ADDRESS")
        draft_id = box.next_draft_id
        box.next_draft_id += 1
        box.drafts[draft_id] = {"draftId": draft_id, "to": to, "subject": subject,
                                "body": body, "cc": cc}
        return {"draftId": draft_id, "created": True}

    async def send_draft(self, email: str, password: str, draft_id: int,
                         request_id: str) -> dict[str, Any]:
        box = await self._auth(email, password)
        if request_id in box.sent_request_ids:
            return {"sent": True, "idempotent": True, "requestId": request_id}
        draft = box.drafts.pop(draft_id, None)
        if draft is None:
            raise MailError(f"草稿不存在或已发送：draftId={draft_id}", "MAIL_NO_DRAFT")
        uid = box.next_uid
        box.next_uid += 1
        box.messages["Sent"].append({
            "uid": uid, "from": email, "subject": draft["subject"],
            "date": "2026-10-28T10:00:00+08:00", "unread": False, "body": draft["body"],
        })
        box.sent_request_ids.add(request_id)
        return {"sent": True, "idempotent": False, "uid": uid, "to": draft["to"]}


# ---------- 实装占位（P2 落地） ----------


class RealMailBackend:
    async def _unimplemented(self) -> None:
        raise MailError(
            "企业邮箱实装排期在 P2（imaplib/smtplib）。当前为生产模式但邮箱后端未实装，"
            "请设置 WECOM_MOCK=1 联调或等待 P2", "MAIL_NOT_IMPLEMENTED")

    async def probe(self, email: str, password: str) -> dict[str, Any]:
        await self._unimplemented()
        return {}

    async def list_folders(self, email: str, password: str) -> list[dict[str, Any]]:
        await self._unimplemented()
        return []

    async def list_messages(self, email: str, password: str, folder: str, limit: int,
                            unread_only: bool) -> list[dict[str, Any]]:
        await self._unimplemented()
        return []

    async def read_message(self, email: str, password: str, uid: int, folder: str) -> dict[str, Any]:
        await self._unimplemented()
        return {}

    async def search_messages(self, email: str, password: str, query: str, folder: str,
                              limit: int) -> list[dict[str, Any]]:
        await self._unimplemented()
        return []

    async def create_draft(self, email: str, password: str, to: str, subject: str,
                           body: str, cc: str | None) -> dict[str, Any]:
        await self._unimplemented()
        return {}

    async def send_draft(self, email: str, password: str, draft_id: int,
                         request_id: str) -> dict[str, Any]:
        await self._unimplemented()
        return {}


_backend: MailBackend | None = None


def get_backend() -> MailBackend:
    global _backend
    if _backend is None:
        _backend = MockMailBackend() if store.is_mock() else RealMailBackend()
    return _backend
