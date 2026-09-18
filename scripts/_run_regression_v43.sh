#!/usr/bin/env bash
# V43 全量回归矩阵运行器（QA 独立重跑）。用法：bash scripts/_run_regression_v43.sh
set -u
cd "$(dirname "$0")/.."
PY="C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
mkdir -p logs
SUITES=(
  e2e_full_system
  e2e_v41_duty_levels
  e2e_v36_stats_clamp
  e2e_v33_roles
  e2e_v32_org_scope
  e2e_admin_personnel_scope
  e2e_leave_flow_notify
  e2e_login_tenant_name
  e2e_p0a_worker_intake
  e2e_worker_permission
  verify_v39_provisioner
  verify_config_effect
  h5_v33_render
  admin_v34_review_render
  check_org_structure_render
)
TWICE=(
  e2e_v36_grant_expert_review
  e2e_v39_applicant_superior
  admin_v39_todo_badge
)
NEW=(
  e2e_v43_dept_applicant
  e2e_v43_cc_read
)

run_one() {
  local name="$1" log="logs/reg_v43_${1}${2:-}.log"
  echo ">>> ${name}${2:-}"
  "$PY" -u "scripts/${name}.py" > "$log" 2>&1
  local rc=$?
  echo "  rc=$rc  |  $(grep -E '通过|ALL PASS|passed|结果：' "$log" | tail -1)"
  return $rc
}

for s in "${SUITES[@]}"; do run_one "$s"; done
for s in "${TWICE[@]}"; do run_one "$s" "_run1"; run_one "$s" "_run2"; done
for s in "${NEW[@]}"; do run_one "$s"; done

echo ">>> agent/tests (pytest)"
( cd agent && "$PY" -m pytest tests -q ) > logs/reg_v43_agent_pytest.log 2>&1
echo "  rc=$?  |  $(tail -2 logs/reg_v43_agent_pytest.log | tr '\n' ' ')"

echo "=== MATRIX DONE ==="
