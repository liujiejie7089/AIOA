# AIOS 功能域要点（要点 + 唯一判定点）

> 由 `MEMORY.md §1` 拆分而来（2026-10-17，因主索引超过注入上限被截断）。
> 这里放「功能长什么样、判定点在哪」；**铁律与索引仍在 `MEMORY.md`**，故事在 `../YYYY-MM-DD.md`。

- **用户端双形态**：`docs/39` · **`user-client/_build_oa.py` 是唯一构建入口，产物 `index.html` 不可手改**
  （源：`_backup_index_pre_oa.html` + `_oa_app.js` + `_oa_markup.html` + `_oa_extra.css` + `_oa_polish.css`）。
- **OA 模块 = 43 个数字人 + 模块目录**：抽屉「OA 模块43」→ `#v-modules` → 点卡即 `oaPickWorker`（**复用唯一入口**）。
  **H5 状态全局是 `window.oaState`，不是 `window.S`**（`_oa_app.js:2581` 挂出）。
  收口 `scripts/_e2e_oa_modules.py`（K0–K6：43 卡逐点 + 43 次发送 + `--mutate`）；`_verify_oa_module_workers.py`（M1–M8）。
  V83 建 43 模板、V84 回填 `source_template_id`；后端唯一判定点 `support/WorkerProfile.java`。故事 `2026-10-17.md §一/§二`。
- **H5 弹层样式「永不匹配」陷阱**：弹层 `appendChild` 到 `document.body`，**不在 `.oa`(#oaRoot) 内** ⇒ `.oa .x{}` **永不匹配**
  （现象是「原生控件直出」，不是「没写样式」）；`--brand*` 只定义在 `.oa{}` ⇒ 弹层内 `var(--brand-*)` 无效。
  **修法**：弹层自带标记类（本仓 `.oa-dlg`）+ 自带品牌令牌；**绝不裸写** `.notif-modal`/`.note-err`/`.notif-foot .btn`（经典形态 10 处共用）。
  一条判据：`getComputedStyle(el).flexDirection`。详见 `2026-10-12.md §13`。
- **OA 扩展 + 数字人 + 自定义表单（`docs/52`，2026-10-17 已实装，§9 是状态权威）**：
  四域 Worker/Form/Invocation/DataFlow；表 `form_template`/`form_template_version`/`form_submission`/`worker_capability`（V85）
  + 43 模块种子（V86）+ 回执修正（V87）；权限码 `form:manage`/`worker:capability`。
  **`form_submission` 是唯一事实源**，`approval_order.form_data` 只存快照。
  链路：agent `request_form` → `need_form` 帧 → Java `RunService.buildNeedFormPayload` 用**表单库**补 fields → H5 `mountFormCard`
  → 提交 `POST /forms/{code}/submit` → 分流 `LEDGER`/`APPROVAL`/`RESUME` → `ApprovalOutcomeSink` 回写终态。
  **字段口径唯一判定点 `support/FormFieldMeta`**（`controlType` 三档、`label` = label→title→name）。
  故事 `2026-10-17.md §一~§三`。
- **请假意图自动判权 + 写工具硬闸（`docs/51`）**：`nodes.filter_intent_write_tools(tools, action)` —— **action 非空即剥 `apply_permission`**
  （确定性代码门）。泛化：**任何 action 意图 ⇒ 确认归 UI ⇒ 不下发写工具**；判据落在「模型真正收到的 tools 列表」。
- **AI agent 内核**：`agent/aios_ai/` 是 AI 唯一归属地（`app/**` 皆垫片）· `aios_ai/README.md`。
  HITL 开关 `AIOS_HITL`（默认 false）、`AIOS_CHECKPOINT_URL`（空=内存；生产=Redis，须 Stack）。
  入口 `POST /internal/v1/runs/{run_id}/resume`、门面 `facade.resume`、`_frame_type(payload)` 分 `need_clarification`/`need_form`。
  哨兵：`_verify_ask_user_hitl.py`、`_check_aios_ai_boundary.py`、`_check_hitl_resume_wire.py`、`_verify_h5_clarification.py`。
  三层贯通要点：`AgentRun.STATUS_WAITING_INPUT` + `RunService.proxyAgentRun/resume/markWaitingInput`；
  `completeRun` 最前面先判 `clarificationRef` 再 return（否则挂起 run 被误置 SUCCEEDED）；
  `subscribe` 必须在 replay 守卫**之前**拦 `WAITING_INPUT`（否则同 `thread_id` 覆盖断点、已跑工具重跑）。
- **多租户模型** `docs/38`（批次 A/B/C 完成，D/E 未开工）· **项目管理** `docs/40`（V71，模块 `aios-project`）
- **代码仓库全流程（V48）夹具**：租户「某某智能科技有限公司」(`MYQY-DEMO`) + `znkj*` 账号，**不在 Flyway**，由脚本造。
- **缺陷台账** `docs/42`（可复跑判据 + 处置三态）· **四项需求** `docs/44`（§3 上传 500 / §4 参数漂移已修）
- **对话内上传 / 语音** `docs/46`（规格）· `docs/47`（简化版已实装：音频原始字节直传；造语音取证只能本地 piper，缓存 `%TEMP%/piper_zh/`）
- **管理端 SSE**：`web/apps/shell/src/api/runs.ts`，终态帧后断流**不是**失败（`StreamEndedAfterCompletion`），**不能只 `return`**
- **知识库开关 `kb_on`**：H5 `createRun` 提到 body 顶层 → Java 透传 → agent 消费
- **回答口径**：唯一事实源 `agent/aios_ai/prompt/answer.py::rules()`（改口径只改这里）
- **仓库联动 Gitee/Gitea**：管理端可配字段只在端口 `RepoProviderSettings` 判定，客户端不得直读 `*Properties`；
  收口 `scripts/_check_gitee_platform_config.py`（静态 12 + `--selftest` 12）。详见 `repo-provider-gitea.md`。
- **数字人→自定义表单（三道闸，2026-10-18 定稿）**：
  闸① 派发时按 `worker_capability` 收窄 `available_forms`；闸② `RunService.buildNeedFormPayload` 出口校验；
  闸③ **确定性开表**：判定只在 Java 一处（`RunService.shouldOpenSingleForm` 纯函数：userText 含 taskName/taskCode）
  → `AgentRunRequest.form_hint` → agent `nodes.agent` 造 `request_form` 控制调用 → `clarify.interrupt()`。
  ★**执行必须在 agent 图里**：只在 Java 流末补一帧 `need_form` = 没有 checkpoint，用户提交后 `/resume` 零帧（假通过）。
  普查 `scripts/_verify_worker_form_routing.py`（tenant3 = **43 PASS / 0 CLARIFY / 4 NO_CAP（86–89）/ 0 FAIL**；
  12 个租户的 capability 指纹 md5 全同 ⇒ 单一租户普查可代表 516 个数字人）；
  续跑 `scripts/_verify_form_resume_no_reopen.py`（U1 首发开表 / U2 resume 200 / U3 续跑不再弹 / U5 问候不误触发）。
- **B-1 服务间令牌（2026-10-18 补上，此前 `/internal/v1/*` 零鉴权）**：
  agent `app/main.py` 中间件 `_require_service_jwt` 按**路径前缀**拦（新增内部端点自动受保护）；
  实现 `aios_ai/security/service_jwt.py`（标准库 HS256，**钉死 alg** 拒 `none`/alg-confusion、`compare_digest`、
  `exp` 必填、`svc ∈ {agent,server}`；空密钥**失败关闭**）。
  Java 侧全部调用方都要带票：`RunService`（runs/resume/tasks，WebClient）、`WorkerIntakeService`（降级分支会把 401
  当成「agent 不可达」而**静默改走本地推断**，故漏票不报错、只退化）、`WorkerScheduleService`、`KpiInsightService`、
  `AsrController`、`ModelConfigService`。判据 `agent/tests/test_internal_auth.py`（A1 无票/A2 格式错/A3 alg=none/
  A4 过期/A5 错密钥 均 401；A6 合规票 200；A7 `/health` 不被连带）；活体判据 = 无票直打 401、走
  `POST /api/v1/workers/intent` 回 `source=agent`（**降级时是 `local-fallback`**，这才是判别点）。脚本侧 `scripts/_svc_token.py`。
  部署口径：compose 的 **agent 容器变量名必须是 `SERVICE_JWT_SECRET`**（agent 读这个名字；Java 读 `AIOS_SERVICE_JWT_SECRET`），
  写错名字 = 生产必 401。
- **B-3 知识库静默降级**：`ToolClient.list_tools()` 失败时记 `self.list_error`，`prepare()` 据此注入 `KB_DEGRADED_NOTE`
  并置 `kbDegraded`，不再把「工具表拉不到」等同于「用户没有工具」（后者会让 KB 预检索被跳过、run 仍 SUCCESS）。
