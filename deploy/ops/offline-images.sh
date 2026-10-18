#!/usr/bin/env bash
# ==============================================================================
# AIOS · 离线镜像搬运（deploy/ops/offline-images.sh）
# ------------------------------------------------------------------------------
# 场景：目标机（10.0.0.3）**拉不到 Docker Hub**（`dial tcp …:443: i/o timeout`），
#       而 compose 需要应用镜像 → 在**能上外网的机器**上导出成一个包，搬到目标机导入。
#
# ★ 单端口部署（docs/33）后，需要搬的镜像**只有 2 张**，而且全是本地构建：
#       aios-server   （同时提供 H5 / 管理端 / 接口，见 deploy/Dockerfile.server）
#       aios-agent
#   必需的就是这 2 张；此外 **可选** 1 张：nginx:1.27-alpine
#   （只在要 /web、/user 短路径入口时才需要 → 导出时加 `--with-nginx`）。
#   已彻底不需要：aios-web（静态已打进 server 镜像）、
#                ollama/ollama（知识库走 provider=local，零外部依赖）、minio（应用代码不读它）。
#   ⇒ 目标机无需能上外网，也无需任何基础镜像。
#
# ⚠️ 关键前提：`deploy/docker-compose.yml` 顶层写了 `name: aios`，
#    因此两台机器构建出来的**镜像名完全一致**（aios-server / aios-agent），
#    目标机 `docker load` 之后直接 `docker compose up -d server agent`（**绝不要加 `--build`**）即可命中。
#
# ─── 在「能上外网 + 有 Docker」的机器上 ────────────────────────────────────────
#   git clone <仓库> && cd aios
#   bash deploy/ops/offline-images.sh export            # 产出 aios-images.tar.gz
#   scp aios-images.tar.gz root@<目标机>:/opt/aios/
#
# ─── 在目标机 10.0.0.3 上 ────────────────────────────────────────────────────
#   cd /opt/aios
#   bash deploy/ops/offline-images.sh import aios-images.tar.gz
#   bash deploy/ops/offline-images.sh list              # 核对齐备
#   cd deploy && docker compose up -d server agent
#
# 备选（目标机能上国内网、只是 Hub 不通）：其实本档已不需要任何外部镜像，
# 只要那台机器自己能 `docker compose build`，就不用搬包。搬包主要解决「连源码构建都做不了」。
# ==============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(cd "$SELF_DIR/.." && pwd)"

# 需要搬运的镜像（全部由本仓库构建；名称由 compose 的 `name: aios` 决定）
BUILT_IMAGES=(aios-server aios-agent)
# 需要构建的 compose 服务名
BUILD_SERVICES=(server agent)
# ★ 可选镜像：入口 nginx（deploy/nginx/aios-entry.conf，提供 /web、/user 短路径，见手册 §0.1）。
#   它是**外部镜像**（Docker Hub），目标机往往拉不到 ⇒ 默认不搬。
#   要短路径入口就在导出时加 --with-nginx，把它一起打进包。
OPTIONAL_IMAGES=(nginx:1.27-alpine)

# ★ ASR（语音识别）模型：**不在镜像里、也不在 git 里**（约 483MB，被 .gitignore 忽略）。
#   agent 容器把宿主 <仓库>/agent/.models 以只读方式挂到 /app/.models
#   （见 docker-compose.yml 的 agent.volumes；k8s 对应 deploy/k8s/20-agent.yaml）。
#   ⇒ 离线搬到目标机时必须**单独携带**，并放到目标机仓库的 agent/ 下，
#     否则目标机 /app/.models 是空的：语音接口 503、H5 麦克风按钮置灰。
#     （这正是手机端「模型 small 未就绪（模型目录 /app/.models）」的根因。）
ASR_MODEL_NAME="${AIOS_ASR_MODEL:-small}"
ASR_MODELS_DIR="$DEPLOY_DIR/../agent/.models"
ASR_MODEL_ARCHIVE="aios-asr-models.tar.gz"

# 本机是否具备 ASR 模型：✅ 就绪 / ⚠️ 目录在但缺 model.bin / ❌ 目录不存在
asr_model_state() {
  if [ -f "$ASR_MODELS_DIR/$ASR_MODEL_NAME/model.bin" ]; then printf '✅'; return 0; fi
  if [ -d "$ASR_MODELS_DIR" ]; then printf '⚠️'; return 1; fi
  printf '❌'; return 1
}
report_asr_model() {
  local st; st="$(asr_model_state)"
  printf '  %s ASR 模型：%s（期望 %s/model.bin）\n' "$st" "$ASR_MODELS_DIR" "$ASR_MODEL_NAME"
  case "$st" in
    '✅') ;;
    '⚠️') echo "     ⚠️ 目录在但缺 $ASR_MODEL_NAME/model.bin ⇒ 目标机语音不可用" ;;
    '❌') echo "     ❌ 目录不存在 ⇒ **目标机语音识别会 503、H5 麦克风置灰**"
          echo "        请先放好模型，再用 --with-asr-model 一起打包搬过去" ;;
  esac
}

hr() { printf '\n\033[36m===== %s =====\033[0m\n' "$*"; }
die() { printf '\033[31m!! %s\033[0m\n' "$*" >&2; exit 1; }
need_docker() { command -v docker >/dev/null 2>&1 || die "本机没有 docker"; }

# ---------------------------------------------------------------- export
do_export() {
  local out="aios-images.tar.gz" with_nginx=0 with_asr=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="$2"; shift 2 ;;
      --with-nginx) with_nginx=1; shift ;;
      --with-asr-model) with_asr=1; shift ;;
      *) die "未知参数：$1（可用：--out FILE / --with-nginx / --with-asr-model）" ;;
    esac
  done
  need_docker
  cd "$DEPLOY_DIR" || die "进不去 $DEPLOY_DIR"

  hr "0) 准备 .env（只为让 compose 能渲染；占位符无所谓，构建不需要真实口令）"
  [ -f .env ] || { cp .env.production .env; echo "  已从 .env.production 生成占位 .env"; }
  docker compose config --quiet || die "compose 配置渲染失败，先修 .env 再导出"

  hr "1) 构建应用镜像（本机从源码构建，需外网拉 Maven / npm 依赖）"
  echo "  build ${BUILD_SERVICES[*]}"
  # aios-server 的构建会顺带把前端产物打进镜像（Dockerfile.server 阶段 1），
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

  # 可选：把入口 nginx 一起打进包（手册 §0.1 的 /web、/user 短路径入口要用它）
  local save_images=("${BUILT_IMAGES[@]}")
  if [ "$with_nginx" = 1 ]; then
    hr "2b) 可选：入口 nginx（--with-nginx）"
    if docker image inspect "${OPTIONAL_IMAGES[0]}" >/dev/null 2>&1; then
      printf '  ✅ %s（本机已有）\n' "${OPTIONAL_IMAGES[0]}"
    else
      printf '  ↓ 本机没有，尝试拉取 %s …\n' "${OPTIONAL_IMAGES[0]}"
      docker pull "${OPTIONAL_IMAGES[0]}" \
        || die "拉不到 ${OPTIONAL_IMAGES[0]}：导出机需能上外网（或配好加速器）；也可以不用入口 nginx。"
    fi
    save_images+=("${OPTIONAL_IMAGES[@]}")
  fi

  hr "3) 导出为一个包（docker save | gzip）"
  local out_abs="$out"
  case "$out" in /*) ;; *) out_abs="$PWD/$out" ;; esac
  echo "  含：${save_images[*]}"
  echo "  文件：$out_abs"
  docker save "${save_images[@]}" | gzip -1 > "$out_abs" || die "docker save 失败"
  ls -lh "$out_abs" | sed 's/^/  /'

  hr "3b) ASR（语音识别）模型 —— 不在镜像里，需单独搬"
  report_asr_model
  local asr_abs=""
  if [ "$with_asr" = 1 ]; then
    [ -f "$ASR_MODELS_DIR/$ASR_MODEL_NAME/model.bin" ] \
      || die "--with-asr-model 需要 $ASR_MODELS_DIR/$ASR_MODEL_NAME/model.bin"
    asr_abs="$DEPLOY_DIR/$ASR_MODEL_ARCHIVE"
    echo "  打包模型（只打 $ASR_MODEL_NAME/，含 model.bin 等 4 个文件）→ $asr_abs"
    # 只打模型本体，不连带 .models 下的 HF 缓存（那份是重复的，会把包再撑大一倍）
    tar -czf "$asr_abs" -C "$ASR_MODELS_DIR" "$ASR_MODEL_NAME" || die "打包 ASR 模型失败"
    ls -lh "$asr_abs" | sed 's/^/  /'
  fi

  hr "完成：把包拷到目标机（用隧道机 → 真实服务器那条既有通道）"
  echo "  scp $out_abs root@10.0.0.3:/opt/aios/"
  [ -z "$asr_abs" ] || echo "  scp $asr_abs root@10.0.0.3:/opt/aios/"
  echo "  目标机执行："
  echo "    cd /opt/aios && bash deploy/ops/offline-images.sh import $out"
  if [ -n "$asr_abs" ]; then
    echo "    # ★ 语音识别必需：放到**仓库的 agent/** 下（compose 默认挂 ../agent/.models）"
    echo "    mkdir -p /opt/aios/agent/.models"
    echo "    tar -xzf /opt/aios/$ASR_MODEL_ARCHIVE -C /opt/aios/agent/.models"
  else
    echo "    # ⚠️ 未打包 ASR 模型（--with-asr-model）⇒ 目标机语音仍会 503、H5 麦克风置灰"
  fi
  echo "    cd /opt/aios/deploy && docker compose up -d server agent   # 不要加 --build"
  echo "  验收：curl -s http://127.0.0.1:8080/actuator/health"
  echo "        curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8080/aios/h5/"
  echo "        curl -s http://127.0.0.1:8080/aios/api/v1/asr/status   # 语音：期望 available=true"
}

# ---------------------------------------------------------------- import
do_import() {
  local f="${1:-}"; [ -n "$f" ] || die "用法： import <aios-images.tar.gz>"
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
  hr "镜像齐备度（单端口部署：只需 aios-server + aios-agent）"
  local img
  for img in "${BUILT_IMAGES[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then printf '  ✅ %s\n' "$img"; else printf '  ❌ %s  ← 缺\n' "$img"; fi
  done
  for img in "${OPTIONAL_IMAGES[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      printf '  ✅ %s（可选：入口 /web、/user）\n' "$img"
    else
      printf '  ⚪ %s（可选，不在包里：不用短路径入口就无需它）\n' "$img"
    fi
  done
  echo "  现有全部镜像："
  docker images --format '    {{.Repository}}:{{.Tag}}  {{.Size}}' | head -40
  hr "ASR（语音识别）模型"
  report_asr_model
}

case "${1:-}" in
  export) shift; do_export "$@" ;;
  import) shift; do_import "$@" ;;
  list)   shift; do_list "$@" ;;
  *) cat <<'EOF'
用法：
  # 在能上外网的机器上导出（必需 2 张：aios-server + aios-agent，均为本地构建）
  bash deploy/ops/offline-images.sh export [--out FILE] [--with-nginx] [--with-asr-model]
  #   --with-nginx  额外把入口 nginx（nginx:1.27-alpine）打进包，
  #                 用于 /web、/user 短路径入口（手册 §0.1）；不用短路径就别加。
  #   --with-asr-model  额外把 ASR 语音模型（agent/.models/<模型名>，约 483MB）打成
  #                     aios-asr-models.tar.gz。★ 目标机要做语音识别就必须带上它 ——
  #                     模型**不在镜像里、也不在 git 里**（见脚本内 ASR_MODELS_DIR 注释）。

  # 在目标机上导入
  bash deploy/ops/offline-images.sh import <aios-images.tar.gz>
  bash deploy/ops/offline-images.sh list              # 核对镜像齐备度

说明：单端口部署（docs/33）后，管理端与用户端静态已随 aios-server 镜像一起发布，
      aios-web / ollama / minio 镜像都不再需要。
      ★ 语音识别还额外需要一个 ASR 模型（约 483MB）：它**不在镜像里、也不在 git 里**，
        离线部署请用 --with-asr-model 一起搬，并按导出结束时打印的步骤放到目标机 agent/.models 下。
      入口 nginx 是**可选**的：只是把 /web、/user 这两个短路径映射到 /aios/web/、/aios/h5/，
      不加它也能用原生地址 http://<host>:8080/aios/web/ 与 /aios/h5/。
EOF
     exit 1 ;;
esac
