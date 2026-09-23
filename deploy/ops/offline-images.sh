#!/usr/bin/env bash
# ==============================================================================
# AIOA · 离线镜像搬运（deploy/ops/offline-images.sh）
# ------------------------------------------------------------------------------
# 场景：目标机（10.0.0.12）**拉不到 Docker Hub**（`dial tcp …:443: i/o timeout`），
#       而 compose 需要应用镜像 → 在**能上外网的机器**上导出成一个包，搬到目标机导入。
#
# ★ 单端口部署（docs/33）后，需要搬的镜像**只有 2 张**，而且全是本地构建：
#       aioa-server   （同时提供 H5 / 管理端 / 接口，见 deploy/Dockerfile.server）
#       aioa-agent
#   不再需要：nginx:1.27-alpine、aioa-web（静态已打进 server 镜像）、
#             ollama/ollama（知识库走 provider=local，零外部依赖）、minio（应用代码不读它）。
#   ⇒ 目标机无需能上外网，也无需任何基础镜像。
#
# ⚠️ 关键前提：`deploy/docker-compose.yml` 顶层写了 `name: aioa`，
#    因此两台机器构建出来的**镜像名完全一致**（aioa-server / aioa-agent），
#    目标机 `docker load` 之后直接 `docker compose up -d server agent`（**绝不要加 `--build`**）即可命中。
#
# ─── 在「能上外网 + 有 Docker」的机器上 ────────────────────────────────────────
#   git clone <仓库> && cd aioa
#   bash deploy/ops/offline-images.sh export            # 产出 aioa-images.tar.gz
#   scp aioa-images.tar.gz root@<目标机>:/opt/aioa/
#
# ─── 在目标机 10.0.0.12 上 ────────────────────────────────────────────────────
#   cd /opt/aioa
#   bash deploy/ops/offline-images.sh import aioa-images.tar.gz
#   bash deploy/ops/offline-images.sh list              # 核对齐备
#   cd deploy && docker compose up -d server agent
#
# 备选（目标机能上国内网、只是 Hub 不通）：其实本档已不需要任何外部镜像，
# 只要那台机器自己能 `docker compose build`，就不用搬包。搬包主要解决「连源码构建都做不了」。
# ==============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(cd "$SELF_DIR/.." && pwd)"

# 需要搬运的镜像（全部由本仓库构建；名称由 compose 的 `name: aioa` 决定）
BUILT_IMAGES=(aioa-server aioa-agent)
# 需要构建的 compose 服务名
BUILD_SERVICES=(server agent)

hr() { printf '\n\033[36m===== %s =====\033[0m\n' "$*"; }
die() { printf '\033[31m!! %s\033[0m\n' "$*" >&2; exit 1; }
need_docker() { command -v docker >/dev/null 2>&1 || die "本机没有 docker"; }

# ---------------------------------------------------------------- export
do_export() {
  local out="aioa-images.tar.gz"
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="$2"; shift 2 ;;
      *) die "未知参数：$1（可用：--out FILE）" ;;
    esac
  done
  need_docker
  cd "$DEPLOY_DIR" || die "进不去 $DEPLOY_DIR"

  hr "0) 准备 .env（只为让 compose 能渲染；占位符无所谓，构建不需要真实口令）"
  [ -f .env ] || { cp .env.production .env; echo "  已从 .env.production 生成占位 .env"; }
  docker compose config --quiet || die "compose 配置渲染失败，先修 .env 再导出"

  hr "1) 构建应用镜像（本机从源码构建，需外网拉 Maven / npm 依赖）"
  echo "  build ${BUILD_SERVICES[*]}"
  # aioa-server 的构建会顺带把前端产物打进镜像（Dockerfile.server 阶段 1），
  # 所以这里不需要单独构建 web。
  docker compose build "${BUILD_SERVICES[@]}" || die "构建失败"

  hr "2) 校验镜像名（必须与目标机期望的一致）"
  local miss=0 img
  for img in "${BUILT_IMAGES[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      printf '  ✅ %s\n' "$img"
    else
      printf '  ❌ %s  ← 不存在（镜像名对不上，load 到目标机也白搭）\n' "$img"; miss=1
    fi
  done
  [ "$miss" = 0 ] || die "有镜像缺失，已中止。请把上面清单发我。"

  hr "3) 导出为一个包（docker save | gzip）"
  local out_abs="$out"
  case "$out" in /*) ;; *) out_abs="$PWD/$out" ;; esac
  echo "  含：${BUILT_IMAGES[*]}"
  echo "  文件：$out_abs"
  docker save "${BUILT_IMAGES[@]}" | gzip -1 > "$out_abs" || die "docker save 失败"
  ls -lh "$out_abs" | sed 's/^/  /'

  hr "完成：把包拷到目标机（用隧道机 → 真实服务器那条既有通道）"
  echo "  scp $out_abs root@10.0.0.12:/opt/aioa/"
  echo "  目标机执行："
  echo "    cd /opt/aioa && bash deploy/ops/offline-images.sh import $out"
  echo "    cd /opt/aioa/deploy && docker compose up -d server agent   # 不要加 --build"
  echo "  验收：curl -s http://127.0.0.1:8080/actuator/health"
  echo "        curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8080/aioa/h5/"
}

# ---------------------------------------------------------------- import
do_import() {
  local f="${1:-}"; [ -n "$f" ] || die "用法： import <aioa-images.tar.gz>"
  [ -f "$f" ] || die "找不到文件：$f"
  need_docker
  hr "导入镜像（$f）"
  case "$f" in
    *.gz|*.tgz) gunzip -c "$f" | docker load ;;
    *)          docker load -i "$f" ;;
  esac || die "docker load 失败"
  do_list
  hr "下一步"
  echo "  cd $DEPLOY_DIR && docker compose up -d server agent"
  echo "  ⚠️ 不要加 --build —— 加了会尝试重新构建，而目标机拉不到基础镜像（maven/node 基础镜像都不在包里），必然失败。"
}

# ---------------------------------------------------------------- list
do_list() {
  need_docker
  hr "镜像齐备度（单端口部署：只需 aioa-server + aioa-agent）"
  local img
  for img in "${BUILT_IMAGES[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then printf '  ✅ %s\n' "$img"; else printf '  ❌ %s  ← 缺\n' "$img"; fi
  done
  echo "  现有全部镜像："
  docker images --format '    {{.Repository}}:{{.Tag}}  {{.Size}}' | head -40
}

case "${1:-}" in
  export) shift; do_export "$@" ;;
  import) shift; do_import "$@" ;;
  list)   shift; do_list "$@" ;;
  *) cat <<'EOF'
用法：
  # 在能上外网的机器上导出（只需 2 张镜像：aioa-server + aioa-agent，均为本地构建）
  bash deploy/ops/offline-images.sh export [--out FILE]

  # 在目标机上导入
  bash deploy/ops/offline-images.sh import <aioa-images.tar.gz>
  bash deploy/ops/offline-images.sh list              # 核对镜像齐备度

说明：单端口部署（docs/33）后不再需要 nginx / aioa-web / ollama / minio 镜像，
      管理端与用户端静态已随 aioa-server 镜像一起发布。
EOF
     exit 1 ;;
esac
