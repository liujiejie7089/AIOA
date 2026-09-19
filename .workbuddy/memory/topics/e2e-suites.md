# E2E 套件矩阵与断言纪律

> 摘自 `MEMORY.md §5`（2026-09-19 拆分）。**收口验收 / 写新套件前先读本文件**。
> 套件脚本在 `scripts/` 且已 gitignore，不入库。

## 5. E2E 套件矩阵（`scripts/e2e_*.py`，已 gitignore 不入库）
- **收口必跑**：`e2e_full_system.py` **155/155**（13 段跨层串联；`--no-browser` 跳渲染段）。跑前先 `ls scripts/ | grep -E "^e2e_"`（套件会因 gitignore 凭空消失，别照抄本表）。只改前端也必须跑 `vue-tsc --noEmit`。
- **按钮级全量 UI（2026-09-19 新增）**：`e2e_v61_h5_all_buttons.py`（H5 **27/27**，运行时枚举 `onclick`，冒烟点 93 键）· `e2e_v61_shell_all_buttons.py`（管理端 **145/145，0 JS 异常**：admin 49 · znkj_admin 45 · znkjyf_admin 19 · znsfb_ldr 17 · znsfb_m01 15）· wrapper `run_v61_shell_buttons.sh`。
  **铁律：管理端按钮级测试必须逐角色分进程**（单浏览器连跑 20+ 路由 + 上百点击 ⇒ Edge renderer 资源耗尽挂起）。稳定三板斧 = `goto(wait_until="commit")` + 越权断言用 `page.url`（免 evaluate 挂起）+ 按钮枚举单次 `evaluate`；点击 `locator.click(timeout=2000, no_wait_after=True, force=True)` + 每次 `Escape` 关弹层；只跳破坏性/真实网络/空文本（树箭头）按钮，跳过清单**过宽会「点 0 个」失去意义**。
- **基线（2026-09-17~19）**：`e2e_v48_gitee`116 · `e2e_v51_gitee_init`50 · `e2e_gitea_live`81 · `e2e_v50_tenant_org`54 · `e2e_v52_message_center`47 · `e2e_leave_flow_notify`19 · `e2e_v45_approver_modes`44 · `e2e_v45_misc_fixes`27 · `e2e_v45_config_ui`25 · `e2e_v43_dept_applicant`41 · `e2e_v43_cc_read`41 · `e2e_v41_duty_levels`48 · `e2e_v39_applicant_superior`49 · `e2e_v36_grant_expert_review`64 · `e2e_admin_personnel_scope`57 · `e2e_v32_org_scope`51 · `e2e_v36_stats_clamp`66 · `e2e_v33_roles`41 · `verify_v51_repo_urls`23 · `verify_v51_repo_urls_ui`18 · `verify_v50_ui`28 · `h5_v33_render`28 · `admin_v39_todo_badge`17 · `_check_gitea_ui_provider`17 · `_check_gitea_cfg_failure_ui`16 · `agent/tests` 42 passed · `aioa-gitee` 单测 165 · **`e2e_v62_milvus_kb` 25（mysql 档；milvus 档未跑）**（以上均为 `N/N` 全绿）。
- **本地哨兵**（非 e2e 命名）：`_syntax_h5.js` · `_refaudit_h5.js`（H5 内联 `onX="fn()"` 悬空引用——单文件 H5 无打包器无类型检查）· `_check_menu_scroll.py`（27 项）。改 H5/管理端布局后顺手跑。
- `h5_v33_render` 假红：其「AI 解读」段依赖 agent，若用 `agent/.venv` + `127.0.0.1` 起 agent，请求体被丢弃 → 422 假红；**必须按 `start-all.sh` 口径**（`envs/default` python + `--host 0.0.0.0`）重启 agent 后再判。

### 断言纪律（写新套件必读）
- **禁固定页长/绝对条数**：用 `len(items)==min(total,size)`。判据：数据涨 10 倍、清库后该断言还成立吗？
- **审批用例先确认「申请人所在部门」的负责人**：首节点指派 = 该部门 `org_department.leader_user_id`。`fagai_li` 在 **dept 11**，负责人是 `fagai_admin`(user 4)，**不是** dept10 的 `fagai_liu`(user 7)；用错人 → `decided=0`。
- **配额类套件必须自治**：`fagai_li` 年假仅 10 天；段首顶到「已用+10」；撤销链路用**不占额度**的事假；不传 `days` 且落周日返回「申请天数为 0」。
- **分清「口令/选择器改动」与「真回归」**：1001=口令错，1004=租户名不匹配；**按 `password_hash` 反查真实口令**再断言。
- **改权限/可见性/生效态/登录口径后必须全局搜既有套件旧口径断言并连跑两次**。历史遗留行 ≠ 代码 bug；可回填就**加 Flyway 回填迁移修数据、断言原样保留**。**绝不为转绿而放宽断言。**
- **动真实租户级配置的验收，`finally` 必须按「原字节」还原**（先登记 `(id, 原 steps_json)`）。
- **管理端配置页验收要「渲染 + 往返」**：用 **label 文本**匹配渲染出的控件，做「打开弹窗不改动直接保存 → 断言与保存前完全一致」，再种一个**页面没建模的键**确认它活下来。范本 `scripts/e2e_v45_config_ui.py`。

