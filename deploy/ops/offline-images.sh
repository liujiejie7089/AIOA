#!/usr/bin/env bash
# ==============================================================================
# AIOA · 离线镜像搬运（deploy/ops/offline-images.sh）
# ------------------------------------------------------------------------------
# 场景：目标机（10.0.0.12）**拉不到 Docker Hub**（`dial tcp …:443: i/o timeout`），
#       而 compose 又需要 5 个镜像 → 在**能上外网的机器**上导出成一个包，搬到目标机导入。
#
# ⚠️ 关键前提：`deploy/docker-compose.yml` 顶层写了 `name: aioa`，
#    因此两台机器构建出来的**镜像名完全一致**（aioa-server / aioa-agent / aioa-web），
#    目标机 `docker load` 之后直接 `docker compose up -d`（**绝不要加 `--build`**）即可命中。
#
# ─── 在「能上外网 + 有 Docker」的机器上 ────────────────────────────────────────
#   git clone <仓库> && cd aioa
#   bash deploy/ops/offline-images.sh export                 # 产出 aioa-images.tar.gz
#   bash deploy/ops/offline-images.sh export --with-ollama   # 连语义嵌入模型一起带
#   scp aioa-images.tar.gz [ollama-models.tar.gz] root@<目标机>:/opt/aioa/
#
# ─── 在目标机 10.0.0.12 上 ────────────────────────────────────────────────────
#   cd /opt/aioa
#   bash deploy/ops/offline-images.sh import aioa-images.tar.gz
#   bash deploy/ops/offline-images.sh import-ollama ollama-models.tar.gz   # 如带了
#   bash deploy/ops/offline-images.sh list                                 # 核对齐备
#
# 备选（目标机能上国内网、只是 Hub 不通）：先别搬包，改走 §5.0 的「镜像加速器」。
# ==============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(cd "$SELF_DIR/.." && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"

# 默认档必需：外部镜像 2 个 + 本地构建 3 个（名称由 compose 的 name: aioa 决定）
EXT_IMAGES=(minio/minio:latest nginx:1.27-alpine)
BUILT_IMAGES=(aioa-server aioa-agent aioa-web)
OLLAMA_IMAGE=ollama/ollama:latest
OLLAMA_MODEL="${AIOA_KB_EMBEDDING_MODEL:-quentinz/bge-small-zh-v1.5}"
OLLAMA_VOLUME=aioa_ollamadata

hr() { printf '\n\033[36m===== %s =====\033[0m\n' "$*"; }
die() { printf '\033[31m!! %s\033[0m\n' "$*" >&2; exit 1; }
need_docker() { command -v docker >/dev/null 2>&1 || die "本机没有 docker"; }

# ---------------------------------------------------------------- export
do_export() {
  local out="aioa-images.tar.gz" with_ollama=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="$2"; shift 2 ;;
      --with-ollama) with_ollama=1; shift ;;
      *) die "未知参数：$1" ;;
    esac
  done
  need_docker
  cd "$DEPLOY_DIR" || die "进不去 $DEPLOY_DIR"

  hr "0) 准备 .env（只为让 compose 能渲染；占位符无所谓，构建不需要真实口令）"
  [ -f .env ] || { cp .env.production .env; echo "  已从 .env.production 生成占位 .env"; }
  docker compose config --quiet || die "compose 配置渲染失败，先修 .env 再导出"

  hr "1) 拉取外部镜像"
  for img in "${EXT_IMAGES[@]}"; do
    echo "  pull $img"
    docker pull "$img" || die "拉取失败：$img（本机必须能上外网）"
  done
  if [ "$with_ollama" = 1 ]; then
    echo "  pull $OLLAMA_IMAGE"
    docker pull "$OLLAMA_IMAGE" || die "拉取失败：$OLLAMA_IMAGE"
  fi

  hr "2) 构建三个应用镜像（这一步会在本机从源码构建，需外网拉依赖）"
  docker compose build server agent web || die "构建失败"

  hr "3) 校验镜像名（必须与目标机期望的一致）"
  local all=("${EXT_IMAGES[@]}" "${BUILT_IMAGES[@]}")
  [ "$with_ollama" = 1 ] && all+=("$OLLAMA_IMAGE")
  local miss=0
  for img in "${all[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      printf '  ✅ %s\n' "$img"
    else
      printf '  ❌ %s  ← 不存在（镜像名对不上，load 到目标机也白搭）\n' "$img"; miss=1
    fi
  done
  [ "$miss" = 0 ] || die "有镜像缺失，已中止。请把上面清单发我。"

  hr "4) 导出为一个包（docker save | gzip）"
  echo "  文件：$PWD/$out"
  docker save "${all[@]}" | gzip -1 > "$out" || die "docker save 失败"
  ls -lh "$out" | sed 's/^/  /'

  if [ "$with_ollama" = 1 ]; then
    hr "5) 导出 Ollama 语义嵌入模型（$OLLAMA_MODEL）"
    docker compose --profile ollama up -d ollama || die "起 ollama 失败"
    for i in $(seq 1 30); do
      docker exec aioa-ollama ollama list >/dev/null 2>&1 && break
      sleep 2
    done
    docker exec aioa-ollama ollama pull "$OLLAMA_MODEL" || die "拉模型失败：$OLLAMA_MODEL"
    docker run --rm -v "$OLLAMA_VOLUME":/m -v "$PWD":/out "${EXT_IMAGES[1]}" \
      tar -C /m -czf "/out/ollama-models.tar.gz" models || die "打包模型目录失败"
    ls -lh ollama-models.tar.gz | sed 's/^/  /'
    docker compose --profile ollama stop ollama >/dev/null 2>&1 || true
  fi

  hr "完成：把包拷到目标机"
  echo "  scp $out${with_ollama:+ ollama-models.tar.gz} root@10.0.0.12:/opt/aioa/"
  echo "  目标机执行："
  echo "    cd /opt/aioa && bash deploy/ops/offline-images.sh import $out"
  [ "$with_ollama" = 1 ] && echo "    bash deploy/ops/offline-images.sh import-ollama ollama-models.tar.gz"
  echo "  然后（**不要加 --build**）："
  echo "    cd deploy && docker compose --profile ollama up -d"
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
  echo "  cd $DEPLOY_DIR && docker compose --profile ollama up -d"
  echo "  ⚠️ 不要加 --build —— 加了会尝试重新构建，而目标机拉不到基础镜像，必然失败。"
}

do_import_ollama() {
  local f="${1:-}"; [ -n "$f" ] || die "用法： import-ollama <ollama-models.tar.gz>"
  [ -f "$f" ] || die "找不到文件：$f"
  need_docker
  hr "导入 Ollama 模型到命名卷 $OLLAMA_VOLUME"
  docker volume create "$OLLAMA_VOLUME" >/dev/null
  local tmp="$PWD/.ollama-models-tmp"
  rm -rf "$tmp"; mkdir -p "$tmp"
  gunzip -c "$f" | tar -C "$tmp" -xf - || die "解包失败"
  docker run --rm -v "$OLLAMA_VOLUME":/dst -v "$tmp":/src:ro nginx:1.27-alpine \
    sh -c 'cp -a /src/models /dst/ && echo "  卷内模型：" && ls /dst/models/manifests/registry.ollama.ai/library/ 2>/dev/null' \
    || die "写入卷失败"
  rm -rf "$tmp"
  echo "  完成。注意卷里若已有旧模型，这里是覆盖同名目录。"
}

# ---------------------------------------------------------------- list
do_list() {
  need_docker
  hr "镜像齐备度"
  local img
  for img in "${EXT_IMAGES[@]}" "${BUILT_IMAGES[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then printf '  ✅ %s\n' "$img"; else printf '  ❌ %s  ← 缺\n' "$img"; fi
  done
  if docker image inspect "$OLLAMA_IMAGE" >/dev/null 2>&1; then
    printf '  ✅ %s\n' "$OLLAMA_IMAGE"
    local n
    n=$(docker run --rm -v "$OLLAMA_VOLUME":/m "$OLLAMA_IMAGE" sh -c 'ls /m/models/manifests/registry.ollama.ai/library/ 2>/dev/null | wc -l' 2>/dev/null || echo 0)
    printf '  %s 卷内模型数量：%s（要语义嵌入需 ≥1）\n' "$([ "${n:-0}" -ge 1 ] && echo ✅ || echo ⚪)" "${n:-0}"
  else
    printf '  ⚪ %s（未装；不启 ollama 则知识库语义嵌入不可用）\n' "$OLLAMA_IMAGE"
  fi
  echo "  现有全部镜像："
  docker images --format '    {{.Repository}}:{{.Tag}}  {{.Size}}' | head -40
}

case "${1:-}" in
  export)        shift; do_export "$@" ;;
  import)        shift; do_import "$@" ;;
  import-ollama) shift; do_import_ollama "$@" ;;
  list)          do_list ;;
  *) cat <<'EOF'
用法：
  bash deploy/ops/offline-images.sh export [--with-ollama] [--out FILE]   # 在能上外网的机器上
  bash deploy/ops/offline-images.sh import <aioa-images.tar.gz>           # 在目标机上
  bash deploy/ops/offline-images.sh import-ollama <ollama-models.tar.gz>  # 如带了模型
  bash deploy/ops/offline-images.sh list                                  # 核对镜像齐备度
EOF
     exit 1 ;;
esac
