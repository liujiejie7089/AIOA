# mcp-hub：MCP 网关（Streamable HTTP，:8099）
# 无状态、不落盘、不持任何凭据 —— 只把 mcp__<code>__<tool> 调用转给 Java 的
# POST /api/v1/mcp/builtin/<code>/call，并透传调用方的 Authorization。
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_HUB_PORT=8099 \
    MCP_HUB_HOST=0.0.0.0

WORKDIR /app

# 先装依赖再加代码，改代码不会打掉依赖层
COPY requirements.txt ./
# ★ 构建期依赖源**必须可覆盖**：国内服务器直连 pypi.org 实测 13 kB/s（一个 4.8MB 的
#   cryptography 轮子跑了 1471 秒），而走清华源同样的依赖只要 40~50 秒。
#   与 deploy/Dockerfile.agent 完全同一套口子：镜像源写在 .env / --build-arg 里，
#   **本文件保持干净**（手改这里会让生产机 git pull 永远被未提交改动挡住）。
#     在 deploy/.env 里设 PIP_EXTRA_ARGS，或临时：
#     docker compose build --build-arg PIP_EXTRA_ARGS="-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn" mcp-hub
#   留空 = 走上游默认源，行为与改造前完全一致。
ARG PIP_EXTRA_ARGS=
RUN pip install ${PIP_EXTRA_ARGS} --no-cache-dir -r requirements.txt

COPY run.py ./
COPY mcp_hub ./mcp_hub

# 非 root：本进程只做 HTTP 转发，不需要任何写权限
RUN useradd -m -u 10001 hub
USER hub

EXPOSE 8099

# 健康检查用 python 自带 urllib（slim 镜像没有 curl）
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/health')" || exit 1

CMD ["python", "run.py"]
