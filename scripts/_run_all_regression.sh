#!/usr/bin/env bash
# ============================================================
# 全量回归矩阵（收口用）：逐个跑、逐个留摘要，跑红一眼可见。
# 输出：logs/regression_all.log（完整），stdout 只给进度与 exit 码。
# ============================================================
set -u
cd "$(dirname "$0")/.."
PY="C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
LOG="logs/regression_all.log"
: > "$LOG"

SUITES=(
  verify_v39_provisioner.py
  verify_config_effect.py
  e2e_login_tenant_name.py
  e2e_v32_org_scope.py
  e2e_v33_roles.py
  e2e_v36_grant_expert_review.py
  e2e_v36_stats_clamp.py
  e2e_v39_applicant_superior.py
  e2e_v41_duty_levels.py
  e2e_v43_cc_read.py
  e2e_v43_dept_applicant.py
  e2e_v45_approver_modes.py
  e2e_v45_config_ui.py
  e2e_v45_misc_fixes.py
  e2e_p0a_worker_intake.py
  e2e_worker_permission.py
  e2e_leave_flow_notify.py
  e2e_admin_personnel_scope.py
  e2e_v50_tenant_org.py
  e2e_v51_gitee_init.py
  e2e_v52_message_center.py
  e2e_v48_gitee.py
  SMOKE_v48.py
  verify_v50_ui.py
  verify_v51_repo_urls.py
  verify_v51_repo_urls_ui.py
  check_org_structure_render.py
  h5_v33_render.py
  admin_v39_todo_badge.py
  admin_v34_review_render.py
  # 管理端布局/菜单：高度链闭合 + 侧栏滚动隔离 + 分组深链展开 + 分组 RBAC 边界
  _check_menu_scroll.py
  verify_v48_ui.py
  verify_v48_ui_extra.py
  e2e_full_system.py
)

for s in "${SUITES[@]}"; do
  printf '===== %s =====\n' "$s" | tee -a "$LOG"
  "$PY" "scripts/$s" >> "$LOG" 2>&1
  code=$?
  printf '   exit=%s\n' "$code" | tee -a "$LOG"
  printf '[%s] exit=%s\n' "$s" "$code"
done

echo "=== ALL SUITES DONE ===" | tee -a "$LOG"
