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
  verify_v50_ui.py
  verify_v51_repo_urls.py
  verify_v51_repo_urls_ui.py
  # 2026-10-11 除名 5 个「指向已删文件的幽灵条目」：SMOKE_v48 / check_org_structure_render /
  # h5_v33_render / admin_v39_todo_badge / admin_v34_review_render。
  # 它们已在 2026-09-20 的 `f370fdd chore(repo): 仓库清理` 里作为「一次性诊断/渲染校验脚本」删除
  # （备份仍在项目外 aioa-cleanup-backup-20260920/scripts/），但**当时没同步改本清单**
  # ⇒ 此后每次矩阵都为这 5 条凭空产出 exit=2「can't open file」，把 28 条非零里的 5 条弄成纯噪声。
  # 且它们依赖早已移除的 tenant 9 与 :5173 管理端 shell ⇒ 即便还原也只会再加 5 条假红。
  # 已加下方 preflight：以后「清单里有、磁盘上没有」一律**跑前大声报错并 exit 2**，不再静默制造失败。
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
  # 首页四张浮动卡**不得带尾巴**（用户口径「去掉这四个气泡」，2026-09-29；
  # 此前做过四套尾巴实现，均被否决 ⇒ 本套件锁的是「卡内无任何 .tail / ::after 三角」）。
  # ⚠️ 原注释写「三角必须指向数字人」，是改口径**之前**的旧文案，已与脚本断言相反，2026-10-11 更正。
  _check_kpi_cards.py
  # 用户端「进入项目」后的布局与记忆：机器人居中且紧凑、回答区不在下半部分、
  # 项目会话被复用且历史消息不被清空（本地静态服务 + page.route 打桩，无需后端）
  _check_oa_project_layout.py
  # H5 语音输入「手势状态机」：长按/免提/取消/拒绝授权四种手势的起停，
  # 含缺陷本体「松手早于 getUserMedia 返回 ⇒ 录音永久停不下来」的负向对照。
  # 纯状态机（Node 桩，无需 HTTPS/麦克风，故本环境可复跑）；--selftest 用 HEAD 版本证明判别力。
  _check_voice_gesture.py
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

# ---- preflight：清单里的套件必须都在磁盘上 ------------------------------------
# 判据：清单里列了、scripts/ 下没有 ⇒ **跑前大声报错并 exit 2**（与「前置不满足」同一口径），
# 而不是让每个幽灵条目各产出一条 exit=2 的假红 —— 2026-09-20 的清理漏改清单就是这样：
# 5 条幽灵条目静默污染了三个月的矩阵结果，直到 2026-10-11 才被发现。
MISSING=()
for s in "${SUITES[@]}"; do
  [ -f "scripts/$s" ] || MISSING+=("$s")
done
if [ "${#MISSING[@]}" -gt 0 ]; then
  printf '[FAIL] 回归清单引用了不存在的套件（%d 个）：\n' "${#MISSING[@]}" | tee -a "$LOG"
  for m in "${MISSING[@]}"; do printf '  - scripts/%s\n' "$m" | tee -a "$LOG"; done
  printf '修法：把已删条目从 SUITES 去掉，或把脚本补回 scripts/（判据见铁律 13「引用即保留」）。\n' | tee -a "$LOG"
  exit 2
fi

for s in "${SUITES[@]}"; do
  printf '===== %s =====\n' "$s" | tee -a "$LOG"
  "$PY" "scripts/$s" >> "$LOG" 2>&1
  code=$?
  printf '   exit=%s\n' "$code" | tee -a "$LOG"
  printf '[%s] exit=%s\n' "$s" "$code"
done

echo "=== ALL SUITES DONE ===" | tee -a "$LOG"
