#!/usr/bin/env bash
# ==============================================================================
# AIOA · 离线镜像搬运（deploy/ops/offline-images.sh）
# ------------------------------------------------------------------------------
# 场景：目标机（10.0.0.12）**拉不到 Docker Hub**（`dial tcp …:443: i/o timeout`），
#       而 compose 又需要若干基础镜像 → 在**能上外网的机器**上导出成一个包，搬到目标机导入。
#       需要搬几个取决于怎么起（见下面两种档位）：
#         完整档        = minio + nginx + aioa-server + aioa-agent + aioa-web  （5 个）
#         只起后端档    = aioa-server + aioa-agent                              （2 个）
#                         ← 目标机 10.0.0.12 本次采用：不用边缘 nginx，也不用 MinIO
#                           （**应用代码根本不读 MinIO**，文件落本地盘 /app/uploads）
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
# 只起后端（不用边缘 nginx、不用 compose 自带 minio）时的子集：**只有 2 个，全是本地构建**
#   - nginx:1.27-alpine 不用：没有边缘 nginx，管理端静态也不由本机托管
#     （aioa-web 的运行底座本身就是 nginx:1.27-alpine ⇒ 不用它俩时连 nginx 镜像都不用搬）
#   - minio/minio:latest 不用：**应用代码根本不使用 MinIO**（全仓无 S3 客户端；文件落本地盘
#     /app/uploads 已挂命名卷）。外部那台 MinIO（172.16.8.249）与本项目无关，直接不接。
#   ⇒ 外部镜像数组**故意留空**：少搬一个 ~150MB 且永远不启的镜像。
EXT_IMAGES_BACKEND=()
BUILT_IMAGES_BACKEND=(aioa-server aioa-agent)
OLLAMA_IMAGE=ollama/ollama:latest
OLLAMA_MODEL="${AIOA_KB_EMBEDDING_MODEL:-quentinz/bge-small-zh-v1.5}"
OLLAMA_VOLUME=aioa_ollamadata

hr() { printf '\n\033[36m===== %s =====\033[0m\n' "$*"; }
die() { printf '\033[31m!! %s\033[0m\n' "$*" >&2; exit 1; }
need_docker() { command -v docker >/dev/null 2>&1 || die "本机没有 docker"; }

# ---------------------------------------------------------------- export
do_export() {
  local out="aioa-images.tar.gz" with_ollama=0 backend_only=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="$2"; shift 2 ;;
      --with-ollama) with_ollama=1; shift ;;
      --backend-only)
        backend_only=1
        EXT_IMAGES=("${EXT_IMAGES_BACKEND[@]}")
        BUILT_IMAGES=("${BUILT_IMAGES_BACKEND[@]}")
        out="aioa-images-backend.tar.gz"
        shift ;;
      *) die "未知参数：$1" ;;
    esac
  done
  need_docker
  cd "$DEPLOY_DIR" || die "进不去 $DEPLOY_DIR"

  hr "0) 准备 .env（只为让 compose 能渲染；占位符无所谓，构建不需要真实口令）"
  [ -f .env ] || { cp .env.production .env; echo "  已从 .env.production 生成占位 .env"; }
  docker compose config --quiet || die "compose 配置渲染失败，先修 .env 再导出"
  [ "$backend_only" = 1 ] && echo "  模式：--backend-only（只搬 ${BUILT_IMAGES[*]}；不含 nginx / web / minio）"

  hr "1) 拉取外部镜像"
  if [ "${#EXT_IMAGES[@]}" -gt 0 ]; then
    for img in "${EXT_IMAGES[@]}"; do
      echo "  pull $img"
      docker pull "$img" || die "拉取失败：$img（本机必须能上外网）"
    done
  else
    echo "  （本档无需外部镜像 —— 全是本地构建，不需要 docker pull）"
  fi
  if [ "$with_ollama" = 1 ]; then
    echo "  pull $OLLAMA_IMAGE"
    docker pull "$OLLAMA_IMAGE" || die "拉取失败：$OLLAMA_IMAGE"
  fi

  hr "2) 构建应用镜像（这一步会在本机从源码构建，需外网拉依赖）"
  if [ "$backend_only" = 1 ]; then
    echo "  build server agent"
    docker compose build server agent || die "构建失败"
  else
    echo "  build server agent web"
    docker compose build server agent web || die "构建失败"
  fi

  hr "3) 校验镜像名（必须与目标机期望的一致）"
  # 注意：EXT_IMAGES 在 --backend-only 下是**空数组**，而 `set -u` + 老 bash 下 "${arr[@]}" 会报
  # unbound ⇒ 一律先判长度再展开，不写 `("${A[@]}" "${B[@]}")` 这种混合形式。
  local all=()
  [ "${#EXT_IMAGES[@]}" -gt 0 ] && all+=("${EXT_IMAGES[@]}")
  all+=("${BUILT_IMAGES[@]}")
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

  hr "4) 导出应用侧为一个包（docker save | gzip）"
  local base=()
  [ "${#EXT_IMAGES[@]}" -gt 0 ] && base+=("${EXT_IMAGES[@]}")
  base+=("${BUILT_IMAGES[@]}")
  local out_abs="$out"
  case "$out" in /*) ;; *) out_abs="$PWD/$out" ;; esac
  echo "  含：${base[*]}"
  echo "  文件：$out_abs"
  docker save "${base[@]}" | gzip -1 > "$out_abs" || die "docker save 失败"
  ls -lh "$out_abs" | sed 's/^/  /'

  if [ "$with_ollama" = 1 ]; then
    hr "5) 导出 Ollama（**单独成包**，方便先起应用侧、后补语义嵌入）"
    echo "  镜像包：$PWD/ollama-image.tar.gz（约 1.5G，比上面那个大）"
    docker save "$OLLAMA_IMAGE" | gzip -1 > ollama-image.tar.gz || die "导出 ollama 镜像失败"
    ls -lh ollama-image.tar.gz | sed 's/^/  /'

    echo "  模型包：$PWD/ollama-models.tar.gz（$OLLAMA_MODEL）"
    docker compose --profile ollama up -d ollama || die "起 ollama 失败"
    for i in $(seq 1 30); do
      docker exec aioa-ollama ollama list >/dev/null 2>&1 && break
      sleep 2
    done
    docker exec aioa-ollama ollama pull "$OLLAMA_MODEL" || die "拉模型失败：$OLLAMA_MODEL"
    # 用 docker cp + 宿主 tar 打包，**不依赖任何第三张镜像**（曾用 ${EXT_IMAGES[1]} 取 nginx 当搬运容器，
    # 但 --backend-only 模式下该数组只有 1 个元素 ⇒ 越界，set -u 会直接终止脚本）
    local tmp="./.ollama-export-tmp"
    rm -rf "$tmp"; mkdir -p "$tmp"
    docker cp aioa-ollama:/root/.ollama/models "$tmp/models" || die "导出模型目录失败（容器在跑吗？）"
    tar -czf ollama-models.tar.gz -C "$tmp" models || die "打包模型目录失败"
    rm -rf "$tmp"
    ls -lh ollama-models.tar.gz | sed 's/^/  /'
    docker compose --profile ollama stop ollama >/dev/null 2>&1 || true
  fi

  hr "完成：把包拷到目标机（用隧道机 → 真实服务器那条既有通道）"
  # ⚠️ 这里不能用 ${with_ollama:+...}：with_ollama=0 时它是**非空字符串**，那样也会展开
  local extra=""
  [ "$with_ollama" = 1 ] && extra=" ollama-image.tar.gz ollama-models.tar.gz"
  echo "  scp ${out_abs}${extra} root@10.0.0.12:/opt/aioa/"
  echo "  目标机执行："
  echo "    cd /opt/aioa && bash deploy/ops/offline-images.sh import $out"
  if [ "$backend_only" = 1 ]; then
    echo "    # 只起后端（不用 nginx），并把 8080/8000 发布到宿主："
    echo "    cd deploy && docker compose -f docker-compose.yml -f docker-compose.backend.yml up -d server agent"
  else
    echo "    cd deploy && docker compose --profile ollama up -d      # 不要加 --build"
  fi
  if [ "$with_ollama" = 1 ]; then
    echo "    # 验收通过后，再补语义嵌入："
    echo "    bash deploy/ops/offline-images.sh import ollama-image.tar.gz"
    echo "    bash deploy/ops/offline-images.sh import-ollama ollama-models.tar.gz"
    echo "    docker compose --profile ollama up -d"
  fi
}

# ---------------------------------------------------------------- import
do_import() {
  local f="${1:-}"; [ -n "$f" ] || die "用法： import <aioa-images.tar.gz> [--backend-only]"
  [ -f "$f" ] || die "找不到文件：$f"
  local list_flag=""
  [ "${2:-}" = "--backend-only" ] && list_flag="--backend-only"
  need_docker
  hr "导入镜像（$f）"
  case "$f" in
    *.gz|*.tgz) gunzip -c "$f" | docker load ;;
    *)          docker load -i "$f" ;;
  esac || die "docker load 失败"
  do_list $list_flag
  hr "下一步"
  echo "  只起后端（不用边缘 nginx，本次 10.0.0.12 的走法）："
  echo "    cd $DEPLOY_DIR && docker compose -f docker-compose.yml -f docker-compose.backend.yml up -d server agent"
  echo "  或用完整档（自带 nginx 80/81）："
  echo "    cd $DEPLOY_DIR && docker compose up -d"
  echo "  ⚠️ 都不要加 --build —— 加了会尝试重新构建，而目标机拉不到基础镜像，必然失败。"
}

do_import_ollama() {
  local f="${1:-}"; [ -n "$f" ] || die "用法： import-ollama <ollama-models.tar.gz>"
  [ -f "$f" ] || die "找不到文件：$f"
  need_docker
  hr "导入 Ollama 模型到命名卷 $OLLAMA_VOLUME"
  docker volume create "$OLLAMA_VOLUME" >/dev/null
  # 直接写卷在宿主上的真实目录 —— 不借任何搬运镜像
  # （曾用 nginx:1.27-alpine 容器挂卷来拷，但 --backend-only 模式没有这张镜像）
  local root dst
  root="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
  dst="$root/volumes/${OLLAMA_VOLUME}/_data"
  [ -d "$dst" ] || die "拿不到卷目录：$dst（需要 root；或检查 DockerRootDir）"

  local tmp="./.ollama-import-tmp"
  rm -rf "$tmp"; mkdir -p "$tmp"
  gunzip -c "$f" | tar -C "$tmp" -xf - || { tar -xzf "$f" -C "$tmp"; } || die "解包失败"
  [ -d "$tmp/models" ] || die "包内没有 models/ 目录（$f 不像模型包）"

  mkdir -p "$dst/models"
  cp -a "$tmp/models/." "$dst/models/" || die "写入卷失败"
  rm -rf "$tmp"
  echo "  已写入：$dst/models"
  echo "  卷内模型目录："
  ls "$dst/models/manifests/registry.ollama.ai/library/" 2>/dev/null | sed 's/^/    /' || echo "    (空)"
}

# ---------------------------------------------------------------- list
do_list() {
  local backend_only=0
  [ "${1:-}" = "--backend-only" ] && backend_only=1
  need_docker
  # 数组按模式选（此前这里只改了标题、清单仍取完整档 ⇒ --backend-only 会把 nginx/aioa-web 报成「缺」）
  local want=()
  if [ "$backend_only" = 1 ]; then
    hr "镜像齐备度（后端模式：不用 nginx / web / minio）"
    [ "${#EXT_IMAGES_BACKEND[@]}" -gt 0 ] && want+=("${EXT_IMAGES_BACKEND[@]}")
    want+=("${BUILT_IMAGES_BACKEND[@]}")
  else
    hr "镜像齐备度（完整档：含 nginx + 管理端静态）"
    want+=("${EXT_IMAGES[@]}" "${BUILT_IMAGES[@]}")
  fi
  local img
  for img in "${want[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then printf '  ✅ %s\n' "$img"; else printf '  ❌ %s  ← 缺\n' "$img"; fi
  done
  if [ "$backend_only" = 0 ]; then
    echo "  （当前为完整档；只起后端时可加 --backend-only 复核，那时 nginx 与 aioa-web 都不需要）"
  else
    echo "  （后端模式不需要 nginx:1.27-alpine / aioa-web / minio/minio）"
  fi
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
  list)          shift; do_list "$@" ;;
  *) cat <<'EOF'
用法：
  # 在能上外网的机器上导出（默认完整档：minio + nginx + aioa-server + aioa-agent + aioa-web）
  bash deploy/ops/offline-images.sh export [--with-ollama] [--backend-only] [--out FILE]
      --backend-only  只导出后端所需的 **2 个**镜像：aioa-server + aioa-agent
                      （不用边缘 nginx、不托管管理端静态、也不用 compose 自带 minio；
                        产出 aioa-images-backend.tar.gz）
      --with-ollama   额外导出 ollama 镜像与语义嵌入模型（单独成包）

  # 在目标机上导入（对上面两种包都适用；末尾可见 --backend-only 来核对后端档清单）
  bash deploy/ops/offline-images.sh import <aioa-images[-backend].tar.gz> [--backend-only]
  bash deploy/ops/offline-images.sh import-ollama <ollama-models.tar.gz>
  bash deploy/ops/offline-images.sh list [--backend-only]    # 核对镜像齐备度
EOF
     exit 1 ;;
esac
