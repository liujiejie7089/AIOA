#!/usr/bin/env bash
# =============================================================================
# 止血：修复「点『绑定 Gitee 账号』→ {"error":"Application does not exist"}」
# -----------------------------------------------------------------------------
# 现象   授权 URL = https://gitee.com/oauth/authorize?client_id=&redirect_uri=…
#        （client_id 为空 ⇒ Gitee 固定回 "Application does not exist"）
# 根因   线上部署物（5e38135）的 GiteeClient.authorizeUrl() **只读环境变量**，
#        管理端「仓库配置」里配的值对它完全无效（走端口是 2d65f39 才修的）。
#        而容器 env 当前 CLIENT_ID 为空、REDIRECT_URI 还停在 http://10.0.0.3/…
# 做法   把正确值写进 deploy/.env → 重建 server 容器（**不重新构建镜像**，
#        所以离线环境也跑得动）。
# 注意   这是**止血**。根治要把 2d65f39（authorizeUrl 改走 RepoProviderSettings
#        端口）重新构建镜像并部署，之后管理端配置才会真正生效。
#        本脚本写入的值与管理端（已修正）**一致**，将来上线后不会互相打架。
#
# 在服务器上、仓库根目录执行（默认 dry-run，只打印将要做的改动）：
#   bash deploy/ops/fix-gitee-binding.sh
#   bash deploy/ops/fix-gitee-binding.sh --apply \
#        --client-id eb1dee15… --client-secret 2f9f51b3…
#   # 也可交互输入（secret 不回显）：
#   bash deploy/ops/fix-gitee-binding.sh --apply
#
# 退出码：0 = 通过（或 dry-run 正常结束）；1 = 失败；2 = 参数错误。
# =============================================================================
set -euo pipefail

APPLY=0
PUBLIC_BASE="https://mall.egoaicloud.com/aioa"
ENV_FILE="${ENV_FILE:-deploy/.env}"
CLIENT_ID="${AIOA_GITEE_CLIENT_ID:-}"
CLIENT_SECRET="${AIOA_GITEE_CLIENT_SECRET:-}"
RESTART=1
SKIP_VERIFY=0
ADMIN_USER="${AIOA_ADMIN_USER:-admin}"
ADMIN_PASS="${AIOA_ADMIN_PASSWORD:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)         APPLY=1 ;;
    --dry-run)       APPLY=0 ;;
    --client-id)     CLIENT_ID="${2:?}"; shift ;;
    --client-secret) CLIENT_SECRET="${2:?}"; shift ;;
    --public-base)   PUBLIC_BASE="${2:?}"; shift ;;
    --env-file)      ENV_FILE="${2:?}"; shift ;;
    --admin-user)    ADMIN_USER="${2:?}"; shift ;;
    --admin-password) ADMIN_PASS="${2:?}"; shift ;;
    --no-restart)    RESTART=0 ;;
    --skip-verify)   SKIP_VERIFY=1 ;;
    -h|--help)       sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（用 --help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

REDIRECT_URI="${PUBLIC_BASE}/api/v1/gitee/bind/callback"
BIND_RETURN_URL="${PUBLIC_BASE}/web/"

echo "== 目标文件：$ENV_FILE"
[ -f "$ENV_FILE" ] || { echo "[ERROR] 找不到 $ENV_FILE（可用 --env-file 指定）" >&2; exit 1; }

get_env() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -E 's/^["'"'"']|["'"'"']$//g'; }

# 取值优先级：命令行 > 环境变量 > 现有 .env 里的非空值 > 交互输入
[ -n "$CLIENT_ID" ]     || CLIENT_ID="$(get_env AIOA_GITEE_CLIENT_ID || true)"
[ -n "$CLIENT_SECRET" ] || CLIENT_SECRET="$(get_env AIOA_GITEE_CLIENT_SECRET || true)"
if [ -z "$CLIENT_ID" ]; then read -rp  "Gitee Client ID: " CLIENT_ID; fi
if [ -z "$CLIENT_SECRET" ]; then read -rsp "Gitee Client Secret（不回显）: " CLIENT_SECRET; echo; fi
if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
  echo "[ERROR] client-id / client-secret 不能为空（Gitee「设置 → 第三方应用」详情页）" >&2
  exit 1
fi

echo
echo "== 将要修改（含现值对比；Secret 一律不回显）=="
for k in AIOA_GITEE_ENABLED AIOA_GITEE_OAUTH_AUTHORIZE_URL AIOA_GITEE_CLIENT_ID \
         AIOA_GITEE_CLIENT_SECRET AIOA_GITEE_REDIRECT_URI AIOA_GITEE_BIND_RETURN_URL; do
  cur="$(get_env "$k" || true)"
  case "$k" in
    AIOA_GITEE_CLIENT_SECRET)
      # 绝不回显 Secret 的值（终端会被录屏/进日志）
      [ -n "$cur" ] && cur="(已配置)" || cur="（空）"
      new="(将写入)" ;;
    AIOA_GITEE_CLIENT_ID)       new="$CLIENT_ID" ;;
    AIOA_GITEE_REDIRECT_URI)    new="$REDIRECT_URI" ;;
    AIOA_GITEE_BIND_RETURN_URL) new="$BIND_RETURN_URL" ;;
    AIOA_GITEE_ENABLED)         new="true" ;;
    *)                          new="https://gitee.com" ;;
  esac
  printf '   %-30s %s  ->  %s\n' "$k" "${cur:-（空）}" "$new"
done

if [ "$APPLY" != 1 ]; then
  echo
  echo "[dry-run] 未做任何改动。确认无误后加 --apply 执行。"
  exit 0
fi

# ---- 备份 ----
BAK="${ENV_FILE}.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$ENV_FILE" "$BAK"
echo
echo "== 已备份：$BAK"

# ---- 写入（用 python3，避免 sed 在引号/特殊字符上出错）----
python3 - "$ENV_FILE" "$CLIENT_ID" "$CLIENT_SECRET" "$REDIRECT_URI" "$BIND_RETURN_URL" <<'PY'
import re, sys, pathlib
path, cid, csec, ruri, bret = sys.argv[1:6]
updates = {
    "AIOA_GITEE_ENABLED": "true",
    "AIOA_GITEE_OAUTH_AUTHORIZE_URL": "https://gitee.com",
    "AIOA_GITEE_CLIENT_ID": cid,
    "AIOA_GITEE_CLIENT_SECRET": csec,
    "AIOA_GITEE_REDIRECT_URI": ruri,
    "AIOA_GITEE_BIND_RETURN_URL": bret,
}
p = pathlib.Path(path)
lines = p.read_text(encoding="utf-8").splitlines()
seen, out = set(), []
for ln in lines:
    m = re.match(r"^([A-Za-z0-9_]+)=", ln)
    if m and m.group(1) in updates:
        k = m.group(1); seen.add(k)
        out.append(f"{k}={updates[k]}")
    else:
        out.append(ln)
for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("已写入", len(updates), "项")
PY

# ---- 重建 server 容器（不 --build；离线也跑得动）----
if [ "$RESTART" = 1 ]; then
  echo "== 重建 server 容器"
  ( cd deploy && docker compose up -d server )
  echo "== 等待 /actuator/health"
  for _ in $(seq 1 40); do
    code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/aioa/actuator/health || true)"
    [ "$code" != "000" ] && { echo "   health HTTP $code"; break; }
    sleep 3
  done
fi

# ---- 验收一：容器**真正收到**的环境变量（不是 .env 里写了什么）----
echo
echo "== 容器实收 env"
got="$( (cd deploy && docker compose exec -T server printenv AIOA_GITEE_CLIENT_ID) 2>/dev/null | tr -d '\r' || true)"
if [ "$got" = "$CLIENT_ID" ]; then
  echo "   [PASS] AIOA_GITEE_CLIENT_ID 已进入容器"
else
  echo "   [FAIL] 容器拿到的 CLIENT_ID='${got:-<空>}'（期望 $CLIENT_ID）"
  echo "          排查：cd deploy && docker compose config | grep -A1 AIOA_GITEE_CLIENT_ID"
  exit 1
fi

if [ "$SKIP_VERIFY" = 1 ]; then
  echo; echo "[OK] 已写入并重建（--skip-verify：未做接口验收）"; exit 0
fi

# ---- 验收二：授权 URL 里 client_id 必须**真的带上**（判据回到事实源头）----
echo
[ -n "$ADMIN_PASS" ] || { read -rsp "平台管理员口令（用于验收，不回显）: " ADMIN_PASS; echo; }
BODY="$(python3 -c 'import json,sys;print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$ADMIN_USER" "$ADMIN_PASS")"
TOK="$(curl -s -X POST http://127.0.0.1:8080/api/v1/auth/login -H 'Content-Type: application/json' -d "$BODY" \
       | python3 -c 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("accessToken") or "")')"
if [ -z "$TOK" ]; then echo "[FAIL] 登录失败，无法验收（credentials 不对？）"; exit 1; fi
URL="$(curl -s -X POST http://127.0.0.1:8080/api/v1/gitee/bind/authorize -H "Authorization: Bearer $TOK" \
       | python3 -c 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("url") or "")')"
echo "   授权 URL: $URL"
case "$URL" in
  *"client_id=$CLIENT_ID"*)
     echo "   [PASS] client_id 已带上 ⇒ 可去应用内重新点『绑定 Gitee 账号』" ;;
  *)
     echo "   [FAIL] client_id 仍为空/不匹配 —— 回到上一步看容器实收 env" >&2; exit 1 ;;
esac
echo
echo "[OK] 完成。回滚：cp '$BAK' '$ENV_FILE' && (cd deploy && docker compose up -d server)"
