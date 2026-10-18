# AIOS 长期记忆（索引 + 铁律）

> 本文件只放「每次都要遵守的」；明细按主题在 `topics/`，故事在同目录 `YYYY-MM-DD.md`。
> **压缩前全文快照**（含下表被压缩掉的全部长条目原文）：`archive/MEMORY-full-2026-10-17.md`（只读）。
> 找不到某条细节时先查该快照，再查 `topics/`，最后查当日 `YYYY-MM-DD.md`。

| 何时读 | 文件 |
|---|---|
| 项目结构 · 打包 · 起服务 · 端口 · 账号 · env · Flyway | `topics/runtime-env.md` |
| 编码 / 改缺陷 / 排查异常 | `topics/pitfalls.md`（**已修坑清单，勿回退**；编号以文件内为准） |
| 跑套件 / 写验收 / 收口 | `topics/e2e-suites.md` |
| 接口口径 · 登录 · 角色 · 权限链 | `topics/api-permissions.md` |
| 知识库 / 检索 / 向量库 | `topics/vector-store-milvus.md` |
| 仓库联动 Gitee/Gitea | `topics/repo-provider-gitea.md` · 哨兵 `scripts/_check_gitee_platform_config.py`（静态 12 + `--selftest` 12）· **铁律：管理端可配字段只允许在端口 `RepoProviderSettings` 处判定**（客户端直读 `*Properties` ⇒ 页面改的值进不了出站 URL） |
| 模型管理 / 手动添加 / 默认模型 | `topics/model-config.md`（V61，默认 MiniMax） |
| 生产部署（10.0.0.3） | `topics/production-deploy.md` + `deploy/生产部署手册.md` |
| 已知缺口 /「判定不改」的数据 | `topics/known-gaps.md` |
| git 推送 | `topics/git-remote.md` |
| 进度口径 | `docs/28 §6`（未开工项唯一权威）· `docs/19`（七项优先事项） |
| **用户端双形态（经典 / OA 协同）** | `docs/39`（计划）· **`user-client/_build_oa.py` 是唯一构建入口，产物 `index.html` 不可手改**（源：`_backup_index_pre_oa.html` + `_oa_app.js` + `_oa_markup.html` + `_oa_extra.css` + `_oa_polish.css`）· 全套哨兵见 `topics/e2e-suites.md` 与本目录 `2026-10-12/13/17.md` |
| **OA 模块 = 43 个数字人 + 模块目录（2026-10-17 实装）** | 抽屉「OA 模块43」→ `#v-modules` 网格 → 点卡即 `oaPickWorker`（**复用唯一入口，不造第二条路径**）· **H5 状态全局是 `window.oaState`，不是 `window.S`**（IIFE 闭包，`_oa_app.js:2581` 才挂出来）· 收口 **`scripts/_e2e_oa_modules.py`（K0–K6：43 卡逐张点 + 43 次发送 + `--mutate` 自检）** · 后端哨兵 `scripts/_verify_oa_module_workers.py`（M1–M8）· V83 建 43 条模板、**V84 回填 `source_template_id`**（V83 的 CROSS JOIN 让租户行序不确定 ⇒ 前端按它排序）· 后端唯一判定点 `aios-resource/.../support/WorkerProfile.java` · 故事 `2026-10-17.md §一/§二` |
| **H5 弹层样式「永不匹配」陷阱** | 弹层都 `appendChild` 到 `document.body`，**不在 `.oa`（#oaRoot）内** ⇒ 规则写 `.oa .x{…}` **永不匹配**（现象是「浏览器原生控件直出」，不是「没写样式」）；`--brand*` 也只定义在 `.oa{}` 里 ⇒ 弹层内 `var(--brand-*)` 无效。**修法**：弹层自带标记类（本仓 `.oa-dlg`）+ 自带品牌令牌；**绝不裸写** `.notif-modal`/`.note-err`/`.notif-foot .btn`（经典形态 10 处共用）。一条判据定位：`getComputedStyle(el).flexDirection`。详见快照与 `2026-10-12.md §13` |
| **OA 功能扩展 + 数字人自建 + 自定义表单（`docs/52`，★规划未实装）** | 43 个功能模块（原有 26 + 补充 17）。**已核实三现状**：① `WorkerRole` 只有 4 个硬编码角色（用户不能自建任意数字人）；② `formFields` 是假的（`agent/aios_ai/intent/intake.py` 只有中文提示串，全仓无动态表单）；③ `expert_settings` agent 会解析但 `RunService` 从不注入。**定案：扩展 HITL 澄清链（A），不扩展 action-intent 弹窗链（B）**。四域 Worker/Form/Invocation/DataFlow；契约 V83+ 起 `form_template`/`form_submission`/`worker_capability`，权限码 `form:manage`/`worker:capability`。**`form_submission` 是唯一事实源**，`approval_order.form_data` 只存快照。故事 `2026-10-17.md §一` |
| **请假意图自动判权 + 写工具硬闸（`docs/51`）** | `agent/aios_ai/graph/nodes.py::filter_intent_write_tools(tools, action)`：**action 非空就剥掉 `apply_permission`**（确定性代码门，非软提示）。泛化口径：**任何 action 意图 ⇒ 确认归 UI ⇒ 不下发写工具**。判据落在「模型真正收到的 tools 列表」，非界面副本 |
| **AI agent 内核（LangGraph + HITL 澄清）** | `agent/aios_ai/` 是 AI 唯一归属地（`app/**` 皆垫片）· `aios_ai/README.md` · HITL 开关 **`AIOS_HITL`（默认 false）**、`AIOS_CHECKPOINT_URL`（空=内存；生产=Redis）· 入口 `POST /internal/v1/runs/{run_id}/resume`、门面 `facade.resume` · 哨兵 `scripts/_verify_ask_user_hitl.py` / `_check_aios_ai_boundary.py` / `_check_hitl_resume_wire.py` / `_verify_h5_clarification.py` · 故事 `2026-10-15.md §十/§十二/§十三`、`2026-10-16.md` |
| **多租户领域模型（平台/租户/机构/部门/员工/用户）** | `docs/38`（唯一进度权威）：批次 A/B/C 已完成（C=V67 员工↔账号多对多），D/E 未开工 |
| **项目管理模块（PM）** | `docs/40`（批次 1 已实装，V71）· 模块 `server/aios-project`；守卫单一判定点 `support/Project…` |
| `gitee_project` 加列零回归哨兵 | `scripts/_check_gitee_repo_write.py`（R1 新列不泄漏 / R2 既有 INSERT 仍落库 / R3 语义自洽），需 `scripts/gitee-e2e-se…` 环境 |
| 代码仓库全流程（V48）夹具 | 租户「某某智能科技有限公司」(`MYQY-DEMO`) + `znkj_admin`/`znkjyf_admin`/`znsfb_ldr`，**不在 Flyway 里**，由 `scripts/…` 造 |
| 缺陷台账（可复跑判据 + 处置三态） | `docs/42` · 留存哨兵 `scripts/_repro_admin_assistant_ui.py` 等 |
| 四项需求（用户端项目 · 管理端菜单权限 · 文档上传 · 系统参数） | `docs/44`（唯一权威）：§3 上传 500、§4 参数漂移**已修并 A/B 验证**；§1 项目、§2 菜单权限状态见 §7 复核 |
| 对话内上传文档 / 语音输入 | `docs/46`（规格）· `docs/47`（**已按简化版实装**：音频原始字节直传、非安全上下文只置灰）· 造语音取证只能靠本地 piper（模型缓存 `%TEMP%/piper_zh/`） |
| 管理端 SSE / AI 助手 | `web/apps/shell/src/api/runs.ts`：终态帧后断流**不是**失败（`StreamEndedAfterCompletion`）；**不能只 `return`** |
| 知识库开关 `kb_on`（三层） | H5 `createRun` 把 `kb_on` 提到 body 顶层；Java 透传；agent 消费。含「SSE 流结束重复鉴权」修复 |
| 数字人回答机制 / AI 回答口径 | `docs/49` + **唯一事实源 `agent/app/core/answer_shape.py::rules()`**（改口径只改这里；旧总纲「默认只答所问」已废） |

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
16. **JDK `HttpClient` 默认 HTTP/2，对明文 `http://` 目标会先发 h2c 升级请求**；uvicorn 桩与部分自建服务端不认该升级，回 `Unsupported upgrade request` + `Invalid HTTP request received` ⇒ 业务侧看到的是「Gitee 拒绝了本次授权」这类**与业务无关的假象**。本仓库约定是显式钉 HTTP/1.1（见 `common/http/AgentHttpClient`、`integration/scfy/ScfyClient` 的注释）；2026-09-30 已给 `aios-gitee` 的 `GiteeClient` / `GiteaProviderClient` 补齐。**新写调用明文 http 的客户端时必须钉版本**。
17. **共享消费者对「可选回调」必须逐一守存在（`if(h.onXxx)`），删回调时要回头查消费器**：实例（2026-10-12 用户截图复报）—— 共享 SSE 消费器 `_backup_index_pre_oa.html:1580` 调 `h.onUsage(...)` **无守卫**，而相邻 `onStarted`/`onCompleted`/`onApproval` **全都有** `if(h.onXxx)`；按需求从 OA 处理器删掉 `onUsage` 后，消费器**无条件调用未定义函数** ⇒ 整条回答流抛 `TypeError: h.onUsage is not a function`、气泡被覆写成「请求失败」、且**依赖回答完成**的弹窗**永不出现**（表面症状与「删调试信息」毫无关联，极易误判）。判据：**增删任一可选回调时，必须同时检查两侧 —— 调用点是否守卫 + 每个 handler 是否定义**；「可选」只能由消费器端守卫体现，不能靠「反正我会定义」臆断。
17. **「源码里有」≠「运行实例里有」**：判「运行实例是否含某改动」必须看**制品/活体**——jar 内嵌 jar 的 class 字节（Python `zipfile`）、agent 活体 `/openapi.json`、`flyway_schema_history` / `information_schema`；**不得只看源码 mtime**。实例（2026-10-12）：源码比运行实例新 3 小时，`attachments` 在源码里有、在运行的 jar/agent/DB 里全无，**没有任何告警**，表现只是「＋上传的文档 AI 看不到」这种静默失效。配套：**构建入口用 `server/mvnw`**（系统 `mvn` 包装脚本会报 `ClassNotFoundException: …classworlds.launcher.Launcher`，那是 `M2_HOME` 未设、不是缺依赖）；**就绪判据不得用 `/aios/actuator/health`**（恒 401，走安全链），看 `boot.log` 的 `Started AiosBootApplication` 或 `netstat` 监听。
18. **把元素改成「默认隐藏」⇒ 只挑可见元素的测试会「静默缩水」，报告仍写全绿**：`pick(sel)=all.find(vis)` 挑不到就记 `missing`，聚合循环再 `skip` 掉 ⇒ 该元素的所有断言**无声消失**（连「未验」列表都不进），退出码 0。实例（2026-10-12）：胶囊改造把 `#oaSendBtn` 空输入时 `display:none`，`_check_oa_visual.py` 的 `C/E .cbtn.send` 两条当天没跑，**恢复覆盖后立刻抓出真回归**（命中区 44→34，因胶囊规则特异性高于 `_oa_polish.css:116`）。纪律：**凡改了某元素的可见性/生效态，必须回头确认「以该元素为样本的断言是否还在跑」**，并给关键样本加**覆盖自检断言**（样本缺失即红），别只依赖它「没报错」。反之，`el.click()` 这类**绕开可见性**的点击（`e2e_v61` 的 `click_by_selector`）**证明不了「用户点得到」**，可达性必须用真实 click + computed style 断言。
17. **本环境推 github：HTTPS 写通道已被出网代理掐死（`CONNECT tunnel failed, response 502` / `schannel: server closed abruptly`），但 SSH 端口会变**（2026-10-10 实测两次结论不同）：早上 **22 端口**秒推成功，当晚 22 端口变 **`Connection refused`（被主动拒绝，不是超时）**，改走 **`ssh.github.com:443`** 又秒推成功。⇒ **推送前先跑三条探针、谁通走谁，别再反复重试已确认不通的那条**：`ssh -T git@github.com` · `ssh -T -p 443 git@ssh.github.com` · `curl -m12 -o /dev/null -w '%{http_code}' https://github.com`；**只要 443 通就一定能推**。`ls-remote` 走 HTTPS 也可能通 ⇒ **读通 ≠ 写通，别用只读成功推定能 push**。已把 `github` remote **永久切成 443 形式**（`ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git`，无需 `-i`/escalation）。收口**按 SHA 比对**（`git rev-parse HEAD` vs `git ls-remote github main`），**不看返回码**。详见 `topics/git-remote.md`。

18. **「兜底写在 `isEmpty()` 上，而那个容器永远非空 ⇒ 兜底永不触发」是反复出现的反模式**（2026-10-10 实证 `sys_config`）。判据：凡「模板/默认值 + 首次克隆」结构，断言必须落到**键级齐全**，不能只断言「非空」；克隆语义应是「缺哪个键补哪个」（并集），不是「有行就返回」。同族第二例见 `docs/28 §2.8(D-8)`（新租户漏播 `leave_type`）。**实例**：`AdminConfigController.loadTenantConfigs()` 因 `tenant_id=0` 被后加迁移写成「非空但只有 3 条」，导致 `BUILTIN_DEFAULTS`（完整 14 条）永不生效 ⇒ 生产 `GET /admin/configs` 只有 **3** 条。另：该接口的配置值在 `data.values`/`data.sources`，**不在 `data.fields`**。
19. **诊断「某功能失败」的正确顺序是「复现 → 拿 traceId → 翻日志拿栈 → A/B 对照」**，不是读代码猜（2026-10-10 实证：子代理静态读代码判「权限不足」为 #1 原因，实跑后 `canManage=true` 直接推翻，真因是 `PmDocService.java:355` 三元表达式拆箱 NPE ⇒ 500）。**A/B 对照**是收口关键：只改一个变量、看红绿翻转（本例：不带 `sizeBytes` → 500；带上 → `code:0`）。凡「两端对同一字段口径不一致」，必查**前端请求体到底发了哪些字段**，别只看后端接口文档。
20. **MySQL `INSERT ... SELECT` 的 `ON DUPLICATE KEY UPDATE` 必须写成「目标表全名限定」**（2026-10-10：`V78` 因此迁移失败 → Flyway 失败 → **应用直接起不来**）。源表与目标表**同名**时（`INSERT INTO sys_config SELECT ... FROM sys_config p`），裸写 `config_key = config_key` 报 **1052 Column 'config_key' in field list is ambiguous**；正解 `ON DUPLICATE KEY UPDATE \`sys_config\`.\`config_key\` = \`sys_config\`.\`config_key\``。**不能照抄 V62**——它的源是只含 `tid` 的派生表，恰好没同名，所以它的同款写法从没炸过。配套两条：① Flyway 失败会留 `flyway_schema_history.success=0` 行，**不清掉则后续每次启动都失败**（`DELETE FROM flyway_schema_history WHERE version='78' AND success=0` 后重跑）；② **零副作用验迁移**：`BEGIN; <迁移文本>; ROLLBACK;`（纯 DML 可回滚）+ 按 `;` 逐条执行能一次点明是哪条炸。
21. **改了后端代码后，先确认「正在跑的那个产物」是否含本次改动，再谈验证**（2026-10-10 实证：源码与 `target/classes` 都是新的，但验收 16/21 全红——因为 :8080 跑的是 **17:11 构建的 fat jar**，IDE 只重编了 `classes`，JVM 不热载）。`start-backend.bat` 启动的是 `server/aios-boot/target/*.jar`。判据：`stat` 比 **jar mtime vs 源码 mtime**，**jar 比源码旧 = 修复没生效，不要去怀疑代码**。**无侵入验证法**：把 `server/` 源码树 `tar` 到临时目录（`--exclude='*/target'`）→ 在那里 `./mvnw -DskipTests clean package` → **另起端口**（如 8081）验收 ⇒ 完全不动用户正在跑的 8080 及其已 source 的 env。注意 `java -jar` 要 **Windows 路径**（`C:/...`；传 `/c/...` 报 `Unable to access jarfile`）。
22. **「缓存 + 复用」必须带失效条件，否则会静默跳过绑定与校验**（2026-10-10 需求一实证）。H5 项目分支曾写**无条件** `if(existing){ 复用 }`：进入项目时建的是**无员工会话**，之后 `oaPickWorker` 换数字人只清了 `S.convId`、**没清项目槽** ⇒ 下次发送把那条无员工会话又取回来 ⇒ **界面选了数字人、会话却没绑 `workerId`** ⇒ 职责范围/项目上下文全失效，**且后端「未分配员工不得建会话」的 403 准入被整条合法路径绕过**（越权/隔离类缺陷的隐蔽形态：测试若只验「选了人有没有显示」，必然全绿）。修法：**复用必须以「当初绑定的那个 worker」为条件**（记 `S.projectConvWorker[pid]` 比对），且在换上下文（`enterProject`）时清掉进入前的选择。**规矩**：凡新增/修改"缓存+复用"结构，先答「它的失效条件是什么？换人/换项目/换租户后还会被复用吗？」，并把该条件固化成**静态回归指纹**（如哨兵 G4：源码须含守卫、且不含那句无条件复用）。
23. **PowerShell 工具在本机可能恒返回空输出**（2026-10-10 实测：`Get-Process`/`Get-CimInstance`/`Get-Process | Out-String` 一律 "Command completed with exit code 0" 且无 stdout）。因此**不要依赖它做「确认/杀进程」**；需要腾端口时优先**换端口**（另起 8082），而不是去杀别人的实例。
24. ★**本仓库禁用 `git commit --amend` / `git rebase`（含 `-i --autosquash`）/ `git reset --hard` / `git gc` / `git stash`（含 `stash push` / `stash pop` / `stash drop`）**（2026-10-12 一天内两次「对象库被清」事故；第一次是 2026-10-11 的 `.git` 损坏 ⇒ 已是**第三次** git 事故）。
   **第三次事故（同日 · 凶手 `git stash`）**：两个 worker 为「证明测试会红」执行 `git stash push`，被**沙箱 SIGTERM 中断在 repack 中途** ⇒ 旧 `objects/pack/*.pack` 已删、新 pack 未写完 ⇒ `main` 退回 `8b59f7d`，本次会话 16 个提交 `git cat-file` 全 `fatal`（与第二次同一种「对象真没了」）。**教训**：`stash`/`gc`/`rebase` 都会触发 **repack（改写 pack 文件）**，凡是会 repack 的命令，只要进程可能被外部 kill，就有「包被删一半」的窗口 ⇒ 一律禁用。要「证明测试会红」，**复制文件到临时目录再改那份拷贝**，不要动仓库工作树。
   **第三次的恢复路径（本地对象库已不可用时）**：① 先导出**仓库外**工作区快照（`tar`，含在途 worker 的交付）；② **克隆一个完好仓库**（github 上 `8b59f7d` 之前的祖先节点是完整的）——**必须克隆到工作区内部**（如 `.recover_clone/`），前台克隆到工作区外会被沙箱静默丢弃；③ 把工作区内容覆盖进克隆、设 `core.autocrlf false` + 身份，按原提交边界**显式文件列表**重建提交；④ `git push` 到 github 固化（本次 `8b59f7d..10d26bc`，PUSH_EXIT=0）；⑤ 回来后把健康 `.git` 换到原路径：`mv .git .git.broken-<date>` + `cp -r .recover_clone/.git .git` + `git config core.autocrlf true`（**恢复用户原有检出习惯**）+ 在 `.git/info/exclude` 里排掉 `.recover_clone/` 与坏 `.git` 备份。
   **行尾噪声识别（恢复后必查）**：tar 覆盖工作区后 `git status` 会报**成百上千个 ` M`**；**判据是 `git diff --ignore-cr-at-eol --numstat | wc -l`**（=0 即纯 CRLF/LF 噪声、零内容漂移）。`git status` 的 ` M` 与其后 `git diff` 空**不矛盾**——那是 tar 覆盖导致的 stat 缓存失效，`git add -A` 刷新索引即可清；`git cat-file blob X | head -c N` 报 `fatal: unable to stream ... to stdout` 是 **SIGPIPE 假警报**（head 提前关闭管道），不是对象损坏。
   **事故链**：队友为「把 README 并进自己的提交」先 `commit --amend`（**误 amend 到了别人的提交 `ddf439f`**），再用 `rebase -i --autosquash` 纠正 ⇒ rebase 报 `main does not have any commits yet` 并触发一次**被中断的 `git gc/repack`**（留下 `maintenance.lock` + `bitmap-ref-tips_*`）⇒ **`8b59f7d` 之后的 7 个本地提交对象被清除**。判据：`git cat-file -t <sha>` → `fatal: Not a valid object name`（**对象真没了，不是「ref 丢了」**）；`git reflog` 只剩 3 条。`origin`(局域网 172.16.8.249) 当时不可达，`github/main` 恰好停在 `8b59f7d` 这个祖先节点。
   **纪律**：修正提交一律**新建提交**，不改写历史；要「并进某提交」就在**新提交**里改，或直接重做。**提交永远用显式文件列表** `git add <file>...`，**禁用 `git add -A`**（并发多 agent 时会裹进别人的半成品与草稿）。
   **恢复配方（内容没丢时可用）**：
   ① 先判对象是否还在：`git cat-file -t <每个丢失的 sha>`（全 `Not a valid object name` ⇒ 改写历史不可能，只能重建）；
   ② 内容是否还在工作树：`git status --short`（本次 33 个改动文件 = 7 个丢失提交的全部内容）；
   ③ **做「丢失提交 ↔ 工作树文件」映射**（用 `git show --stat` 的记忆/报告 + 按模块归属判断），然后**分组 `git add <显式列表>` + 新提交并按原提交边界重建**，提交信息里注明「重建提交：对象库事故后按工作树原样重建，内容无改动」；
   ④ ★**排除在途 worker 正在改的文件**（本次刻意未提交 `application.yml`/`*Properties.java`/`ModelKeyCodec.java`/`aios-common/pom.xml`/新目录 `aios-common/.../security/`，它们是另一个 worker 的半成品）——否则会把半成品固化进历史；
   ⑤ 收尾核对 `git fsck`（本次仅剩 1 个 dangling tree，干净）+ `git status --short | wc -l` 应只剩在途文件与草稿。
   **附带教训**：同时跑多个会 `git commit` 的 worker 时，index 是**共享单文件**——要求每个 worker 自带「提交前 `git log --oneline -3` 确认父提交」这一步。
25. **`agent/aios_ai/` 是 AI 能力的唯一归属地，依赖方向固定 `app → aios_ai`（单向）**：`aios_ai` 永不 `import app.*`；**只有 `aios_ai/graph/` 允许 import `langgraph`**；`agent/app/**` 除服务壳（`main.py` + 若干 `__init__.py`）外**一律是「只再导出、不含实现」的垫片**。判据 = `scripts/_check_aios_ai_boundary.py`（C1 反向 import / C2 langgraph 越界 / C3 app 纯 shim / C4 main.py 无旧业务导入 / C5 可导入）。**为什么要垫片而不是删**：同一类若有两份副本，**打在 A 副本上的补丁不作用于 B 副本** —— 实测 `test_echo_run_kb_citations` 就因 `patch(app.tools_client.ToolClient)` 修不了图里用的那个类而变红；单实现 ⇒ 补丁/类型/行为只有一份真值。**配套**：搬模块后**测试的补丁目标必须跟着搬**（见 27）。
26. **改 `aios_ai/graph/` 时：运行期对象绝不进图状态**（httpx 客户端 / `WallClock` / `ToolClient` 实例）。LangGraph 的 serde 会直接 `TypeError: Type is not msgpack serializable: <类名>`（实测踩到 `ToolClient`）。状态只放 dict / list / 原始类型；运行期对象在**节点内按需重建**（`_clock(state)` 由 `started_at: float`、`ToolClient.from_request(state["req"].user_token)`）。**checkpointer 由开关控制（`AIOS_HITL`，默认 false）**：关闭时不挂 —— 既有行为逐字节一致；开启时 `builder.graph()` 挂 `checkpoint.saver()`（本地内存 / 生产 Redis，见 29）。**另**：状态里 `req` 必须是 **dict**（`RunRequest.model_dump()`），节点内用 `nodes._req()` 还原 —— pydantic 实例会被 checkpointer serde 告警并「未来版本直接拦截」（见 29）。
28. **跑 agent 侧任何东西（pytest / 哨兵）必须显式用 `agent/.venv/Scripts/python.exe`**。本环境另有「托管默认 venv」`~/.workbuddy/binaries/python/envs/default`，**它没装 langgraph** ⇒ 图路径一 import 即 `ModuleNotFoundError: No module named 'langgraph'`，表现成「13 failed / 95 passed」，**看着像代码倒退、实为解释器选错**。判据：`git status` 无改动 + 失败点全是 `import langgraph` ⇒ 先换解释器，别改代码。正确调用：`./agent/.venv/Scripts/python.exe -m pytest tests/ -q`。
27. **给 AI 模块改名 / 搬模块后，测试与哨兵里的「补丁目标」必须跟着搬 —— 补丁要打在「该名字的查找处」（实现所在模块），补在再导出垫片上的别名对「内部调用」无效**。实例：`test_attachment_docs` 的 spy 必须改成 `patch("aios_ai.prompt.builder._neutralize_injection")`（补 `app.core.agent_runtime._neutralize_injection` 没用，因为 `build_messages` 读的是自己模块的全局名）；`scripts/_check_kb_toggle.py` 必须补 `aios_ai.graph.nodes.{gateway.resolve,ToolClient,_post_non_stream,settings}`（补 `app.core.agent_runtime.*` 到不了图）—— 该脚本已改为**双路径**（能 import `aios_ai.graph.nodes` 就补新目标，否则退回 legacy），以保住它的 `--selftest`。
29. **HITL 澄清链（`ask_user` → `need_clarification` → `resume`）已实装于 agent 内核**（2026-10-15 首轮）。入口 `aios_ai.entry.resume` / 门面 `facade.resume`；HTTP `POST /internal/v1/runs/{run_id}/resume`（`agent/app/main.py`）；契约 `ResumeRequest{answer, approval_id, decision, args_override}`。**四条不可回退的设计**：① **`clarify` 必须是独立节点** —— LangGraph `interrupt()` 恢复时**整个节点从头重跑**，中断若塞进 `tools` 节点，同轮已执行的工具会被**再执行一遍**（Q3 失败、副作用翻倍）；② **`need_clarification` 由 facade 在「观察到暂停」后发**，节点内发会因重跑而重复；③ **挂起存储按连接串可插拔**（`checkpoint.py`）：`（空）/memory` → InMemorySaver（**本地默认**）、`redis://` → AsyncRedisSaver（**生产**，须 **Redis Stack**）、`sqlite://` → AsyncSqliteSaver；④ **`AIOS_HITL` 是唯一开关**（默认 **false**，关闭时工具表/事件序列与既有逐字节一致）。**★ 实测坑**：本机 Redis 是 **3.0.504（Windows，无模块，无 `MODULE` 命令）** ⇒ `langgraph-checkpoint-redis` 必 `FT.INFO unknown command`；本地**不要**指向普通 Redis。判据哨兵 = `scripts/_verify_ask_user_hitl.py`（11 项：H0 路由 / H1 载荷 / H2 暂停不发 run.completed / H3 续跑完成 / **H4=Q3 工具不重跑** / H5 关开关不产事件）。
30. **改 `agent/aios_ai/**` 时新增任何 `settings.X` 读取，先查有没有哨兵把 `settings` 换成了精简 shim**。实例：加 `settings.agent_hitl` 后 `scripts/_check_kb_toggle.py` **整片红**（它把 `aios_ai.graph.nodes.settings` 换成只含 3 字段的 `class Shim` ⇒ AttributeError，表现为 A1.2/A1.4/A2.1-A2.5 失败，看着像 KB 功能坏了）。处置双管：① shim 补字段并加注；② 把该读取收口成 `getattr(settings, "X", <安全默认>)` 的**唯一判定点**（本项目已有 `nodes._hitl_enabled()`）。**别只改一边**。
