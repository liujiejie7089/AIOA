#!/usr/bin/env bash
# ============================================================
# AIOS 一键启动全部应用（在仓库根目录执行: bash start-all.sh）
# 幂等：按端口探测，已在运行的服务自动跳过；日志写入 logs/
# ============================================================
set -u
cd "$(dirname "$0")"
mkdir -p logs

# 本机运行时（隔离 venv 与 JDK，按需调整）
PY="C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
JAVA="C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java"
JAR="server/aios-boot/target/aios-boot-0.1.0-SNAPSHOT.jar"

# ---- 单端口静态目录：必须**显式**传给后端 ----
# application.yml 的默认值是**容器内**路径 ${AIOS_WEB_H5_DIR:/app/h5} / ${AIOS_WEB_WEB_DIR:/app/web}，
# 本机没有这两个 env ⇒ 在 Windows 上落到 `C:\app\h5`、`C:\app\web`（不存在）
# ⇒ `/aios/h5/`、`/aios/web/` **全部 404**，而 `/api/v1/**` 照常可用。
# 症状极易被误判成「前端产物没部署」，故此处显式传参并把缺失目录在启动前就喊出来。
ROOT="$(pwd)"
# ★ git bash 的 `pwd` 是 `/c/Users/...` 形式，Windows 上的 Java **认不出**这种路径
#   （会当成当前盘的 `\c\Users\...`）⇒ 交给 JVM 的每个路径都必须过 cygpath -m
#   转成正斜杠的 Windows 形式（`C:/Users/...`）。漏转 = 目录「不存在」⇒ 依旧 404。
winpath() { cygpath -m "$1" 2>/dev/null || echo "$1"; }
H5_DIR="${AIOS_WEB_H5_DIR:-$(winpath "$ROOT/user-client")}"
if [ -n "${AIOS_WEB_WEB_DIR:-}" ]; then
  WEB_DIR="$AIOS_WEB_WEB_DIR"
else
  # 与既有约定一致：管理端产物组装在 %TEMP%\aios-webroot（随系统清理会消失，故下面做存在性检查）
  # 注意 %LOCALAPPDATA% **不含** Temp 这一层，别拿它直接拼。
  if [ -n "${TEMP:-}" ]; then
    TMPROOT="$TEMP"
  elif [ -n "${LOCALAPPDATA:-}" ]; then
    TMPROOT="$LOCALAPPDATA\\Temp"
  else
    TMPROOT="$ROOT"
  fi
  WEB_DIR="$(winpath "$TMPROOT")/aios-webroot"
fi

static_precheck() {
  if [ ! -f "$H5_DIR/index.html" ]; then
    echo "[warn] 用户端 H5 目录缺 index.html：$H5_DIR ⇒ /aios/h5/ 将返回 404"
  fi
  if [ ! -f "$WEB_DIR/index.html" ]; then
    echo "[warn] 管理端目录缺 index.html：$WEB_DIR ⇒ /aios/web/ 将返回 404"
    echo "       从 web/apps/*/dist 重新组装："
    echo "       cp web/apps/shell/dist/index.html \"$WEB_DIR/index.html\" && cp -r web/apps/shell/dist/assets/. \"$WEB_DIR/assets/\""
  fi
}

port_up() { netstat -ano | grep -E ":$1[[:space:]]" | grep -q LISTENING; }

# ---- Gitee 接线：默认生产（授权跳转真的去 gitee.com）----
# 端到端回归需要把服务端接口与授权域指向本地桩 :8090，必须显式 opt-in，
# 否则「为什么没跳到真实 Gitee」就会变成一个查不出来的谜。
if [ "${AIOS_GITEE_E2E:-0}" = "1" ]; then
  # shellcheck disable=SC1091
  . scripts/gitee-e2e-env.sh
  echo "[gitee] 端到端回归接线已启用：服务端接口与授权跳转均指向本地桩 :8090"
  echo "        （用户不会到达真实 Gitee，绑定结果页会显式标注）"
else
  echo "[gitee] 使用生产默认：授权跳转 = https://gitee.com"
  echo "        如需本地桩接线（跑 Gitee 套件）请用：AIOS_GITEE_E2E=1 bash start-all.sh"
fi

# ---- Java 后端 :8080 ----
if port_up 8080; then
  echo "[skip] backend :8080 already running"
else
  if [ ! -f "$JAR" ]; then
    echo "[warn] $JAR 不存在，先执行: cd server && bash mvnw -DskipTests package"
  else
    static_precheck
    echo "[start] backend :8080 (logs/boot.log)"
    echo "        h5-dir =$H5_DIR"
    echo "        web-dir=$WEB_DIR"
    "$JAVA" -Dspring.flyway.validate-on-migrate=false -jar "$JAR" \
      --aios.web.h5-dir="$H5_DIR" \
      --aios.web.web-dir="$WEB_DIR" > logs/boot.log 2>&1 &
  fi
fi

# ---- Python Agent :8000 ----
# --http 必须显式钉成 httptools：它决定「后端的 h2c 升级请求体会不会丢」——
# 跑 httptools（= uvicorn[standard]，与 deploy/Dockerfile.agent 的生产镜像一致）时会丢，
# 跑 h11 时会被 h11 悄悄兜住。auto 会让这个差异随 venv 是否装了 httptools 而漂移，
# 于是「本地过、生产不过 / 本地掩盖了缺陷」都会发生。宁可启动即报错，也不要静默换实现。
#
# ★ 解释器必须用 agent/.venv，**不能**用上面的通用 PY：
#   ASR（语音识别）依赖 faster-whisper（agent/pyproject.toml 的必装依赖），它只装在 agent/.venv 里。
#   用 PY（envs/default）起 agent 时语音接口会直接 503「未安装 faster-whisper」，
#   现象是「电脑端语音也用不了」——本机曾长期如此。agent/.venv 同时装有 httptools，
#   故下面的 --http httptools 依旧成立（两个包都已实测确认存在）。
#   缺了不静默退化：启动前明确喊出来，避免「以为语音能用」。
ASR_PY="$ROOT/agent/.venv/Scripts/python.exe"
if [ ! -f "$ASR_PY" ]; then
  echo "[warn] 找不到 $ASR_PY ⇒ 本地语音识别（ASR）将不可用（改回通用 PY 启动 agent）。"
  echo "       重建：python -m venv agent/.venv && agent/.venv/Scripts/python.exe -m pip install -e agent"
  ASR_PY="$PY"
elif ! "$ASR_PY" -c "import faster_whisper" >/dev/null 2>&1; then
  echo "[warn] $ASR_PY 里没有 faster-whisper ⇒ 本地语音识别（ASR）将不可用。"
  echo "       修复：\"$ASR_PY\" -m pip install faster-whisper"
fi
if port_up 8000; then
  echo "[skip] agent :8000 already running"
else
  echo "[start] agent :8000 (logs/agent.log, --http httptools)"
  ( cd agent && "$ASR_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --http httptools ) > logs/agent.log 2>&1 &
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
echo "AIOS 全部应用（等 10~20s 后端就绪）："
echo "  用户端 H5     http://127.0.0.1:5181   账号 zhangsan/User@123 或 admin/Admin@123"
echo "  管理端 shell  http://localhost:5173   账号 admin/Admin@123"
echo "  工单应用      http://localhost:5174"
echo "  调度应用      http://localhost:5175"
echo "  Java 后端     http://localhost:8080   健康: /actuator/health"
echo "  Agent 服务    http://localhost:8000   健康: /health"
