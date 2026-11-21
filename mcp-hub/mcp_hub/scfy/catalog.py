# -*- coding: utf-8 -*-
"""scfy 工具目录（只读）。

事实源是 Java 侧 `cn.aios.integration.scfy.contract.ScfyCatalog`，由
`ScfyMcpCatalogExportTest -Dscfy.mcp.export=true` 导出成本目录的 catalog.json。
本文件只读它、不重述任何接口事实 —— 接口参数名/必填性/枚举在 scfy 里错一个就会
「静默返回空集」，绝不手抄第二份。

base-url 由环境变量 AIOS_SCFY_BASE_URL 注入，默认直连官网域名
https://szbhpt.tsichuan.com/scfy（免登录 /show/*）。本机测试服务
http://127.0.0.1:16060/scfy 仅排障时显式覆盖，不给默认值。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SERVER_CODE = "scfy"
SERVER_NAME = "四川非遗（scfy）"

_CATALOG_PATH = Path(__file__).with_name("catalog.json")


def _load() -> list[dict]:
    if not _CATALOG_PATH.is_file():
        raise RuntimeError(
            f"scfy 工具目录缺失：{_CATALOG_PATH}。"
            "请在 server/ 下运行 mvn -pl aios-integration-scfy test "
            "-Dtest=ScfyMcpCatalogExportTest -Dscfy.mcp.export=true 生成"
        )
    data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    tools = data["tools"]
    # Java 导出器用 id/summary/inputSchema；registry.probe 与通用代理按
    # name/description/input_schema/read_only 读取（与 wecom_cli/specs 同口径）。
    # 这里补别名，两处消费同一份数据，不改导出器也不改 probe。
    for t in tools:
        t.setdefault("name", t["id"])
        t.setdefault("description", t["summary"])
        t.setdefault("input_schema", t["inputSchema"])
        t.setdefault("read_only", True)
    return tools


TOOLS: list[dict] = _load()

# name -> 工具定义，供 server 动态注册时查 schema / 必填 / 路径
BY_NAME: dict[str, dict] = {t["id"]: t for t in TOOLS}


def base_url() -> str:
    return os.environ.get("AIOS_SCFY_BASE_URL", "https://szbhpt.tsichuan.com/scfy").rstrip("/")


def tool_count() -> int:
    return len(TOOLS)
