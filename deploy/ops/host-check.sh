#!/usr/bin/env bash
# ==============================================================================
# AIOA · 部署机只读体检（deploy/ops/host-check.sh）
# ------------------------------------------------------------------------------
# 用途：在**部署目标机**（本环境为 10.0.0.12）上一把跑完，输出部署前需要的全部事实：
#   ① 机器身份 / 资源        ② 代码版本            ③ 配置现状（占位符 / 口令长度）
#   ④ Docker 现状与镜像清单   ⑤ 外网出口与镜像加速器可达性   ⑥ 还缺哪些镜像
#
# 安全约定：**只读**。不写任何文件、不改 docker 配置、不 echo 任何口令明文，
#          口令只打印「长度」与「是否仍是占位符」。
#
# 用法：
#     bash deploy/ops/host-check.sh
#     bash deploy/ops/host-check.sh /opt/aioa          # 指定仓库根目录
# ==============================================================================
set -uo pipefail

REPO="${1:-$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)}"
ENVF="$REPO/deploy/.env"
PRODF="$REPO/deploy/.env.production"
COMPOSE="$REPO/deploy/docker-compose.yml"

hr() { printf '\n\033[36m%s\033[0m\n' "===== $* ====="; }
kv() { printf '  %-34s %s\n' "$1" "$2"; }

printf '\033[1mAIOA 部署机只读体检\033[0m  时间=%s  仓库=%s\n' "$(date '+%F %T')" "$REPO"

# ------------------------------------------------------------------ ① 身份/资源
hr "① 机器身份与资源"
kv "hostname" "$(hostname 2>/dev/null)"
kv "本机 IP" "$(hostname -I 2>/dev/null | tr -s ' ')"
kv "OS" "$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}")"
kv "内核" "$(uname -r)"
kv "CPU 核数" "$(nproc 2>/dev/null)"
kv "内存" "$(free -h 2>/dev/null | awk '/^Mem:/{print $2" 总 / "$7" 可用"}')"
kv "磁盘 /" "$(df -h / 2>/dev/null | awk 'NR==2{print $2" 总 / "$4" 可用 ("$5" 已用)"}')"
kv "磁盘 /var/lib/docker" "$(df -h /var/lib/docker 2>/dev/null | awk 'NR==2{print $2" 总 / "$4" 可用"}')"

# ------------------------------------------------------------------ ② 代码版本
hr "② 代码版本（判断是否已拉到最新）"
if [ -d "$REPO/.git" ]; then
  kv "HEAD" "$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)"
  echo "  最近 3 次提交："
  git -C "$REPO" log --oneline -3 2>/dev/null | sed 's/^/    /'
  kv "工作区改动" "$(git -C "$REPO" status --short 2>/dev/null | wc -l) 个文件"
  # 模板是否含本次外部实例参数
  if [ -f "$PRODF" ]; then
    kv "模板含 10.0.0.5:13049" "$(grep -c 'MYSQL_PORT=13049' "$PRODF" 2>/dev/null) 处"
    kv "模板含 10.0.0.7" "$(grep -c 'REDIS_HOST=10.0.0.7' "$PRODF" 2>/dev/null) 处"
  fi
else
  echo "  !! $REPO 不是 git 仓库（或路径不对）"
fi

# ------------------------------------------------------------------ ③ 配置现状
hr "③ 配置现状（$ENVF）"
if [ ! -f "$ENVF" ]; then
  echo "  !! .env 不存在。先执行： cp deploy/.env.production deploy/.env"
else
  echo "  -- 残留的 CHANGE_ME__ 占位（此行应【无输出】）--"
  grep -nE 'CHANGE_ME__' "$ENVF" | grep -v ':#' | sed 's/^/    /' || true
  echo "  -- 关键键值（非敏感）--"
  grep -nE '^(MYSQL_HOST|MYSQL_PORT|MYSQL_DB|MYSQL_USER|REDIS_HOST|REDIS_PORT|SPRING_REDIS_DATABASE|AIOA_MILVUS_URI|MODEL_DEFAULT|SPRING_PROFILES_ACTIVE|PUBLIC_BASE_URL)=' \
    "$ENVF" 2>/dev/null | sed 's/^/    /'
  echo "  -- 口令/密钥：只打印长度与状态（不打印明文）--"
  # 在子 shell 里 source，避免污染当前环境
  (
    set -a; . "$ENVF" 2>/dev/null; set +a
    for k in MYSQL_PASSWORD SPRING_DATASOURCE_PASSWORD SPRING_REDIS_PASSWORD \
             MINIMAX_API_KEY JWT_SECRET AIOA_JWT_SECRET MINIO_ROOT_PASSWORD; do
      v="${!k-}"; n=${#v}
      case "$v" in
        CHANGE_ME__*) tag='❌ 仍是占位符' ;;
        '')           tag='❌ 空' ;;
        *)            tag='✅ 已填' ;;
      esac
      printf '    %-28s len=%-4s %s\n' "$k" "$n" "$tag"
    done
    # 22 / 25 是占位符本身的长度，看到这两个数就是没写进去
    printf '    %s\n' "参考：占位符 CHANGE_ME__db-password=22 字符、CHANGE_ME__redis-password=25 字符"
  )
  echo "  -- compose 渲染后的实际值长度（最能说明问题）--"
  if command -v docker >/dev/null 2>&1; then
    ( cd "$REPO/deploy" && docker compose config 2>&1 ) | awk '
      /^[[:space:]]+(MYSQL_PASSWORD|SPRING_REDIS_PASSWORD|MINIMAX_API_KEY):/ {
        line=$0; sub(/^[[:space:]]+/,"",line); name=line; sub(/:.*/,"",name);
        val=line; sub(/^[^:]*:[[:space:]]*/,"",val); gsub(/^["'"'"']|["'"'"']$/,"",val);
        printf "    %-28s 渲染后 len=%d\n", name, length(val)
      }'
    echo "    （若渲染后长度 = 22 / 25，说明就是占位符本尊没被替换）"
  else
    echo "    (无 docker，跳过)"
  fi
fi

# ------------------------------------------------------------------ ④ Docker 现状
hr "④ Docker 现状"
if ! command -v docker >/dev/null 2>&1; then
  echo "  !! 未安装 docker"
else
  kv "docker" "$(docker version --format '{{.Server.Version}}' 2>&1 | head -1)"
  kv "compose" "$(docker compose version 2>&1 | head -1)"
  echo "  -- 已有镜像 --"
  docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' 2>&1 | head -60 | sed 's/^/    /'
  echo "  -- 运行中/已停止容器 --"
  docker ps -a --format '{{.Names}} | {{.Image}} | {{.Status}}' 2>&1 | head -30 | sed 's/^/    /'
  echo "  -- /etc/docker/daemon.json --"
  if [ -f /etc/docker/daemon.json ]; then cat /etc/docker/daemon.json | sed 's/^/    /'; else echo "    (不存在)"; fi
  echo "  -- 监听端口 --"
  (ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null) | head -25 | sed 's/^/    /'
fi

# ------------------------------------------------------------------ ⑤ 外网出口
hr "⑤ 外网出口探测（决定镜像怎么进来）"
probe() { # url 说明
  code=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null) || code="000"
  printf '    %-46s -> %s\n' "$2" "$code"
}
echo "  -- 解析（DNS 是否被污染：看 docker.io 解到哪个段）--"
for h in www.baidu.com registry-1.docker.io docker.m.daocloud.io mirrors.aliyun.com; do
  printf '    %-28s %s\n' "$h" "$(getent hosts "$h" 2>/dev/null | awk '{print $1}' | head -1 || echo '(解析失败)')"
done
echo "  -- HTTPS 连通性（200/301/302 = 通；000 = 不通）--"
probe https://www.baidu.com                       '国内站点 baidu.com'
probe https://mirrors.aliyun.com                  '阿里云镜像站 mirrors.aliyun.com'
probe https://mirrors.tuna.tsinghua.edu.cn        '清华镜像站'
probe https://registry-1.docker.io/v2/            'Docker Hub registry-1.docker.io'
probe https://docker.m.daocloud.io/v2/            '加速器 docker.m.daocloud.io'
probe https://dockerproxy.net/v2/                 '加速器 dockerproxy.net'
probe https://hub-mirror.c.163.com/v2/            '加速器 hub-mirror.c.163.com'
probe https://mirror.ccs.tencentyun.com/v2/       '加速器 mirror.ccs.tencentyun.com'
echo "  -- ★ 内网可达性（真实服务器虽然没外网，但可能能碰内网 registry / Gitea）--"
probe http://172.16.8.249:3000                     '内网 Gitea 172.16.8.249:3000'
probe http://172.16.8.249:3000/api/v1/version       '内网 Gitea API'
echo "  -- ★ daemon.json 里声明的 registry（若有 → 很可能能直接 pull，不用搬包！）--"
if [ -f /etc/docker/daemon.json ]; then
  # 把 registry-mirrors / insecure-registries 里的地址逐个探一遍
  grep -oE 'https?://[^",[:space:]]+' /etc/docker/daemon.json 2>/dev/null | sort -u | while read -r u; do
    probe "${u%/}/v2/" "daemon.json => $u"
  done
else
  echo "    (无 /etc/docker/daemon.json)"
fi
echo "  -- ★ docker 实际生效的 Registry Mirrors（最权威，读它的输出）--"
(docker info 2>/dev/null | sed -n '/Registry Mirrors/,/^[A-Z]/p' | head -8 | sed 's/^/    /') || echo "    (取不到)"
echo "  -- 代理相关 --"
env | grep -iE 'proxy|PROXY' | sed 's/^/    /' || echo "    (无 proxy 环境变量)"
[ -f /etc/systemd/system/docker.service.d/http-proxy.conf ] && \
  cat /etc/systemd/system/docker.service.d/http-proxy.conf | sed 's/^/    /' || echo "    (docker 无 http-proxy drop-in)"

# ------------------------------------------------------------------ ⑥ 缺哪些镜像
hr "⑥ 镜像齐备度（对照 deploy/docker-compose.yml）"
if command -v docker >/dev/null 2>&1; then
  have() { docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qxF "$1"; }
  have_re() { docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qE "$1"; }
  echo "  -- 默认档（不做则服务起不来）--"
  for img in minio/minio:latest nginx:1.27-alpine; do
    have "$img" && printf '    ✅ %s\n' "$img" || printf '    ❌ %s   ← 缺\n' "$img"
  done
  for img in aioa-server aioa-agent aioa-web; do
    have_re "(^|/)$img:latest$|(^|/)$img$" && printf '    ✅ %s\n' "$img" || printf '    ❌ %s   ← 缺（本地构建产物镜像）\n' "$img"
  done
  echo "  -- 构建三个应用镜像还需的基础镜像（只有要在这台机上 build 时才需要）--"
  for img in maven:3.9-eclipse-temurin-21 eclipse-temurin:21-jre node:22-alpine python:3.13-slim; do
    have "$img" && printf '    ✅ %s\n' "$img" || printf '    ❌ %s\n' "$img"
  done
  echo "  -- 可选档 --"
  for img in ollama/ollama:latest vllm/vllm-openai:latest prom/prometheus:latest; do
    have "$img" && printf '    ✅ %s\n' "$img" || printf '    ⚪ %s（未装，非必需）\n' "$img"
  done
  echo "  -- 是否有现成 minio 镜像可复用（宿主 milvus-minio 通常已有）--"
  docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -i '^minio/' | sed 's/^/    /' || echo "    (无)"
fi

printf '\n\033[1m体检完成（未改动任何东西）。\033[0m\n'
