#!/usr/bin/env bash
# ==============================================================================
# AIOS · 把「仓库之外」的落盘内容搬回仓库内（deploy/ops/move-into-repo.sh）
# ------------------------------------------------------------------------------
# 起因（2026-11-01）：部署时把企微 CLI、ASR 模型、扫码凭据目录放到了 /opt 或
# 仓库平级目录（如 /data/aioa/wecom-cli-bin），带来三个实际问题：
#   ① /opt 是系统保留目录：属主、容量配额、备份与换机迁移都不受本项目控制；
#      而且 /opt 下由 root 建目录，hub 容器以 uid 10001 运行 ⇒ 写凭据直接 PermissionError；
#   ② 换机器/重装时只搬 git 仓库，这些「仓库外的文件」一定漏搬，现象是
#      「企微扫码 404」「语音 503」，但代码和配置看起来全对；
#   ③ `git clean -xdf` / rsync --delete 会连带把它们删掉，且没有备份。
#
# 本脚本把这些路径**搬进仓库**，并同步改 deploy/.env 里对应的键。
#
# 用法（在部署机，仓库根目录下执行）：
#     bash deploy/ops/move-into-repo.sh                 # 只体检，打印计划，不动任何文件
#     bash deploy/ops/move-into-repo.sh --apply         # 真的搬（会先备份 .env）
#     REPO=/data/aioa/AIOA bash deploy/ops/move-into-repo.sh --apply
#
# 约束：
#   · 默认**只读**。不加 --apply 绝不移动、绝不改文件（与 host-check.sh 同一纪律）。
#   · 目标位置已存在且非空时**不覆盖**，只报告，让人自己决定（数据比整齐重要）。
#   · 只搬三类已知内容：企微 CLI、企微扫码凭据、ASR 模型。别的一律不碰。
# ==============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SELF_DIR/../.." && pwd)"
ENVF="$REPO/deploy/.env"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

hr()  { printf '\n\033[36m%s\033[0m\n' "===== $* ====="; }
kv()  { printf '  %-32s %s\n' "$1" "$2"; }
warn(){ printf '\033[33m  ! %s\033[0m\n' "$*"; }
plan(){ printf '  → %s\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ -f "$ENVF" ] || die "找不到 $ENVF —— 请在部署机（有 deploy/.env 的那台）上跑"

printf '\033[1mAIOS 落盘归位\033[0m  仓库=%s  模式=%s\n' "$REPO" "$([ $APPLY -eq 1 ] && echo 执行 || echo 只读体检)"

env_get() { grep -E "^[[:space:]]*$1=" "$ENVF" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*$//'; }

outside() {
  # 判断路径是否在仓库之外（都转成绝对路径再比前缀）
  local p="$1"
  [ -z "$p" ] && return 1
  case "$p" in /*) : ;; *) p="$REPO/deploy/$p" ;; esac
  local rp rp2
  rp="$(cd "$p" 2>/dev/null && pwd)" || rp="$p"
  rp2="$(cd "$p/.." 2>/dev/null && pwd)/$(basename "$p")"
  case "$rp2" in
    "$REPO"|"$REPO"/*) return 1 ;;
    *) return 0 ;;
  esac
}

# ------------------------------------------------------------------ ① 现状
hr "① 当前配置里的落盘路径"
declare -a KEYS=(AIOS_WECOM_CLI_BIN_DIR AIOS_WECOM_CLI_ROOT_DIR AIOS_ASR_MODELS_DIR)
declare -A WANT=(
  [AIOS_WECOM_CLI_BIN_DIR]="$REPO/data/wecom-cli-bin"
  [AIOS_WECOM_CLI_ROOT_DIR]="$REPO/data/wecom-cli"
  [AIOS_ASR_MODELS_DIR]="$REPO/agent/.models"
)
NEED=0
for k in "${KEYS[@]}"; do
  v="$(env_get "$k")"
  if [ -z "$v" ]; then
    kv "$k" "（未设置 ⇒ 用 compose 默认，默认已在仓库内）"
    continue
  fi
  if outside "$v"; then
    kv "$k" "$v"
    warn "在仓库之外 ⇒ 应搬到 ${WANT[$k]}"
    NEED=$((NEED+1))
  else
    kv "$k" "$v（已在仓库内）"
  fi
done

hr "② 仓库外是否还有 /opt 残留"
HITS="$(ls -d /opt/aios /opt/wecom-cli 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  printf '%s\n' "$HITS" | sed 's/^/  · /'
  warn "发现 /opt 下的历史目录；确认无用后手工删除（本脚本不会动 /opt）"
else
  echo "  （无）"
fi

[ "$NEED" -eq 0 ] && { hr "结论"; echo "  全部落盘内容已在仓库内，无需迁移。"; exit 0; }

# ------------------------------------------------------------------ ③ 计划
hr "③ 迁移计划"
for k in "${KEYS[@]}"; do
  v="$(env_get "$k")"; [ -z "$v" ] && continue
  outside "$v" || continue
  dst="${WANT[$k]}"
  if [ -e "$dst" ] && [ -n "$(ls -A "$dst" 2>/dev/null)" ]; then
    warn "$dst 已存在且非空 ⇒ 跳过 $k（请人工比对后决定保留哪份）"
    continue
  fi
  plan "mv $v → $dst"
  plan "改 .env: $k=$dst"
done
[ $APPLY -eq 0 ] && { echo; echo "  以上为计划。确认后加 --apply 执行。"; exit 0; }

# ------------------------------------------------------------------ ④ 执行
hr "④ 执行"
cp -a "$ENVF" "$ENVF.bak-move-$(date +%Y%m%d-%H%M%S)" || die "备份 .env 失败，中止"
echo "  已备份 .env"

for k in "${KEYS[@]}"; do
  v="$(env_get "$k")"; [ -z "$v" ] && continue
  outside "$v" || continue
  dst="${WANT[$k]}"
  if [ -e "$dst" ] && [ -n "$(ls -A "$dst" 2>/dev/null)" ]; then
    warn "$dst 非空，跳过 $k"
    continue
  fi
  mkdir -p "$(dirname "$dst")" || { warn "建目录失败：$dst"; continue; }
  if [ -d "$v" ]; then
    cp -a "$v/." "$dst/" || { warn "拷贝失败：$v → $dst"; continue; }
  elif [ -f "$v" ]; then
    mkdir -p "$dst"; cp -a "$v" "$dst/" || { warn "拷贝失败：$v"; continue; }
  else
    warn "源不存在，跳过：$v"
    continue
  fi
  chmod +x "$dst"/wecom-cli 2>/dev/null || true
  # hub 以 uid 10001 运行：凭据目录必须可写，否则扫码成功也写不进凭据
  if [ "$k" = "AIOS_WECOM_CLI_ROOT_DIR" ]; then
    chown -R 10001:10001 "$dst" 2>/dev/null || warn "chown 失败（非 root？）—— 请手工 chown -R 10001:10001 $dst"
  fi
  # 按行重写，不做模式替换（口令里含 & 会被 sed 改坏，见 set-secrets.py 的教训）
  tmp="$(mktemp)"
  awk -v k="$k" -v val="$dst" '
    BEGIN { done = 0 }
    $0 ~ "^[[:space:]]*"k"=" { print k"="val; done = 1; next }
    { print }
    END { if (!done) print k"="val }
  ' "$ENVF" > "$tmp" && mv "$tmp" "$ENVF"
  echo "  ✓ $k → $dst"
  plan "源目录仍在：$v（确认无误后自行删除，本脚本不删数据）"
done

hr "⑤ 下一步"
cat <<EOF
  cd "$REPO/deploy"
  docker compose config | grep -E 'wecom-cli|\.models'   # 核对容器真正会收到的值
  docker compose up -d --force-recreate mcp-hub agent    # up -d 才重读 .env
EOF
