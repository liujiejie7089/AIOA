#!/usr/bin/env bash
# ============================================================
# AIOA 一键启动全部应用（在仓库根目录执行: bash start-all.sh）
# 幂等：按端口探测，已在运行的服务自动跳过；日志写入 logs/
# ============================================================
set -u
cd "$(dirname "$0")"
mkdir -p logs

# 本机运行时（隔离 venv 与 JDK，按需调整）
PY="C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
JAVA="C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java"
JAR="server/aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar"

port_up() { netstat -ano | grep -E ":$1[[:space:]]" | grep -q LISTENING; }

# ---- Gitee 接线：默认生产（授权跳转真的去 gitee.com）----
# 端到端回归需要把服务端接口与授权域指向本地桩 :8090，必须显式 opt-in，
# 否则「为什么没跳到真实 Gitee」就会变成一个查不出来的谜。
if [ "${AIOA_GITEE_E2E:-0}" = "1" ]; then
  # shellcheck disable=SC1091
  . scripts/gitee-e2e-env.sh
  echo "[gitee] 端到端回归接线已启用：服务端接口与授权跳转均指向本地桩 :8090"
  echo "        （用户不会到达真实 Gitee，绑定结果页会显式标注）"
else
  echo "[gitee] 使用生产默认：授权跳转 = https://gitee.com"
  echo "        如需本地桩接线（跑 Gitee 套件）请用：AIOA_GITEE_E2E=1 bash start-all.sh"
fi

# ---- Java 后端 :8080 ----
if port_up 8080; then
  echo "[skip] backend :8080 already running"
else
  if [ ! -f "$JAR" ]; then
    echo "[warn] $JAR 不存在，先执行: cd server && bash mvnw -DskipTests package"
  else
    echo "[start] backend :8080 (logs/boot.log)"
    "$JAVA" -Dspring.flyway.validate-on-migrate=false -jar "$JAR" > logs/boot.log 2>&1 &
  fi
fi

# ---- Python Agent :8000 ----
# --http 必须显式钉成 httptools：它决定「后端的 h2c 升级请求体会不会丢」——
# 跑 httptools（= uvicorn[standard]，与 deploy/Dockerfile.agent 的生产镜像一致）时会丢，
# 跑 h11 时会被 h11 悄悄兜住。auto 会让这个差异随 venv 是否装了 httptools 而漂移，
# 于是「本地过、生产不过 / 本地掩盖了缺陷」都会发生。宁可启动即报错，也不要静默换实现。
if port_up 8000; then
  echo "[skip] agent :8000 already running"
else
  echo "[start] agent :8000 (logs/agent.log, --http httptools)"
  ( cd agent && "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --http httptools ) > logs/agent.log 2>&1 &
fi

# ---- 用户端 H5 :5181（读 user-client/.env）----
if port_up 5181; then
  echo "[skip] user-client :5181 already running"
else
  echo "[start] user-client :5181 (logs/user-client.log)"
  ( cd user-client && "$PY" serve.py ) > logs/user-client.log 2>&1 &
fi

# ---- 管理端三应用 :5173/5174/5175（各自读 .env）----
if port_up 5173; then
  echo "[skip] web apps already running"
else
  echo "[start] web apps shell/ticket/dispatch (logs/web-dev.log)"
  ( cd web && pnpm -r --parallel dev ) > logs/web-dev.log 2>&1 &
fi

echo ""
echo "AIOA 全部应用（等 10~20s 后端就绪）："
echo "  用户端 H5     http://127.0.0.1:5181   账号 zhangsan/User@123 或 admin/Admin@123"
echo "  管理端 shell  http://localhost:5173   账号 admin/Admin@123"
echo "  工单应用      http://localhost:5174"
echo "  调度应用      http://localhost:5175"
echo "  Java 后端     http://localhost:8080   健康: /actuator/health"
echo "  Agent 服务    http://localhost:8000   健康: /health"
