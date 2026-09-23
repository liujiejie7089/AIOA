# E2E 套件矩阵与断言纪律

> 摘自 `MEMORY.md §5`（2026-09-19 拆分）。**收口验收 / 写新套件前先读本文件**。
> 套件脚本在 `scripts/` 且已 gitignore，不入库。

## 5. E2E 套件矩阵（`scripts/e2e_*.py`，已 gitignore 不入库）
- **收口必跑**：`e2e_full_system.py` **155/155**（13 段跨层串联；`--no-browser` 跳渲染段）。跑前先 `ls scripts/ | grep -E "^e2e_"`（套件会因 gitignore 凭空消失，别照抄本表）。只改前端也必须跑 `vue-tsc --noEmit`。
- **按钮级全量 UI（2026-09-19 新增）**：`e2e_v61_h5_all_buttons.py`（H5 **27/27**，运行时枚举 `onclick`，冒烟点 93 键）· `e2e_v61_shell_all_buttons.py`（管理端 **145/145，0 JS 异常**：admin 49 · znkj_admin 45 · znkjyf_admin 19 · znsfb_ldr 17 · znsfb_m01 15）· wrapper `run_v61_shell_buttons.sh`。
  **铁律：管理端按钮级测试必须逐角色分进程**（单浏览器连跑 20+ 路由 + 上百点击 ⇒ Edge renderer 资源耗尽挂起）。稳定三板斧 = `goto(wait_until="commit")` + 越权断言用 `page.url`（免 evaluate 挂起）+ 按钮枚举单次 `evaluate`；点击 `locator.click(timeout=2000, no_wait_after=True, force=True)` + 每次 `Escape` 关弹层；只跳破坏性/真实网络/空文本（树箭头）按钮，跳过清单**过宽会「点 0 个」失去意义**。
- **基线（2026-09-17~19）**：`e2e_v48_gitee`116 · `e2e_v51_gitee_init`50 · `e2e_gitea_live`81 · `e2e_v50_tenant_org`54 · `e2e_v52_message_center`47 · `e2e_leave_flow_notify`19 · `e2e_v45_approver_modes`44 · `e2e_v45_misc_fixes`27 · `e2e_v45_config_ui`25 · `e2e_v43_dept_applicant`41 · `e2e_v43_cc_read`41 · `e2e_v41_duty_levels`48 · `e2e_v39_applicant_superior`49 · `e2e_v36_grant_expert_review`64 · `e2e_admin_personnel_scope`57 · `e2e_v32_org_scope`51 · `e2e_v36_stats_clamp`66 · `e2e_v33_roles`41 · `verify_v51_repo_urls`23 · `verify_v51_repo_urls_ui`18 · `verify_v50_ui`28 · `h5_v33_render`28 · `admin_v39_todo_badge`17 · `_check_gitea_ui_provider`17 · `_check_gitea_cfg_failure_ui`16 · `agent/tests` 42 passed · `aioa-gitee` 单测 165 · **`e2e_v62_milvus_kb` 25（mysql 档；milvus 档未跑）**（以上均为 `N/N` 全绿）。
- **本地哨兵**（非 e2e 命名）：`_syntax_h5.js` · `_refaudit_h5.js`（H5 内联 `onX="fn()"` 悬空引用——单文件 H5 无打包器无类型检查）· `_check_menu_scroll.py`（27 项）。改 H5/管理端布局后顺手跑。
- `h5_v33_render` **（该套件现已不在 `scripts/`）**：本条曾把它的红写成「假红」，2026-09-22 查明**是误判**，保留原文以记住教训 ——
  原文：「其『AI 解读』段依赖 agent，若用 `agent/.venv` + `127.0.0.1` 起 agent，请求体被丢弃 → 422 假红；**必须按 `start-all.sh` 口径**（`envs/default` python + `--host 0.0.0.0`）重启 agent 后再判。」
  **真相**：那不是假红，是**真缺陷**（后端默认 HTTP/2 客户端发 h2c 升级 ⇒ uvicorn 丢请求体 ⇒ 422），见 `pitfalls.md` #55–#57。
  `envs/default` 当时「能过」只是因为它装着裸 uvicorn（落到 h11，h11 恰好保住 body），而 `agent/.venv` 与**生产镜像**都是 httptools ⇒ 会显形。
  **结论**：agent 现在由 `start-all.sh` 显式 `--http httptools` 起（与生产一致）；凡「换个启动姿势就不红了」的结论，必须先把两种姿势的行为差异查清再下判。
- **后端→agent 传输三件套（2026-09-22 新增）**：`_check_agent_httpclient.py`（静态守卫，正向 8/8 + 负向自检 4/4）· `e2e_worker_schedule_exec.py`（**18/18**：反掩盖前置 + 手动执行 + 到点执行 + 意图识别走 agent，**约 80s，含等整分**）· `_probe_agent_h2c.py`（判别 agent 在 httptools 还是 h11）。
  **前置依赖**：`e2e_worker_schedule_exec` 会先跑 `_probe_agent_h2c`，若 agent 跑在 h11（返回 200）则该用例**故意报红**并说明「本套件通过说明不了问题」——这是刻意的，别为了让红变绿去改它。
- **知识库共享可见性三件套（2026-09-21 新增）**：`e2e_kb_share_visible.py`（**31/31**，两次连跑均绿；A 权限口径 / B 共享可见性+跨租户零泄露+PERSONAL 不外泄 / B6 列表与检索同源 / C 看与改同源含 3 条反断言 / D 管理端真浏览器 / E 用户端 H5 渲染且断言 `is_visible` / **F 静默截断 5 项**）· `_check_kb_permission.py`（静态守卫，正向 6/6 + 负向自检 4/4）· 探针 `_probe_kb_accounts.py`（纯 HTTP 扫全部账号的列表/租户/机构三口径）、`_probe_kb_console.py`、`_probe_kb_share.py`。
  套件用 `finally` 保证清理；造的资料带 `KBVIS<run>` 前缀。**写「看不到数据」类缺陷先跑 `_probe_kb_accounts.py`**：只要有一个账号拿到数据，「数据/迁移」方向即为错。
  **探针注意**：`#kbList` 在 H5 的「我的」页（`#page-me`）里，先 `go('page-me')` 再操作，否则元素「读得到文本但不可见」，`click()` 会 30s 超时。

### 断言纪律（写新套件必读）
- **禁固定页长/绝对条数**：用 `len(items)==min(total,size)`。判据：数据涨 10 倍、清库后该断言还成立吗？
- **审批用例先确认「申请人所在部门」的负责人**：首节点指派 = 该部门 `org_department.leader_user_id`。`fagai_li` 在 **dept 11**，负责人是 `fagai_admin`(user 4)，**不是** dept10 的 `fagai_liu`(user 7)；用错人 → `decided=0`。
- **配额类套件必须自治**：`fagai_li` 年假仅 10 天；段首顶到「已用+10」；撤销链路用**不占额度**的事假；不传 `days` 且落周日返回「申请天数为 0」。
- **分清「口令/选择器改动」与「真回归」**：1001=口令错，1004=租户名不匹配；**按 `password_hash` 反查真实口令**再断言。
- **改权限/可见性/生效态/登录口径后必须全局搜既有套件旧口径断言并连跑两次**。历史遗留行 ≠ 代码 bug；可回填就**加 Flyway 回填迁移修数据、断言原样保留**。**绝不为转绿而放宽断言。**
- **动真实租户级配置的验收，`finally` 必须按「原字节」还原**（先登记 `(id, 原 steps_json)`）。
- **管理端配置页验收要「渲染 + 往返」**：用 **label 文本**匹配渲染出的控件，做「打开弹窗不改动直接保存 → 断言与保存前完全一致」，再种一个**页面没建模的键**确认它活下来。范本 `scripts/e2e_v45_config_ui.py`。

## 5.3 ⚠️ `_run_all_regression.sh` 在本机**不能当零回归判据**（2026-09-22 实测）

**背景**：2026-09-20「批次 4」有意把本地库收敛到与生产首启一致（Flyway 只播 tenant 0/2/3），
tenant 9 全清（5866 行 / 44 表）。当时记录了代价，本轮把它**量化为四桶**（34 个 runner 套件：通过 3 / 失败 31）：

| 桶 | 数 | 判据（怎么一眼认出来） |
|---|---|---|
| A 演示数据集换代 | 21 | 首错是 `登录失败 <t9/jyj 账号>：code=1001`。**查库定案**：`SELECT COUNT(*) FROM sys_user` = 16，且这些名字**连软删行都没有** |
| B Gitee 桩未启动 | 4 | `httpx.ConnectError [WinError 10061]`，目标 `:8090` |
| C runner 引用的套件文件已不存在 | 5 | `python: can't open file` → exit=2 |
| D 套件期望 vs 现行实现 | 1 | `_check_menu_scroll.py` 断言分组名「安全与治理」，**HEAD 版就已改名「权限与安全」**（`git show HEAD:...MainLayout.vue` 为证） |

**在这个环境里真正有效的回归面 = 面向现库的套件**（跑 `_run_all_regression.sh` **之后**补跑）：
`e2e_v59_bridge_tool_invoke` · `e2e_v59b_tool_sdk` · `e2e_v60_workflow_ext` · `e2e_v61_h5_all_buttons` 27/27 ·
`e2e_v62_default_ai` **79/79** · `e2e_v62_admin_default_ai_ui` 9/9 · `e2e_agent_orchestrator` · `verify_config_effect` 11/11 ·
`e2e_v63_single_port` 51/51 · `e2e_v64_expert_template` 25/25。
`e2e_sdk_token_origin` 红在 `E0-1 子应用 iframe`：根因是 **`app_registry` 表 0 行**（demo 子应用未注册）= A 桶。

**`e2e_v62` 的 79 项构成（2026-09-22 扩容，由 64 项而来）**：A 静态 26（新增 A6b/A6c/A9/A10/A2b，把「满屏是基样式、媒体查询只留宽屏反例」「手机壳色值 `#14181f` 与死尺寸已清零」「回答层级渲染对所有会话生效」「copyText/guide-copy 无残留」都锁住）；B 纯函数 15（**推荐精准匹配语义全在这里**：相关⇒只出命中、无关⇒只留兜底、多命中按分排序、cap 不挤兜底）；C 接口 14；D 浏览器 24。
**分层原则**：**语义（该不该推荐某位专家）放 B 用真实源码在 node 里跑；接线（DOM 是否渲染、按钮点了会不会重发）放 D**。D 组验「精准匹配」用的手法是**直接调 `guidanceBlock()` 造块**（真实源码 + 真实目录 + 造好的问句），而不是真发两次模型 —— 后者既慢又不可控。
**纪律**：向用户报回归时，**先查库/查日志把每条失败归到桶**，再决定说不说「零回归」。
把「不可运行」写成「通过」、或把「需要重建演示数据」写成「已零回归」，都是报告失真。
`seed_multi_tenant.py` 能重建租户但**给不出旧的硬编码 id**（套件里写死 3142–3145）⇒ 恢复旧基线 = 改套件，
属明确不做。

## 5.4 写「校验器 + 负向自检」时的坑：替换机制必须够得到被测代码

`scripts/_check_single_port.py` 的负向自检靠 `_OVERRIDES = {rel: 替换文本}` 让 `read()/exists()/hit()` 返回假内容。
**若某段逻辑直接 `p.read_text()` 读盘，就绕过了 `_OVERRIDES` ⇒ 那段永远无法被负向自检证明「被写坏会报红」。**
真实踩到：c4（叠加文件已清理）的文本扫描就是直接读盘，加了一条针对它的突变却**不报红**，
看上去像「白名单把检查吞了」，实为机制够不到。修法：扫描也走 `read(rel_key)` + `exists(rel_key)`。
**判据：每条检查项至少要有一条突变能让它报红**；加断言时必须同步加突变，否则等于没有防线。

**另**：校验器的白名单（如「允许提及已删文件名」）必须是**显式集合 + 每条写明理由**，
不能写成前缀/目录级通配 —— 那是把洞开成门。

