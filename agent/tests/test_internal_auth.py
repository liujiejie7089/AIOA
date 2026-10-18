"""`/internal/v1/*` 服务间令牌校验（B-1）的定点验收。

背景（2026-10-18 审计 B-1）：agent 的内部端点此前**零鉴权** —— 任何能连到 :8000 的
进程都能调 `/internal/v1/models/apply`（把模型密钥热加载进进程）、`/internal/v1/runs`
（消耗额度、执行工具）、`/internal/v1/runs/{id}/resume`（劫持挂起中的会话）。

修法是 `app/main.py` 的 `_require_service_jwt` 中间件：路径前缀判定，新增内部端点自动受保护。
本文件钉住的**不只是"能挡"**，还包括三件同样重要的事：

  A1 无票 → 401（原来是 200）
  A2 伪造票 → 401
  A3 ★`alg=none` 的伪造票 → 401（经典 alg confusion：不钉死算法就等于没验签）
  A4 过期票 → 401
  A5 用错密钥签的票 → 401（两端密钥不一致必须失败关闭，不能"验不过就放行"）
  A6 合规票 → 200（证明没有把正常链路一起挡死）
  A7 非内部路径（`/health`）无票 → 200（证明作用域没越界）

判别力说明：把 `_require_service_jwt` 里的 `verify` 换成 `pass`，A1/A2/A3/A4/A5 必须同时变红，
而 A6/A7 仍绿 —— 这就是「挡的是鉴权，不是整个服务」的证据。
"""
from __future__ import annotations

import base64
import json
import time

from fastapi.testclient import TestClient

from app.main import app
from aios_ai.config import settings
from aios_ai.security.service_jwt import DEV_SECRET, issue
from tests._svc import svc_headers

client = TestClient(app)

PROBE = "/internal/v1/models"          # 只读、无副作用，适合做鉴权矩阵
INTERNAL_ERROR_CODE = "UNAUTHORIZED_SERVICE"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _forge_none_alg() -> str:
    """构造一张 `alg=none` 的无签名票（攻击者最省力的一招）。"""
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps(
        {"sub": "server", "svc": "server", "exp": int(time.time()) + 300},
        separators=(",", ":")).encode())
    return f"{header}.{payload}."


def _assert_401(resp, label: str) -> None:
    assert resp.status_code == 401, f"{label}：期望 401，实际 {resp.status_code} {resp.text}"
    body = resp.json()
    assert body.get("code") == INTERNAL_ERROR_CODE, f"{label}：错误信封不符 —— {body}"
    assert body.get("retryable") is False, f"{label}：鉴权失败不可重试，retryable 必须 false —— {body}"


# ---------------------------------------------------------------- 必须被挡

def test_no_token_is_401():
    """A1：完全没有 Authorization 头 —— 修复前这里是 200（零鉴权）。"""
    _assert_401(client.get(PROBE), "A1 无票")


def test_malformed_token_is_401():
    """A2：随便给个串，不能因为"解不开就看不出错"而放行。"""
    _assert_401(client.get(PROBE, headers={"Authorization": "Bearer not-a-jwt"}), "A2 格式错")
    _assert_401(client.get(PROBE, headers={"Authorization": "Basic abc"}), "A2 非 Bearer 方案")


def test_alg_none_forgery_is_401():
    """A3：★alg confusion —— 若实现用「解出 payload 就算过」，这张票会被当成合法。"""
    _assert_401(client.get(PROBE, headers={"Authorization": "Bearer " + _forge_none_alg()}),
                "A3 alg=none")


def test_expired_token_is_401():
    """A4：exp 已过。用负 TTL 签一张「出生即过期」的票。"""
    expired = issue("server", settings.service_jwt_secret, ttl_seconds=-60)
    _assert_401(client.get(PROBE, headers={"Authorization": "Bearer " + expired}), "A4 过期")


def test_token_signed_with_other_secret_is_401():
    """A5：两端密钥不一致时必须失败关闭（换生产密钥后漏配就是这种状态）。"""
    other = issue("server", DEV_SECRET + "-wrong")
    _assert_401(client.get(PROBE, headers={"Authorization": "Bearer " + other}), "A5 错密钥")


# ---------------------------------------------------------------- 不得被挡

def test_valid_token_passes():
    """A6：合规票 → 200。证明中间件是"校验"而不是"一律拒绝"。"""
    resp = client.get(PROBE, headers=svc_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "providers" in body and "default" in body, body


def test_agent_side_token_also_accepted():
    """A6b：`svc=agent` 与 `svc=server` 都是白名单内（Java 侧 generate 可能任选其一）。"""
    resp = client.get(PROBE, headers=svc_headers(svc="agent"))
    assert resp.status_code == 200, resp.text


def test_health_is_not_gated():
    """A7：作用域只覆盖 /internal/v1/ —— 健康检查不能被连带要求令牌（探针会全红）。"""
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "UP"}
