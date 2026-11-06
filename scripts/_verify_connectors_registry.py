#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""连接器注册表与统一凭证管理面哨兵（mock 模式，无 Java 依赖）。

覆盖：
  S1  清单包含两个内置连接器（qq_mail / wecom_cli）+ 运行期登记的 demo_vault，
     且**已下线的 wechat_work / wecom_group 不出现**
  S2  两个内置连接器都没有应用级凭据字段（qq_mail=CREDENTIAL / wecom_cli=QR）
  S3  无应用配置的连接器 configured 恒为 true（扫码方案的核心：管理员无事可做）
  S4  _require_admin：非管理员且非 mock ⇒ 拒绝（mock 放行是既定口径）
  S5  管理员保存 provider=vault 凭据 ⇒ configured=true
  S6  掩码视图：sensitive 字段只回「已配置」布尔，非 sensitive 字段回明文
  S7  重复提交空串/掩码值 ⇒ 保留旧值（不外泄也不清空）
  S8  同一租户下两个 vault 连接器互不覆盖（(tenant, code, field) 主键语义）
  S9  未声明字段被拒（不写库）
  S10 provider=none 的连接器（QQ邮箱）拒绝管理员写应用凭据
  S11 未知连接器 404；已下线的连接器同样 404
  S12 清除后 configured=false
  S13 库文件字节扫描：无明文凭据（db / -wal / -shm 全扫）
  S14 工具目录未变（wecom_cli 5 / 邮箱 6）

> 2026-10-30（docs/64 §9.7）：`wechat_work`（provider=wecom）随连接器物理删除，
> `provider=wecom` 分支也一并删掉。原 S2/S3/S5/S6/S7/S12 以 wechat_work 为主体，
> 现在改挂到**运行期登记的 provider=vault 连接器**上 —— 验的是同一套「按 provider 落库 +
> 掩码 + 保留旧值 + 清除」机制，机制没变，只是不再有企微那张专用表。

用法：D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_connectors_registry.py
退出码 = 失败项数。
"""

from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

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


def _plain(code: str, field: str) -> str:
    """第二源：用与 hub 相同的库文件与密钥直接解出**明文真值**。

    铁律 12：判「掩码没泄露」不能只看掩码视图自己说了什么，要能证明库里存的是真值、
    视图给的是打星 —— 两边同时成立才叫没泄露。
    """
    import sqlite3

    from mcp_hub.wecom import crypto, store

    con = sqlite3.connect(os.environ["WECOM_DB_PATH"])
    try:
        row = con.execute(
            "SELECT value_enc FROM connector_credential WHERE connector_code=? AND field=?",
            (code, field),
        ).fetchone()
    finally:
        con.close()
    return crypto.decrypt(row[0], store.key()) if row else ""


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
    # 第二个 vault 连接器：专验「(tenant, code, field) 主键」不会把两个应用的值串在一起
    registry.register(ConnectorManifest(
        code="demo_vault2", name="演示第三方应用二", group="测试",
        auth_mode=AUTH_API_KEY, provider="vault",
        credential_fields=(
            CredentialField(name="apiKey", label="API Key", type="password", sensitive=True),
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
        retired = {"wechat_work", "wecom_group"} & set(codes)
        check("S1 清单含两个内置连接器 + demo_vault，且已下线的两个不出现",
              {"qq_mail", "wecom_cli", "demo_vault"} <= set(codes) and not retired,
              f"codes={sorted(codes)} retired={sorted(retired)}")

        # S2 内置连接器都没有应用级凭据字段（provider=none）
        by_code = {x["code"]: x for x in r["connectors"]}
        qq, cli = by_code["qq_mail"], by_code["wecom_cli"]
        check("S2 内置连接器无应用级凭据字段（qq=CREDENTIAL / cli=QR）",
              qq["authMode"] == "CREDENTIAL" and cli["authMode"] == "QR"
              and not qq["credentialFields"] and not cli["credentialFields"],
              json.dumps({k: (by_code[k]["authMode"], len(by_code[k]["credentialFields"]))
                          for k in ("qq_mail", "wecom_cli")}, ensure_ascii=False))

        # S3 没有应用配置的形态恒就绪
        check("S3 无应用配置 ⇒ configured=true（不需管理员配）",
              qq["configured"] is True and cli["configured"] is True
              and cli["provider"] == "none",
              json.dumps({"qq": qq["configured"], "cli": cli["configured"],
                          "cliProvider": cli["provider"]}, ensure_ascii=False))

        # S4 权限判定（直接对函数断言：mock 模式放行是既定口径）
        denied = connectors_admin_api._require_admin(Identity(tenant_id="t", user_id="u", roles=[], mock=False))
        allowed = connectors_admin_api._require_admin(Identity(tenant_id="t", user_id="u", roles=[], mock=True))
        check("S4 非管理员被拒 / mock 放行", denied is not None and allowed is None, str(denied))

        # S5 保存 vault 凭据（原用 wechat_work 的 provider=wecom 专用分支，现统一走 vault）
        secret = "SECRET-PLAINTEXT-CANARY-9f3a"
        body = {"values": {"apiKey": secret, "endpoint": "https://example.com/cb"}}
        r = c.put(f"{BASE}/api/v1/connectors/demo_vault/credentials", json=body)
        ok = r.status_code == 200 and r.json().get("configured") is True
        check("S5 管理员保存 vault 凭据 ⇒ configured=true", ok, f"HTTP {r.status_code}")

        # S6 掩码（第二源：直接用同一把密钥解库，证明「视图是掩码」而「库里是明文密文对」）
        v = c.get(f"{BASE}/api/v1/connectors/demo_vault/credentials").json()
        val = v.get("values", {})
        masked_ok = (val.get("apiKey") == "" and val.get("apiKeySet") is True
                     and str(val.get("endpoint", "")).startswith("http")
                     and "*" in str(val.get("endpoint", ""))
                     and "example.com" not in json.dumps(v, ensure_ascii=False))
        check("S6 掩码视图不回明文（sensitive 只回布尔 / 其余打星）",
              masked_ok and _plain("demo_vault", "apiKey") == secret,
              json.dumps(val, ensure_ascii=False))

        # S7 空串/掩码值保留旧值（判据用解密后的真值，不看掩码视图）
        r = c.put(f"{BASE}/api/v1/connectors/demo_vault/credentials",
                  json={"values": {"apiKey": "••••", "endpoint": ""}})
        v2 = c.get(f"{BASE}/api/v1/connectors/demo_vault/credentials").json()
        check("S7 掩码值/空串 ⇒ 保留旧值（不解密视图，直接读库）",
              r.status_code == 200 and v2["configured"] is True
              and _plain("demo_vault", "apiKey") == secret
              and _plain("demo_vault", "endpoint") == "https://example.com/cb",
              f"HTTP {r.status_code} apiKey保留={_plain('demo_vault', 'apiKey') == secret} "
              f"endpoint保留={_plain('demo_vault', 'endpoint') == 'https://example.com/cb'}")

        # S8 两个 vault 连接器互不覆盖
        vkey = "sk-demo-canary-7b2c"
        r = c.put(f"{BASE}/api/v1/connectors/demo_vault2/credentials",
                  json={"values": {"apiKey": vkey}})
        b = c.get(f"{BASE}/api/v1/connectors/demo_vault2/credentials").json()
        check("S8 两个 vault 连接器互不覆盖（(tenant, code, field) 主键语义）",
              r.status_code == 200 and b.get("configured") is True
              and b["values"].get("apiKeySet") is True
              and _plain("demo_vault2", "apiKey") == vkey
              and _plain("demo_vault", "apiKey") == secret,
              f"HTTP {r.status_code} v2={_plain('demo_vault2', 'apiKey') == vkey} "
              f"v1未串={_plain('demo_vault', 'apiKey') == secret}")

        # S13 库文件无明文（必须在 S12 清除**之前**跑：否则两个 canary 已被删掉，扫描就成了空转）
        blob = b""
        for suffix in ("", "-wal", "-shm"):
            p = os.environ["WECOM_DB_PATH"] + suffix
            if os.path.exists(p):
                with open(p, "rb") as f:
                    blob += f.read()
        canaries = (b"SECRET-PLAINTEXT-CANARY-9f3a", b"sk-demo-canary-7b2c")
        present = [s for s in canaries if s in blob]
        # 先确认「canary 确实进过库」（否则下面的扫描等于什么都没验）
        stored = (_plain("demo_vault", "apiKey"), _plain("demo_vault2", "apiKey"))
        leaks = present
        check("S13 库文件字节无明文凭据（db/-wal/-shm 全扫）",
              not leaks and stored[0] == "SECRET-PLAINTEXT-CANARY-9f3a"
              and stored[1] == "sk-demo-canary-7b2c",
              f"leaks={leaks} 真值可解出={stored[0] != '' and stored[1] != ''}")

        # S9 未声明字段
        r = c.put(f"{BASE}/api/v1/connectors/demo_vault/credentials",
                  json={"values": {"apiKey": "x", "nope": "y"}})
        check("S9 未声明字段被拒", r.status_code == 400, f"HTTP {r.status_code} {r.text[:80]}")

        # S10 provider=none 拒绝写入
        r = c.put(f"{BASE}/api/v1/connectors/qq_mail/credentials", json={"values": {"email": "a@b.c"}})
        check("S10 QQ邮箱无应用级凭据 ⇒ 400", r.status_code == 400, f"HTTP {r.status_code}")

        # S11 未知连接器 / 已下线连接器
        r = c.get(f"{BASE}/api/v1/connectors/not_exists")
        check("S11a 未知连接器 404", r.status_code == 404, f"HTTP {r.status_code}")
        gone = [c.get(f"{BASE}/api/v1/connectors/{code}").status_code
                for code in ("wechat_work", "wecom_group")]
        check("S11b 已下线连接器在注册表里查无此 code（404）", gone == [404, 404], str(gone))

        # S12 清除
        r = c.delete(f"{BASE}/api/v1/connectors/demo_vault/credentials")
        v3 = c.get(f"{BASE}/api/v1/connectors/demo_vault/credentials").json()
        check("S12 清除后 configured=false（且库里无残留真值）",
              r.status_code == 200 and v3.get("configured") is False
              and _plain("demo_vault", "apiKey") == "",
              f"HTTP {r.status_code}")

        # S14 工具目录未变
        r = c.get(f"{BASE}/api/v1/connectors").json()
        tc = {x["code"]: x["toolCount"] for x in r["connectors"]}
        check("S14 工具计数：wecom_cli 5 / 邮箱 6", tc.get("wecom_cli") == 5 and tc.get("qq_mail") == 6, str(tc))

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
