# -*- coding: utf-8 -*-
"""mcp-hub 入口：uvicorn 起 mcp_hub.app:app，端口 MCP_HUB_PORT（默认 8099）。"""

import logging
import os
import sys

# 让 `import mcp_hub` 可用（run.py 与 mcp_hub/ 同目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_hub.app import app  # noqa: E402
from mcp_hub.builtin import SERVER_INFO  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [mcp-hub] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_hub")

PORT = int(os.environ.get("MCP_HUB_PORT", "8099"))
HOST = os.environ.get("MCP_HUB_HOST", "0.0.0.0")
BASE = os.environ.get("AIOS_SERVER_BASE_URL", "http://127.0.0.1:8080")


def main():
    servers_str = ", ".join(f"{c}({n})" for c, n in SERVER_INFO.items())
    logger.info("mcp-hub listening on :%s, servers: %s", PORT, servers_str)
    logger.info("转发目标 AIOS_SERVER_BASE_URL=%s", BASE)
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
