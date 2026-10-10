# AIOA 长期记忆（索引 + 铁律）

> 本文件只放「每次都要遵守」的；明细按主题在 `topics/`，故事在同目录 `YYYY-MM-DD.md`，
> 压缩前全文快照 `archive/MEMORY-full-2026-09-19.md`（只读）。

| 何时读 | 文件 |
|---|---|
| 项目结构 · 打包 · 起服务 · 端口 · 账号 · env · Flyway | `topics/runtime-env.md` |
| 编码 / 改缺陷 / 排查异常 | `topics/pitfalls.md`（**已修坑清单，勿回退**；编号以文件内为准） |
| 跑套件 / 写验收 / 收口 | `topics/e2e-suites.md` |
| **用户端双形态（经典 / OA 协同：构建链 · 断言 · 已知未验项）** | **`docs/39`**（计划）· `user-client/_build_oa.py`（**唯一构建入口，产物 index.html 不可手改**）· `scripts/_e2e_oa.py`（**106 项**，2026-09-30 新增 H 组 + H5d；**H 组需要 agent :8000 在线**，否则 14 项全红且归因文案会明说）· `scripts/_check_dto_fields.py`（DTO 口径哨兵）· **`scripts/_verify_h5_pm_contacts.py`**（11 项：通讯录排除自己 + 项目面板接真 PM + 非成员负向对照；**fixture = T1008 两项目 56/57 + 仓库 165，有意保留**，重建步骤见 `2026-10-08.md` §五）· 本目录 `2026-10-08.md` · `2026-09-30.md` §二/§四 · `2026-09-29.md` §v6 |
| 接口口径 · 登录 · 角色 · 权限链 | `topics/api-permissions.md` |
| 知识库 / 检索 / 向量库 | `topics/vector-store-milvus.md` |
| 仓库联动 Gitee/Gitea | `topics/repo-provider-gitea.md` · **收口哨兵** `scripts/_check_gitee_platform_config.py`（静态 **12** + `--selftest` 12；**S12 = 客户端对可覆盖字段必须走 `RepoProviderSettings` 端口**）· **铁律：管理端可配字段只允许在端口处判定**；客户端直读原始 `*Properties` ⇒ 页面改的值进不了出站 URL（2026-10-10 实测：空 `client_id` ⇒ Gitee 回 `{"error":"Application does not exist"}`） |
| 模型管理 / 手动添加模型 / 默认模型 | `topics/model-config.md`（V61，默认=MiniMax） |
| **生产部署（10.0.0.3）** | `topics/production-deploy.md` + `deploy/生产部署手册.md` |
| 已知缺口 /「判定不改」的数据 | `topics/known-gaps.md` |
| git 推送 | `topics/git-remote.md` |
| 进度口径 | `docs/28 §6`（未开工项唯一权威）· `docs/19`（七项优先事项） |
| **多租户领域模型（平台/租户/机构/部门/员工/用户 六层）** | **`docs/38`** —— 唯一进度权威：批次 A（租户层级+域名+平台调额度）、B（机构类型收敛+信用代码校验）、C（员工↔账号多对多中间表，V67）已完成，D/E 未开工 |
| **项目管理模块（PM：立项→成员→任务→文档→经费→合同，兼容业务/开发两类型）** | **`docs/40`** —— **批次 1 已实装**（立项/成员/任务/仓库绑定，V71）。模块 = `server/aioa-project`；守卫单一判定点 = `support/ProjectTypeGuard`；前端 = `web/apps/shell/src/{api/pm.ts,views/PmProject*View.vue}`。**收口三件套**：`scripts/_check_pm_guards.py`（静态 12 + `--selftest` 12）· `scripts/_smoke_pm.py`（接口 **15 + 1 SKIP**，含数据范围 M9a–e；M7 因本环境无「未归属且 ACTIVE」仓库 → SKIP，不伪装 PASS）· `scripts/_e2e_pm_ui.py`（界面 18，单端口 `:8080/aioa/web`，含 `--selftest` 4）。**仓库与 PM 的界面关系（2026-10-03 定案）**：代码仓库**不再有独立一级菜单**，跟**开发项目**走（详情页「代码仓库」页签，业务项目不渲染 = BR-01）；租户级配置在「系统配置 → 仓库配置」`/settings/repo-config`；`/gitee/projects` 降级为不进菜单的「仓库总览」。核验：`scripts/_verify_repo_menu_merge.py`（19，含 BR-01 负向对照）。**批次 3（文档）已实装**（2026-10-09）：V72 `pm_folder`+`pm_document`，`PmDocService`/`PmDocController`（`/pm/projects/{id}/docs/**`），详情页「文档」页签，立项即建「项目文档」根（历史项目惰性补齐），BR-08 非空 409 与 BR-14 级联已实跑验过；`api/pm.ts` 加 doc 端点。**批次 4（经费流水 + 合同收付款）已实装**（2026-10-09，提交 `e1a9024`）：V75 播 `pm:budget:manage`/`pm:contract:manage`；`PmExpenseService`/`PmContractService` + `PmExpenseController`（`/pm/projects/{id}/expenses` list/create/reverse）+ `PmContractController`（contracts list/create/update/status + payments list/add/confirm/reverse）；详情页真实「经费」「合同」页签。哨兵 `scripts/_verify_pm_finance_contract.py`（**42 项**）。**★关键语义：K4 红冲 = 同方向负金额（红字冲销）**，**不可**写成「方向翻转+正金额」（汇总按方向分桶，翻转会让被冲销支出仍留在支出桶 ⇒ 结余回不去）；`PUT`/`DELETE` 流水端点不存在（本仓对未注册路由回 HTTP 404+`code=404「接口不存在」`，不是 405）。**批次 2（里程碑）仍端点未开工**。两项新能力（项目数字人分配、项目上下文控制）**已实装**（2026-10-10 核实：V76 播 `pm:ai:manage`；`PmDigitalWorkerService`/`PmDigitalWorkerController`/`PmContextSource`/`PmProjectWorker` 均在，`scripts/_verify_pm_digital_worker.py`）—— ✅ **2026-10-10 需求一已把下发链路接上**（commit `abc81de`）：`chat_conversation` 加可空 `project_id`（V79）；`ConversationService.create` 按 `pm_project_worker` 硬校验（未分配或已停用 → **403**）；`RunService.buildScope(workerId, projectId, tenantId)` 经**只读窄端口** `cn.aioa.project.port.PmAiScopePort`（`aioa-chat` 单向下依赖 `aioa-project`，闭包无环）下发项目生效上下文。收口哨兵 **`scripts/_verify_project_isolation.py`（25 项）**：A/B 同脚本 —— **新 jar 25/25 vs 旧 jar 11/18**（旧 jar 的 7 条红正是缺陷本体：`projectId` 被忽略 ⇒ 列表返回全部 34 条会话、跨项目用未分配数字人不回 403）。关键词→表/接口/规则全量映射与 6 条假设见 **`docs/43`**（注意其 `§4/§8` 说「批次 2–4 未开工」是残留，`§2` 的 ✅ 才与代码一致）。**四项新需求（用户端项目功能 / 管理端菜单权限 / 文档上传 / 系统参数漂移）的实施方案 = `docs/44`**（2026-10-10：其中「文档上传失败」与「系统参数漂移」两项已当场定位到根因）。要点：12 张 `pm_*` 表（V71 出 3 / V72 出 2 / V73 出 5 / V74 出 2）+ `gitee_project` 加 `pm_project_id`；`gitee_task` 是异步队列**不是**业务任务（新表叫 `pm_task`）；「云端文件夹」全库无对象存储，先留 `storage_kind` 抽象位；审批复用 `biz_type=PM_CONTRACT/PM_EXPENSE`；ADR-007 只借开源领域模型不嵌第二套运行时。**仓库绑定不建映射表**：靠 `UPDATE ... WHERE pm_project_id IS NULL` 的原子影响行数保证「一仓库只归一项目」；解绑只置空不删行。 |
| **`gitee_project` 加列零回归哨兵** | `scripts/_check_gitee_repo_write.py`（R1 新列不得泄漏到既有接口 / R2 既有 INSERT 仍落库 / R3 新列语义自洽）。**需后端以 `source scripts/gitee-e2e-env.sh` 启动**（Gitee 指向桩 :8090）；前置不满足时记 SKIP 并返回非 0，**不伪装 PASS** |
| **代码仓库全流程（V48）夹具与落库核对** | **夹具 = 租户 `某某智能科技有限公司`（`MYQY-DEMO`）+ `znkj_admin`(租户管理员)/`znkjyf_admin`(机构)/`znsfb_ldr`(同部门)** —— **不在 Flyway 里**，由 `scripts/seed_multi_tenant.py` 经 API 开通；2026-09-20「租户 9 清除」删过它 ⇒ 跑 `scripts/e2e_v48_gitee.py` **前先重跑 seed 脚本**（否则登录步即中止）。**2026-10-10 实跑 116/0**；落库核对 = `scripts/_verify_repo_flow_persisted.py --tenant <id>`（11 项：account/project/member/event/commit/task + 本轮时间窗）。**三处已修的「写死 id」**：部门/用户 id 改由 `resolve_fixture()` 从**登录令牌**取（`uid`；部门取 `znsfb_ldr.did`）· `TOK["tenant"]` 必须是**租户管理员**（`/gitee/calibrate`、`/gitee/tasks/stats` 只认 TENANT_ADMIN）· MR/Issue/Note 事件 id 必须**每轮唯一**（`uk_gitee_event_key` 全局唯一）。**两条留判据不改代码的观察**：① 可重试错误（限流）会**先写 FAILED 再翻回 ACTIVE**（用户见一次假失败）⇒ FR-8.3 须等终局；② `event_key` 不带项目维度。故事：本目录 `2026-10-10.md` §十二 |
| **缺陷台账（每条给出可复跑的判据 + 处置三态）** | **`docs/42`** —— 2026-10-02 模拟项目全流程自检 + 管理端 AI 助手修复。本轮留存哨兵：`scripts/_repro_admin_assistant_ui.py`（AI 助手，12/12）· `scripts/_e2e_pm_simulated_project.py`（PM 全流程，33/0/1）· `scripts/_check_sse_termination.py`（SSE 终止块，报告型哨兵：恒退出 0，看 `[STATUS]`；D-C 未修时恒为 `DEFECT-PRESENT`）。故事：本目录 `2026-09-30.md` §八 |
| **四项需求实施方案（用户端项目功能 · 管理端菜单权限 · 文档上传 · 系统参数漂移）** | **`docs/44`** —— 2026-10-10 规划，**其中两项当场定位到根因**：① **文档上传 100% 500** = `PmDocService.java:355` 三元表达式把 `Long` 拆箱（上传路径 `asLong(null)` ⇒ NPE），前端从不发 `sizeBytes` ⇒ 只有「上传」坏、「AI 创建」不坏（A/B 对照已证）；② **生产系统参数只剩 3 条** = `V18` 只播 `tenant_id=1` + `V33/V34/V62` 把 `tenant_id=0` 写成「非空但残缺」⇒ `loadTenantConfigs` 的 `isEmpty()` 兜底永不触发（铁律 18）。**该文同时推翻三处旧结论**：`docs/43 §4/§8`（PM 批次 2–4 其实已实装）、`docs/39 §6.1`（用户端项目已接真 PM）、`docs/43 §2` K7/K8（下发链路其实没接）。故事：本目录 `2026-10-10.md` §十五 |
| **管理端 SSE / AI 助手** | `web/apps/shell/src/api/runs.ts`（终态帧后断流**不是**失败，抛 `StreamEndedAfterCompletion` 吞掉；**不能只 `return`**，否则 `fetch-event-source` 按 1s 无限重连）· `src/stores/assistant.ts`（改消息必须经 `this.messages[i]` 取代理对象）。服务端 `SseEmitter` 未发终止块（SPR-14444 同类）**未修**，H5 端免疫 |
| **四项需求（docs/44）· 已修 2 项缺陷** | **`docs/44`** 是四项需求的唯一权威：§3 文档上传 500、§4 系统参数漂移**已修并 A/B 验证**（`7c61700` / `e2244e9`），三处过期结论**已更正**（`b0e3462`）；**§2 管理端菜单与机构参数 仍未开工**；**§1 用户端项目功能 已实施**（`abc81de`：项目可点击进入 + 会话/数字人/文档/花费按项目隔离，见 `2026-10-10.md` §十七）。新哨兵：`scripts/_verify_pm_doc_upload.py`（21 项，带 `--selftest`）· `scripts/_verify_sys_config_template.py`（13 + 1 诚实 SKIP）· **`scripts/_verify_project_isolation.py`（25 项，A/B 新 25/25 vs 旧 11/18）**；A/B 证据 `logs/proof/req3_pm_doc_upload_{OLD_8080,NEW_8081}.txt`、`logs/proof/req4_selfheal_AB.txt`、`logs/proof/req1_isolation_AB_{newjar,oldjar}.txt`。**改后端后先比 `aioa-boot/target/*.jar` 与源码 mtime —— jar 旧 = 修复未生效**（:8080 跑的是 jar，不是 `classes`）；无侵入验收法见 §十六。 |

## 铁律（每次都要遵守）

1. **展示必须与事实同源**：同一决策点只在一处判定。回填用户可见文案**不准照抄历史原文**（判据：「这行文本放**今天**的配置下，还是真的吗？」）。
2. **每一步失败都要有终态**：凡「A 步成功才入队 B 步」，B 的终态失败必须回写主对象。**不可逆动作绝不静默成功**（执行段不得 `selectById`，信息不全抛错判 FAILED）。
3. **前端 `unwrap` 必须校验 `code`**，否则失败信封被当业务数据 ⇒ 页面空白无数据。
4. **管理端配置页 = 能力的唯一入口**：引擎支持但配不出来 = 能力事实上不可用。常量只有一个入口（`constants/permissions.ts`），配置页须 `_extra` 无损往返。
5. **新增可配置维度 ⇒ 造出旧状态机从未有过的组合，必须为该组合补断言**（最易漏的缺陷类型）。
6. **诊断端点回「报告」（恒 200 + `code=0` + `steps`），动作端点才失败即抛**；`passed` 必须与 `steps` 同源推导。
7. **绝不为转绿而放宽断言**；`chk(name, True, "")` 这类恒真断言比没断言更危险。
8. **改权限 / 可见性 / 生效态 / 登录口径后**：全局搜既有套件的旧口径断言 + **连跑两次**；历史遗留行 ≠ 代码 bug（能回填就加迁移修数据，断言原样保留）。
9. **管理端测试必须逐角色分进程**（单浏览器连跑 20+ 路由必挂起）；**长驻服务绝不交给子代理启动**（子代理被 kill 会带走子进程，服务静默消失）。
10. **本环境禁用 `git rm`**（曾一次误删清空整个目录）：用 `rm 明确文件列表` + `git add`，小步走、每批核对 `git status`。恢复正确性用「跑套件」判定，不用文件大小。
11. **「与基线一致」≠ 干净**：基线本身可能已含历史残留（实例：E2E 造的 9 个机构被长期当成「机构总数 22」的基线，于是 50% 的污染被放行很久）。数量类断言要么能说出基线里**每条**是什么，要么直接断言「按命名前缀筛出的残留数为 0」；造数据的脚本收尾必须让数据**退出业务可见面**，不是只改个状态。
12. **断言「界面展示了某事实」时，判据不得与被测对象同源**：判据必须回到**事实源头**（接口/库）重新取一次，不能读**界面自己的数据副本**——否则「渲染层读错字段」会让判据与实现一起错、测试永远绿（本轮实测：首版 F3a 读 `state.workers` 时，负向测试复现旧缺陷**仍是绿的**）。**凡新写的「同源」断言，先跑负向测试证明它会红**，否则无法区分「真通过」与「判据无效」。
13. **清理仓库前必须先过「禁删清单」**（做过一轮全库清理后固化，2026-09-30）。下列路径**看着像垃圾、实则是资产**，一律不删：
    | 路径 | 为什么不能删 |
    |---|---|
    | `logs/proof/` | **有意保留的举证目录**（e2e-suites 明写「要留证就 `cp` 到 `logs/proof/`」） |
    | `logs/reset_backup/` | **DB 回滚快照**（2026-09-12 写死的保留红线） |
    | `docs/_incoming/非违接口文档.txt` | 5 份已入库文档的**依据源**；且含凭证 ⇒ 只在本机、严禁入库 |
    | `docs/_incoming/probe_show_result.json` | 生产环境探测的**唯一原始响应体**（环境已变，难复现） |
    | `ux-review/用户体验走查报告.html` | 历史交付产物，**曾被误删并刻意 `git checkout --` 还原**（2026-09-17） |
    | `user-client/_oa_clean.html` | `_build_oa.py` 的**构建输入**（不是中间垃圾） |
    | `user-client/_backup_index_pre_oa.html` | 重建的唯一经典基线段 |
    | `scripts/_check_*` `_probe_*` `_verify_*` `_refaudit_*` `_run_all_regression.sh` | 项目约定的**长期回归哨兵**（`topics/git-remote.md`） |
    | `scripts/e2e_*.py` | 本地**必跑回归面**（虽被 .gitignore，仍要留在磁盘上） |
    | `scripts/_diag_member1_restore.py` | 可复算的破坏性恢复件 |
    | `start-backend.bat` | 用户自有终端启动后端的唯一入口 |
    | `agent/.venv` `*/target` `*/node_modules` `*/dist` | 构建/运行缓存（非「文档/日志/测试文件」，不属清理对象） |
    判据：**删任何东西之前先问「有没有文档/记忆/CI/构建脚本引用它」，引用即保留**；只删「未入库（.gitignore）**且**无任何执行依赖」的生成物。删除走环境的 safe-delete（进回收站，可恢复）。
14. **`nohup X &` 在 Bash 工具调用里起的进程，会在该次调用结束时被回收**（2026-09-30 实测：8080 后端存活 <1 分钟即消失，日志末尾是**正常启动完成、无异常栈**）。要活过本会话必须用工具的 `run_in_background`；要**长期**运行只能由用户在自有终端启动（`start-backend.bat` / `bash start-all.sh`）。见到「日志正常但进程凭空不见」就是被回收，**不要去翻日志找 bug**。
15. **跑任何既有套件前先验它的 fixture 还在不在**：本轮实例 —— `e2e_v48_gitee.py` 的主操作人是**租户 9** 的 `znkjyf_admin`，而当前 `sys_tenant` 只剩 1/2/3（租户 9 已被移除）⇒ 套件在**登录步**即以 `1001 用户名或密码错误` 中止。**2026-10-03 同类第二个实例**：`scripts/verify_v48_ui.py` 绑 `znkj*` 租户（`LIKE 'znkj%'` 计数 = 0）且入口写死 dev `:5173`。此现象**不是**「套件坏了」也不是本次改动引起，而是环境漂移 ⇒ 必须如实记为「本环境跑不起来」，**不许改成别的账号硬跑**（那会让断言落到未被设计覆盖的分支上）。
16. **JDK `HttpClient` 默认 HTTP/2，对明文 `http://` 目标会先发 h2c 升级请求**；uvicorn 桩与部分自建服务端不认该升级，回 `Unsupported upgrade request` + `Invalid HTTP request received` ⇒ 业务侧看到的是「Gitee 拒绝了本次授权」这类**与业务无关的假象**。本仓库约定是显式钉 HTTP/1.1（见 `common/http/AgentHttpClient`、`integration/scfy/ScfyClient` 的注释）；2026-09-30 已给 `aioa-gitee` 的 `GiteeClient` / `GiteaProviderClient` 补齐。**新写调用明文 http 的客户端时必须钉版本**。
17. **本环境推 github：HTTPS 写通道已被出网代理掐死（`CONNECT tunnel failed, response 502` / `schannel: server closed abruptly`），但 SSH 端口会变**（2026-10-10 实测两次结论不同）：早上 **22 端口**秒推成功，当晚 22 端口变 **`Connection refused`（被主动拒绝，不是超时）**，改走 **`ssh.github.com:443`** 又秒推成功。⇒ **推送前先跑三条探针、谁通走谁，别再反复重试已确认不通的那条**：`ssh -T git@github.com` · `ssh -T -p 443 git@ssh.github.com` · `curl -m12 -o /dev/null -w '%{http_code}' https://github.com`；**只要 443 通就一定能推**。`ls-remote` 走 HTTPS 也可能通 ⇒ **读通 ≠ 写通，别用只读成功推定能 push**。已把 `github` remote **永久切成 443 形式**（`ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git`，无需 `-i`/escalation）。收口**按 SHA 比对**（`git rev-parse HEAD` vs `git ls-remote github main`），**不看返回码**。详见 `topics/git-remote.md`。

18. **「兜底写在 `isEmpty()` 上，而那个容器永远非空 ⇒ 兜底永不触发」是反复出现的反模式**（2026-10-10 实证 `sys_config`）。判据：凡「模板/默认值 + 首次克隆」结构，断言必须落到**键级齐全**，不能只断言「非空」；克隆语义应是「缺哪个键补哪个」（并集），不是「有行就返回」。同族第二例见 `docs/28 §2.8(D-8)`（新租户漏播 `leave_type`）。**实例**：`AdminConfigController.loadTenantConfigs()` 因 `tenant_id=0` 被后加迁移写成「非空但只有 3 条」，导致 `BUILTIN_DEFAULTS`（完整 14 条）永不生效 ⇒ 生产 `GET /admin/configs` 只有 **3** 条。另：该接口的配置值在 `data.values`/`data.sources`，**不在 `data.fields`**。
19. **诊断「某功能失败」的正确顺序是「复现 → 拿 traceId → 翻日志拿栈 → A/B 对照」**，不是读代码猜（2026-10-10 实证：子代理静态读代码判「权限不足」为 #1 原因，实跑后 `canManage=true` 直接推翻，真因是 `PmDocService.java:355` 三元表达式拆箱 NPE ⇒ 500）。**A/B 对照**是收口关键：只改一个变量、看红绿翻转（本例：不带 `sizeBytes` → 500；带上 → `code:0`）。凡「两端对同一字段口径不一致」，必查**前端请求体到底发了哪些字段**，别只看后端接口文档。
20. **MySQL `INSERT ... SELECT` 的 `ON DUPLICATE KEY UPDATE` 必须写成「目标表全名限定」**（2026-10-10：`V78` 因此迁移失败 → Flyway 失败 → **应用直接起不来**）。源表与目标表**同名**时（`INSERT INTO sys_config SELECT ... FROM sys_config p`），裸写 `config_key = config_key` 报 **1052 Column 'config_key' in field list is ambiguous**；正解 `ON DUPLICATE KEY UPDATE \`sys_config\`.\`config_key\` = \`sys_config\`.\`config_key\``。**不能照抄 V62**——它的源是只含 `tid` 的派生表，恰好没同名，所以它的同款写法从没炸过。配套两条：① Flyway 失败会留 `flyway_schema_history.success=0` 行，**不清掉则后续每次启动都失败**（`DELETE FROM flyway_schema_history WHERE version='78' AND success=0` 后重跑）；② **零副作用验迁移**：`BEGIN; <迁移文本>; ROLLBACK;`（纯 DML 可回滚）+ 按 `;` 逐条执行能一次点明是哪条炸。
21. **改了后端代码后，先确认「正在跑的那个产物」是否含本次改动，再谈验证**（2026-10-10 实证：源码与 `target/classes` 都是新的，但验收 16/21 全红——因为 :8080 跑的是 **17:11 构建的 fat jar**，IDE 只重编了 `classes`，JVM 不热载）。`start-backend.bat` 启动的是 `server/aioa-boot/target/*.jar`。判据：`stat` 比 **jar mtime vs 源码 mtime**，**jar 比源码旧 = 修复没生效，不要去怀疑代码**。**无侵入验证法**：把 `server/` 源码树 `tar` 到临时目录（`--exclude='*/target'`）→ 在那里 `./mvnw -DskipTests clean package` → **另起端口**（如 8081）验收 ⇒ 完全不动用户正在跑的 8080 及其已 source 的 env。注意 `java -jar` 要 **Windows 路径**（`C:/...`；传 `/c/...` 报 `Unable to access jarfile`）。
22. **「缓存 + 复用」必须带失效条件，否则会静默跳过绑定与校验**（2026-10-10 需求一实证）。H5 项目分支曾写**无条件** `if(existing){ 复用 }`：进入项目时建的是**无员工会话**，之后 `oaPickWorker` 换数字人只清了 `S.convId`、**没清项目槽** ⇒ 下次发送把那条无员工会话又取回来 ⇒ **界面选了数字人、会话却没绑 `workerId`** ⇒ 职责范围/项目上下文全失效，**且后端「未分配员工不得建会话」的 403 准入被整条合法路径绕过**（越权/隔离类缺陷的隐蔽形态：测试若只验「选了人有没有显示」，必然全绿）。修法：**复用必须以「当初绑定的那个 worker」为条件**（记 `S.projectConvWorker[pid]` 比对），且在换上下文（`enterProject`）时清掉进入前的选择。**规矩**：凡新增/修改"缓存+复用"结构，先答「它的失效条件是什么？换人/换项目/换租户后还会被复用吗？」，并把该条件固化成**静态回归指纹**（如哨兵 G4：源码须含守卫、且不含那句无条件复用）。
23. **PowerShell 工具在本机可能恒返回空输出**（2026-10-10 实测：`Get-Process`/`Get-CimInstance`/`Get-Process | Out-String` 一律 "Command completed with exit code 0" 且无 stdout）。因此**不要依赖它做「确认/杀进程」**；需要腾端口时优先**换端口**（另起 8082），而不是去杀别人的实例。
