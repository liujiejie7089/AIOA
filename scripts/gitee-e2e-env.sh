#!/usr/bin/env bash
# ============================================================
# Gitee 端到端回归接线（opt-in）
# ------------------------------------------------------------
# 把 Gitee 的**服务端接口**与**用户浏览器授权域**一并指向本地桩 :8090，
# 使自动化回归无需真实 Gitee 也能跑通「绑定 → 建仓 → Webhook → 成员同步」。
#
# 用法：
#   source scripts/gitee-e2e-env.sh && <启动后端>
#   或   AIOA_GITEE_E2E=1 bash start-all.sh
#
# ⚠ 重要：本文件会把**授权跳转**也指向桩，因此用户不会到达真实 Gitee，
#   而是被桩直接签发一个假身份（如 gitee_dev_152）。为避免误判，后端会在
#   绑定结果页与授权响应里显式标注「本次授权未经过真实 Gitee」。
#   生产/演示要真实授权时**不要** source 本文件（保持默认 https://gitee.com）。
# ============================================================
export AIOA_GITEE_BASE_URL=http://127.0.0.1:8090/api/v5
export AIOA_GITEE_WEB_URL=http://127.0.0.1:8090
# 授权跳转独立于 web-base-url：只有端到端回归才把它指向桩
export AIOA_GITEE_OAUTH_AUTHORIZE_URL=http://127.0.0.1:8090
export AIOA_GITEE_CLIENT_ID=aioa-e2e-client
export AIOA_GITEE_CLIENT_SECRET=aioa-e2e-secret
export AIOA_GITEE_REDIRECT_URI=http://127.0.0.1:8080/api/v1/gitee/bind/callback
export AIOA_GITEE_ORG=aioa-demo-org
export AIOA_GITEE_WEBHOOK_BASE_URL=http://127.0.0.1:8080
export AIOA_GITEE_BIND_RETURN_URL=http://127.0.0.1:5173/gitee/projects
export AIOA_GITEE_SYNC_ENABLED=false
