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
  # 机构参数（需求二 / docs/44 §2）三处同源：常量 / 路由 allowRoles / 后端 PermissionCatalog
  # 必须同值，且「系统参数」不得随机构一起下放（纯静态，无需后端）
  _check_org_config_consistency.py
  # 机构作用域接口级验收（B1 可读 / B2 ★另一机构不受影响 / B3 租户级接口 403）
  # 需要后端已含 V80/V81 与新控制器；不含时以 exit=2 明确报「前置不满足」，不伪装 PASS。
  # 脚本自带自净（finally 里删除探针覆盖值），跑完 sys_org_config 不留探针行。
  _verify_org_config_scope.py
  verify_v48_ui.py
  verify_v48_ui_extra.py
  e2e_full_system.py
  # 知识库「点开查看 / 删除」：接口口径 + 新版(OA)/经典 双形态 + 视觉覆盖层
  _e2e_kb_doc.py
  _e2e_oa.py
  # 对话意图 → 真窗口 端到端链路（用户真打一句 → 分类器 agent:8000 → 真弹窗 → 真拉 /docs/tree）
  # 需本地静态服务 :5181 + 后端 :8080 + agent :8000 在线；无可见项目 / 分类器离线则 SKIP+非0。
  _verify_oa_intent_e2e.py
  _e2e_oa_approve.py
  _check_oa_visual.py
  # 首页四张浮动卡的三角必须指向数字人（几何 + 波峰像素重叠）
  _check_kpi_cards.py
  # 用户端「进入项目」后的布局与记忆：机器人居中且紧凑、回答区不在下半部分、
  # 项目会话被复用且历史消息不被清空（本地静态服务 + page.route 打桩，无需后端）
  _check_oa_project_layout.py
  # 部署面：application.yml 引用的环境变量必须被 compose 透传（否则在 .env 里改它是空转）
  _check_compose_env_wiring.py
  # 可执行产物：aioa-boot 的 jar 必须是胖 jar（含 BOOT-INF/lib）。
  # 2026-10-11 实际踩到：构建用了 repackage.skip 后留下 170KB 瘦 jar，
  # 正在运行的实例随即 NoClassDefFoundError（/runs、/admin/org-configs 一律 500），
  # 而 mvn test 全绿（测试读 target/classes 不读 jar）⇒ 只有查产物才看得见。
  # 纯静态、无需后端；产物不存在时 SKIP 且非 0，不伪装 PASS。
  _check_boot_jar_fat.py
  # 仓库联动平台参数动态配置：适配器必须走覆盖层 + 三处字段口径一致 + Secret 不明文回传
  # （默认只跑静态；加 --api 才验接口往返，需要后端含本次改动）
  _check_gitee_platform_config.py
)

for s in "${SUITES[@]}"; do
  printf '===== %s =====\n' "$s" | tee -a "$LOG"
  "$PY" "scripts/$s" >> "$LOG" 2>&1
  code=$?
  printf '   exit=%s\n' "$code" | tee -a "$LOG"
  printf '[%s] exit=%s\n' "$s" "$code"
done

echo "=== ALL SUITES DONE ===" | tee -a "$LOG"
