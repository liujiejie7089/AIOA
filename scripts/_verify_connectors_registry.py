#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""连接器注册表与统一凭证管理面哨兵（mock 模式，无 Java 依赖）。

覆盖：
  S1  清单包含 wechat_work / qq_mail，工具计数与事实源一致
  S2  wechat_work 凭证 schema 为 4 字段（3 必填），corpSecret 标记 sensitive
  S3  未配置时 configured=false
  S4  _require_admin：非管理员且非 mock ⇒ 拒绝（mock 放行是既定口径）
  S5  管理员保存企微凭据 ⇒ configured=true
  S6  掩码视图：corpId 只回前 4 位，corpSecret 只回「已配置」布尔
  S7  重复提交空串/掩码值 ⇒ 保留旧值（不外泄也不清空）
  S8  provider=vault 的连接器：任意第三方应用凭证可存可读（掩码）
  S9  未声明字段被拒（不写库）
  S10 provider=none 的连接器（QQ邮箱）拒绝管理员写应用凭据
  S11 未知连接器 404
  S12 清除后 configured=false
  S13 库文件字节扫描：无明文凭据（db / -wal / -shm 全扫）
  S14 工具目录未变（企微 13 / 邮箱 6）

用法：D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_connectors_registry.py
退出码 = 失败项数。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

_TMP = tempfile.mkdtemp(prefix="connectors_verify_")
os.environ["WECOM_MOCK"] = "1"
os.environ["WECOM_DB_PATH"] = os.path.join(_TMP, "wecom.db")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp-hub"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _free_port()
BASE = f"http://127.0.0.1:{PORT}"

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((bool(cond), name, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))


def main() -> int:
    import httpx
    import uvicorn

    from mcp_hub.connectors import registry
    from mcp_hub.connectors.manifest import AUTH_API_KEY, ConnectorManifest, CredentialField
    from mcp_hub.connectors import admin_api as connectors_admin_api
    from mcp_hub.app import app as hub_app
    from mcp_hub.wecom.models import Identity

    # 运行期登记一个 provider=vault 的第三方连接器，验证「任意应用凭证」路径
    registry.register(ConnectorManifest(
        code="demo_vault", name="演示第三方应用", group="测试",
        auth_mode=AUTH_API_KEY, provider="vault",
        credential_fields=(
            CredentialField(name="apiKey", label="API Key", type="password", sensitive=True),
            CredentialField(name="endpoint", label="接口地址", type="url", required=False),
        ),
    ))

    config = uvicorn.Config(hub_app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True).start()

    with httpx.Client(timeout=10.0, trust_env=False) as c:
        for _ in range(100):
            try:
                if c.get(f"{BASE}/health").status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            print("服务未就绪")
            return 1

        # S1 清单
        r = c.get(f"{BASE}/api/v1/connectors").json()
        codes = [x["code"] for x in r.get("connectors", [])]
        check("S1 清单包含两个内置连接器", {"wechat_work", "qq_mail"} <= set(codes), f"codes={codes}")

        # S2 schema
        wecom = next(x for x in r["connectors"] if x["code"] == "wechat_work")
        fields = {f["name"]: f for f in wecom["credentialFields"]}
        check("S2 企微 schema = 4 字段 / 3 必填 / secret 敏感",
              len(fields) == 4 and sum(1 for f in fields.values() if f["required"]) == 3
              and fields["corpSecret"]["sensitive"] is True,
              json.dumps(sorted(fields), ensure_ascii=False))

        # S3 未配置
        check("S3 未配置时 configured=false", wecom["configured"] is False, str(wecom.get("hint")))

        # S4 权限判定（直接对函数断言：mock 模式放行是既定口径）
        denied = connectors_admin_api._require_admin(Identity(tenant_id="t", user_id="u", roles=[], mock=False))
        allowed = connectors_admin_api._require_admin(Identity(tenant_id="t", user_id="u", roles=[], mock=True))
        check("S4 非管理员被拒 / mock 放行", denied is not None and allowed is None, str(denied))

        # S5 保存企微凭据
        secret = "SECRET-PLAINTEXT-CANARY-9f3a"
        body = {"values": {"corpId": "wwcanary1234", "agentId": "1000002",
                           "corpSecret": secret, "redirectUri": "https://example.com/cb"}}
        r = c.put(f"{BASE}/api/v1/connectors/wechat_work/credentials", json=body)
        ok = r.status_code == 200 and r.json().get("configured") is True
        check("S5 管理员保存企微凭据 ⇒ configured=true", ok, f"HTTP {r.status_code}")

        # S6 掩码
        v = c.get(f"{BASE}/api/v1/connectors/wechat_work/credentials").json()
        val = v.get("values", {})
        check("S6 掩码：corpId 前 4 位可见 / secret 只回布尔",
              val.get("corpId", "").startswith("wwca") and val.get("corpId") != "wwcanary1234"
              and val.get("corpSecret") == "" and val.get("corpSecretSet") is True,
              json.dumps(val, ensure_ascii=False))

        # S7 空串/掩码值保留旧值
        r = c.put(f"{BASE}/api/v1/connectors/wechat_work/credentials",
                  json={"values": {"corpId": "wwca****", "agentId": "", "corpSecret": ""}})
        v2 = c.get(f"{BASE}/api/v1/connectors/wechat_work/credentials").json()
        check("S7 掩码值/空串 ⇒ 保留旧值",
              r.status_code == 200 and v2["configured"] is True
              and v2["values"].get("corpSecretSet") is True, f"HTTP {r.status_code}")

        # S8 vault 连接器
        vkey = "sk-demo-canary-7b2c"
        r = c.put(f"{BASE}/api/v1/connectors/demo_vault/credentials",
                  json={"values": {"apiKey": vkey, "endpoint": "https://api.example.com"}})
        vv = c.get(f"{BASE}/api/v1/connectors/demo_vault/credentials").json()
        check("S8 vault 连接器可存可读（掩码）",
              r.status_code == 200 and vv.get("configured") is True
              and vv["values"].get("apiKeySet") is True and vv["values"].get("apiKey") == ""
              and vv["values"].get("endpoint", "").startswith("http"),
              f"HTTP {r.status_code}")

        # S9 未声明字段
        r = c.put(f"{BASE}/api/v1/connectors/demo_vault/credentials",
                  json={"values": {"apiKey": "x", "nope": "y"}})
        check("S9 未声明字段被拒", r.status_code == 400, f"HTTP {r.status_code} {r.text[:80]}")

        # S10 provider=none 拒绝写入
        r = c.put(f"{BASE}/api/v1/connectors/qq_mail/credentials", json={"values": {"email": "a@b.c"}})
        check("S10 QQ邮箱无应用级凭据 ⇒ 400", r.status_code == 400, f"HTTP {r.status_code}")

        # S11 未知连接器
        r = c.get(f"{BASE}/api/v1/connectors/not_exists")
        check("S11 未知连接器 404", r.status_code == 404, f"HTTP {r.status_code}")

        # S12 清除
        r = c.delete(f"{BASE}/api/v1/connectors/wechat_work/credentials")
        v3 = c.get(f"{BASE}/api/v1/connectors/wechat_work/credentials").json()
        check("S12 清除后 configured=false",
              r.status_code == 200 and v3.get("configured") is False, f"HTTP {r.status_code}")

        # S14 工具目录未变
        r = c.get(f"{BASE}/api/v1/connectors").json()
        tc = {x["code"]: x["toolCount"] for x in r["connectors"]}
        check("S14 工具计数：企微 13 / 邮箱 6", tc.get("wechat_work") == 13 and tc.get("qq_mail") == 6, str(tc))

    # S13 库文件无明文
    blob = b""
    for suffix in ("", "-wal", "-shm"):
        p = os.environ["WECOM_DB_PATH"] + suffix
        if os.path.exists(p):
            with open(p, "rb") as f:
                blob += f.read()
    leaks = [s for s in (b"SECRET-PLAINTEXT-CANARY-9f3a", b"sk-demo-canary-7b2c") if s in blob]
    check("S13 库文件无明文凭据", not leaks, f"leaks={leaks}")

    fails = [r for r in RESULTS if not r[0]]
    print()
    if fails:
        print(f"存在失败项：{len(fails)} / {len(RESULTS)}")
        for _, name, detail in fails:
            print(f"  - {name} {detail}")
    else:
        print(f"全部断言通过 ✅\n（共 {len(RESULTS)} 项，失败 0 项）")
    return len(fails)


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.stdout.flush()
    os._exit(code)
