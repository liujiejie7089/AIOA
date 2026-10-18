# 50 · Agent 框架选型对比：LangGraph vs 阿里 AgentScope 2.0

> 结论面向决策：**是否更换 agent 执行内核**、**换成哪一个**、**代价多大**、**先做什么**。
> 事实核实时间：2026-10-15。所有对本仓库的描述均带 `文件:行号`；所有对框架的描述均标注来源与核实日期（框架资料一年一变，不凭记忆）。

---

## 0. 结论先行

**建议：采用 LangGraph，但限定在一个文件的范围。不选 AgentScope 2.0 作首选，列为备选 + 试点对象。**

三条决定性理由：

1. **这不是一次新决策，而是回归已批准的架构。** `docs/01-架构设计.md` 本就写明 L4 = `aios-agent (Python：FastAPI + LangGraph)`（第 30 行），技术选型表也写明 `Agent | FastAPI + LangGraph（pin 0.2.x），core/runtime.py 门面隔离`（第 49 行），并预留了「LangGraph 不可用时只换 graph 实现」。**当前的自研循环（`agent/app/core/agent_runtime.py`）是对该设计的偏离**，不是相反。

2. **本次要的能力，契约和状态机早已冻结，只差实现。** 用户举例的 `ask_user` 澄清卡 = 「持久化暂停 + 结构化中断 + 恢复」，而 `docs/04-接口契约/internal-agent.yaml` 已定义 `need_clarification { question, suggested_options }`（第 133 行）与 `POST /internal/v1/runs/{id}/resume`（第 46-70 行）；`docs/01-架构设计.md` 第 69 行甚至已写完 HITL 状态机（`RUNNING → WAITING_APPROVAL → …`）、`LangGraph interrupt + checkpointer（thread_id=conversation_id，重启不丢）`、`args_hash` 校验、`args_override`。**要做的是「把设计做出来」，不是「选一个框架来设计」。**

3. **LangGraph 是低层框架，爆炸半径最小；AgentScope 是平台级框架，会与我们已自研的能力正面重叠。** 三条铁律之第 1 条是「**SSE 走 Java 中转，不直连 Python**……agent 实现可替换」（`docs/01-架构设计.md` 第 38 行）。LangGraph 不接管模型调用，我们自研的 `model_gateway`（OpenAI 兼容 + 管理端热加载 + 三级降级）、知识库检索、Java 工具网关、SSE 事件契约**全部保留**；AgentScope 自带 Agent Service（REST+SSE 托管、多租户、会话持久化）、RAG、长期记忆，这些**我们都已经有**，接入它等于把已有资产对着一份外来实现做重复建设。

**但不建议直接全量推进**：先做 §7 的 2 周时间盒试点，用可执行判据验证「LangGraph 真的解决了 ask_user 这条链」，再决定是否扩大。

---

## 1. 事实基线：现在的 agent 到底弱在哪

### 1.1 架构事实（先破除一个误解）

| 事实 | 证据 |
|---|---|
| agent 模块共 **3460 行** Python | `find agent/app -name '*.py' \| xargs wc -l` |
| **零 agent 框架依赖** | `agent/pyproject.toml:10-22` 仅 fastapi / uvicorn / pydantic / pyyaml / httpx / pytest / faster-whisper / av |
| 运行时门面极薄（29 行），按 provider 二选一 | `agent/app/core/runtime.py:21-29` |
| 真正的循环是**单文件 707 行** | `agent/app/core/agent_runtime.py`（最长文件） |
| **Python 侧完全无状态**：历史由 Java 注入 | `agent/app/schemas.py:57` 的 `history`；`RunService.java:106` `HISTORY_TURNS = 10` |
| 工具**不在 Python 声明**，实时从 Java 拉 | `agent/tools_client.py:61` `list_tools()` → GET Java `/api/v1/tools` |
| 循环轮数硬上限 4 | `agent/tools_client.py:20` `MAX_TOOL_ROUNDS = 4` |

**关键判断：当前不是「用了弱框架」，而是「没用框架，自己写了个薄循环」。** 所以「换框架」的准确含义是：**把一个自研的 700 行循环换成框架的图/事件循环**。这既降低了迁移的连带风险（耦合面小），也意味着**能力缺口不是因为框架弱，而是因为当初没按设计落地**。

### 1.2 缺陷清单（与用户举的例子逐条对齐）

| # | 缺陷 | 证据 | 用户举的 `ask_user` 例子是否命中 |
|---|---|---|---|
| 1 | **无 ask_user / 澄清 / 中断 / 恢复** | 项目代码（`agent/app` + `agent/tests`）对 `ask_user\|need_clarification\|clarif\|interrupt\|resume\|checkpoint` **0 命中**（注：`grep -rn agent/` 的 13 处同名命中**全部**位于 `.venv/Lib/site-packages/` 的第三方库文档字符串，与本项目无关，勿误读为「已实现」） | ✅ **正是此例** |
| 2 | 无断点 / checkpoint，取消是桩 | `RunService.java:455-456` 注释自述「真实中断 M2 实现」；`cancel()` 只置 `CANCELLED` | ✅ |
| 3 | 无结构化输出约束（表单 JSON 无 schema 校验） | 全目录无 `structured`/`response_format` 相关实现 | ✅ |
| 4 | 无长期记忆 | 架构仅「留表」（`docs/01` 第 70 行 `agent_memory 仅留表`） | — |
| 5 | **无可观测**（无 OTel、无指标端点） | `agent/app/main.py:112` 仅 `/internal/v1/models` 状态观测 | — |
| 6 | 无多智能体「模型决策」执行 | 契约有 `run.plan`/`run.step`/`agent.switched`（`internal-agent.yaml:124-126`）但未实现；`multi_task.py` 是**无 LLM 的显式计划**，与模型决策无关 | — |
| 7 | 无反思 / 重试；上游错即整轮失败 | `agent/app/core/agent_runtime.py:612-623` 上游非 200 → `error` + `run.failed` 直接收口 | — |
| 8 | 沙箱是轻量实现 | `agent/app/tools/sandbox.py`（182 行，非容器隔离） | — |

### 1.3 契约里已冻结、但没实现的能力（这是本次真正的杠杆）

`docs/04-接口契约/internal-agent.yaml` 已写死但未实现的：

| 契约项 | 位置 | 状态 |
|---|---|---|
| `POST /internal/v1/runs/{runId}/resume`（含 `approval_id` / `decision` / `args_override`） | 第 46-70 行 | ✅ **已实现**（澄清形态）：agent `app/main.py` + Java `RunController` 转发；`approval_id`/`args_override`（审批形态）仍未用 |
| `need_clarification: { question, suggested_options }` | 第 133 行 | ✅ **已实现**（用户要的单选表单）：agent 门面发事件 → Java `EVENT_NEED_CLARIFICATION` 透传 + `AgentRun.WAITING_INPUT` → H5 `.clar-card` 单选卡回填 |
| `approval.required` / `approval.resolved` | 第 129-130 行 | 未实现（但 Java 侧有演示级替代，见 1.4） |
| `run.plan` / `run.step` / `agent.switched` | 第 124-126 行 | 未实现 |
| `citation`（M4） | 第 132 行 | 未实现 |
| `ping` 心跳 / `Last-Event-ID` 续传 | 第 121 行 | Java 侧已实现（`RunService.java:241-243`） |

**含义：`suggested_options` 这个字段名，就是用户描述里「标准化单选表单」的落地位置。契约已经替我们定好了数据形状。**

### 1.4 一个容易被忽略的既有先例（H5 已有卡片渲染雏形）

Java 侧**已经在发卡片事件**：`RunService.java:722-724` 在 `message.completed` 后，若回答文本命中「对外发布场景」关键词，就发一个 `approval.required` 事件，载荷由 `approvalCardJson()`（`:918-929`）生成（`title`/`bizType`/`scenario`/`reason`）。

这是**演示级启发式**（用关键词命中冒充风险判定，不是真 HITL），但它证明了两件事：
- **H5 侧已有「卡片」事件通道可复用**（前端认识 `approval.required` 这个事件名）；
- 真实 HITL 要替换的正是这段启发式 —— 判定应从「回答文本关键词」上移到「工具调用的风险等级」（架构里 `risk_level` 字段早已定义，`docs/01` 第 59 行）。

---

## 2. 候选框架事实卡（2026-10-15 核实）

### 2.1 LangGraph

| 项 | 事实 |
|---|---|
| 归属 | LangChain Inc.（2026 估值 12.5 亿美元） |
| 许可 | **MIT**（可自由商用） |
| 版本 | 1.0 GA 2025-10-22；截至 2026-05 已到 **1.2** |
| Python 要求 | **>= 3.10**（本环境 3.13.14，满足） |
| 定位 | **低层编排 runtime**：不包装模型调用，可与 LangChain 分离使用 |
| 核心原语 | `StateGraph`（节点/边/条件边）、`checkpointer`、`interrupt()` + `Command(resume=)`、`interrupt_before/after`、`Store`（长期记忆） |
| 持久化 | InMemory（仅演示）/ **SqliteSaver / PostgresSaver / RedisSaver** |
| 关键能力 | 持久化执行（durable execution）、时间旅行、流式多模式、HITL 首选级支持、子图/supervisor 多智能体 |
| 部署 | LangSmith Deployment（原 LangGraph Platform）：Cloud（Plus/Enterprise）/ Hybrid（Enterprise）/ 全自托管（Enterprise）；Developer 免费档自托管 ≤10 万节点/月 |
| 生态规模 | 月下载约 **3450 万**；仓库约 3.1-3.5 万 star |
| **已知摩擦（第三方复现，非本文推测）** | ① 学习曲线陡，团队常花 2-3 周才能上手；② **每个节点转换 = 一次 checkpoint 写库**，高频图会变成延迟瓶颈；③ state 会静默膨胀直至撑爆上下文，需自行做剪枝；④ 恢复时**节点会重跑**，副作用必须幂等（需包 Task）；⑤ 条件边返回未注册的 key 会在**运行中**（已花掉 token 后）抛错；⑥ **无原生 MCP server**；⑦ 重试/降级/可观测/CI 都要外部系统，框架只管 runtime |

### 2.2 阿里 AgentScope 2.0

| 项 | 事实 |
|---|---|
| 归属 | 阿里巴巴通义实验室 |
| 许可 | **Apache-2.0**（可自由商用） |
| 版本 | **2.0 为破坏性升级，2026-05 发布**（当前文档 2.0.3）；与 1.0 **不兼容，且不提供自动迁移路径** |
| Python 要求 | **>= 3.11**（本环境 3.13.14，满足） |
| 定位 | **平台级**：SDK + 模型集成 + 工具 + 上下文管理 + 权限 + 可选 Agent Service + 前端 UI |
| 核心原语 | 统一 `Agent` 类（`reply()` / `reply_stream()`）、**类型化事件流**、`Toolkit`（Python 工具 + MCP）、`Workspace`、`Permission`、`Offloader`、middleware |
| **HITL** | **原生**：Permission 可对工具调用 `allow / deny / request confirmation`；HITL 事件向应用投递审批请求并回收决策；支持中断（interruption）并在暂停处**精确恢复** |
| 结构化输出 | **原生**：`structured_schema`（Pydantic）→ `structured_output`，框架负责校验；官方文档明确提到「reply 因人工输入暂停时的行为」 |
| 沙箱 | **原生**：`LocalWorkspace` / `DockerWorkspace` / `E2BWorkspace`，同一份 agent 代码可无改切换；并托管 MCP server 生命周期、skill、上下文卸载 |
| **Agent Service** | REST + SSE 托管任意 agent；**多租户、多 Session 并发、可续传流、持久化会话、定时任务、凭据管理** |
| 多智能体 | `Agent Team`：leader 在运行时动态创建 worker（每个 worker 独立 session），无需预定义 worker 类型 |
| 可观测 | 内置 **OpenTelemetry**（由 middleware 实现）；配套 Studio 可视化调试 |
| 生态 | Studio / ReMe（记忆）/ OpenJudge（50+ 评判器）/ Trinity-RFT（微调）/ Mem0 集成 |
| 多语言 | **Python / TypeScript / Java（`agentscope-java`）三套独立实现** |
| 规模 | 约 2.7-3.0 万 star，40 个 release |
| **已知摩擦** | ① 2.0 破坏性升级、**无自动迁移**；② 生态（第三方集成、教程、案例）**明显小于 LangChain/LangGraph**；③ **RAG 与长期记忆口径不一致**：官方 FAQ（2026-09-10）称已可用，但多篇解析指出这两块仍在 1.0→2.0 迁移、后续版本才陆续上线 —— **属须在试点中核实的不确定项**；④ 「热度 ≠ 成熟度」，企业级长期维护案例尚少 |

---

## 3. 四维度对比

### 3.1 能力匹配度

| 我们要的能力 | 本项目现状 | LangGraph | AgentScope 2.0 | 更优 |
|---|---|---|---|---|
| 工具调用循环 | 有（自研，上限 4 轮） | ✔ 图/节点 | ✔ 事件流 | 持平 |
| **澄清 / ask_user 暂停-回填** | **无** | ✔✔ `interrupt()` + checkpointer + `Command(resume=)`，最成熟 | ✔✔ Permission+confirmation+interruption，**原生且更直白** | 平（AS 略直白） |
| **结构化表单输出** | **无校验** | ✔ `with_structured_output` | ✔✔ `structured_schema` 原生，且文档覆盖「暂停时」行为 | AS |
| 持久化 / 断点续跑 | 无（Python 无状态） | ✔✔ checkpointer 生态（Postgres/Redis/Sqlite） | ✔（依赖 Agent Service 的会话持久化） | LG |
| 多智能体 | 无（模型决策层） | ✔✔ 子图/supervisor，生产案例最多 | ✔✔ Agent Team leader-worker | 平 |
| 可观测 | **无** | ✔（LangSmith，商业/按席位） | ✔✔ OTel 内置 + Studio，**免费** | AS |
| 沙箱 | 轻量自研 | ✖ 无内置 | ✔✔ Local/Docker/E2B | AS |
| 长期记忆 | 仅留表 | ✔✔ Store | ✔✔ ReMe/Mem0 | 平 |
| RAG | **我们已有**（Milvus+MySQL，`docs/32`） | ✔ 生态丰富 | ⚠ 2.0 迁移中，口径待核 | LG（且我们用不上外来 RAG） |
| 模型无关 | 自研 model_gateway | ✔ | ✔（OpenAI/DashScope/Ollama 等） | 平 |

**小结**：AgentScope 在「HITL 直白度、结构化输出、可观测免集成、沙箱」上领先；LangGraph 在「持久化底座成熟度、多智能体生产验证、与我们已经自研部分的**不重叠**」上领先。

### 3.2 迁移与改造成本

| 维度 | LangGraph | AgentScope 2.0 |
|---|---|---|
| 需要改写的**核心** | `agent_runtime.py` 的 run 循环（707 行） | 同左 |
| 模型调用 | **保留**自研 `model_gateway`（LD 低层，不接管模型调用） | 倾向改用其 model 类；与我们的热加载/三级降级**重叠**，需适配或替换 |
| 工具 | 保留 `tools_client`（HTTP 拉 Java 工具），加一层适配器即可 | 需接入其 `Toolkit`；与 Java 工具网关**重叠** |
| 知识库 | **保留**（自研检索） | 其 RAG 与我们重叠，且 2.0 迁移中 → 应保留自研，则其 RAG 收益为 0 |
| SSE / 事件 | **保留**（契约已冻结，Java 侧几乎不用改） | 其 Agent Service 自带 REST+SSE，会**诱发绕过 Java 中转**，与铁律 1 冲突 |
| 事件映射 | 需把图事件映射到既有 16 类事件（`internal-agent.yaml:122-138`） | 需把其类型化事件映射到同一套契约（映射面更大） |
| 新增基础设施 | **需一个 checkpointer 存储**（见 §9 未决项） | 若用 Agent Service，需多跑一个服务 |
| 学习曲线 | 高（2-3 周，图/状态/条件边/序列化） | 中（概念多：事件流/Workspace/Permission/Runtime，但语义更贴近「生产设施」） |
| 官方文档语言 | 英文为主 | **中文 + 英文**（本团队友好） |

**小结**：**两者「重写循环」的代价相当**；差异在于**非循环部分** —— LangGraph 允许我们几乎原样保留自研栈，AgentScope 会引入与我们重叠的平台层。故 LangGraph 的**净改造量更小**。

### 3.3 长期维护与生态

| 维度 | LangGraph | AgentScope 2.0 |
|---|---|---|
| 许可 | MIT | Apache-2.0（两者均宽松） |
| 版本稳定性 | 1.0 承诺到 2.0 前无破坏性变更；已到 1.2 | **2.0 刚破坏性升级（2026-05），后续仍有演进风险** |
| 生产案例 | Uber/LinkedIn/Klarna/JPMorgan/BlackRock/Cisco 等 | 企业级案例尚少，多为解析与试用 |
| 社区 / 第三方 | 最大（月下载 3450 万） | 明显较小，MCP 生态仍在适配 |
| 组织背书 | LangChain Inc.（融资 2.6 亿美元） | 阿里巴巴通义实验室 |
| 中文支持 | 一般（中文资料靠社区） | **强（官方中文文档）** |
| 人才/招聘 | 市场供给最大 | 供给较少 |
| **锁定期权** | 深用后迁出成本高（条件边/状态/checkpointer 需重写） | 同样存在（2.0 与 1.0 已不兼容，证明其自身迁移也不便宜） |

**小结**：LangGraph 在**成熟度、案例、人才供给**上占优；AgentScope 在**中文文档、阿里生态对齐**上占优。对「地级市政务平台」这类需要长期可维护、可招人接手、可审计的项目，**成熟度权重更高**。

### 3.4 性能与稳定性风险

| 维度 | LangGraph | AgentScope 2.0 |
|---|---|---|
| 主要性能风险 | **每节点一次 checkpoint 写库**；state 静默膨胀撑爆上下文；恢复时节点重跑（需幂等） | 相对轻（事件流 + 内置 Offloader 卸载超大工具结果/压缩上下文） |
| 主要稳定性风险 | 条件边误路由在**运行中**抛错（此时已消耗 token）；checkpoint 需自建 TTL 清理，否则存储膨胀 | **年轻**：2.0 破坏性、生态小、RAG/记忆迁移未定 → 缺陷类型「未知」 |
| 运维面 | 需 checkpointer 存储 + 外部可观测（LangSmith 或自建） | OTel 内置；但若用 Agent Service 则多一个服务 |
| 与本项目栈的冲突 | **栈内只有 MySQL8 / Redis7 / MinIO（`docs/01` 第 32、55 行），无 Postgres** → checkpointer 需选 Redis 或补 Postgres | 无存储冲突 |

**小结**：LangGraph 的风险是**已知、有文档、可缓解**，且**主要是运维面的**（跑一个 checkpointer 存储 + 可观测）；AgentScope 的风险是**未知/未成熟**。对政务平台的稳定性取向，**「已知可管」优于「年轻未知」**。

### 3.5 加权汇总（权重为本项目定制）

| 维度 | 权重 | 理由 | LangGraph | AgentScope 2.0 |
|---|---|---|---|---|
| 能力匹配度 | 25% | 决定能不能解决问题 | 8.5 | 9.0 |
| 迁移与改造成本（净） | 25% | 与自研栈重叠越多，净成本越高 | 8.5 | 6.5 |
| 长期维护与生态 | 25% | 政务项目要长期可维护、可招人 | 9.0 | 7.0 |
| 性能与稳定性风险 | 25% | 稳定性优先于极致性能 | 7.5 | 6.5 |
| **加权** | | | **8.38** | **7.25** |

（评分 10 分制，为本项目场景的主观工程判断，非厂商数据。）

---

## 4. 迁移爆炸半径：换的到底是什么

| 文件 / 资产 | 换框架后是否重写 | 理由 |
|---|---|---|
| `agent/app/core/agent_runtime.py`（707 行） | **重写** | 这正是「循环」本身，是唯一被替换的对象 |
| `agent/app/core/runtime.py`（29 行） | 小改 | 已设计为门面；新增一个 graph 分支 + 开关 |
| `agent/app/core/echo_runtime.py`（142 行） | 不动 | 回声路径与框架无关 |
| `agent/app/core/answer_shape.py`（199 行） | 不动 | 提示词规则，与框架无关 |
| `agent/app/core/events.py` · `guards.py` | 不动 | SSE 渲染与护栏，是契约层 |
| `agent/app/core/multi_task.py` · `orchestrator.py` | 不动（后续可迁到子图） | 显式计划执行，独立于对话 run |
| `agent/app/model_gateway/**`（~380 行） | 不动 | **低层框架不接管模型调用** |
| `agent/app/tools_client.py` · `tools/**` | 加适配器 | 把 Java 工具 schema 包成框架的 tool 即可 |
| `agent/app/asr/**`（~280 行） | 不动 | 语音链路独立 |
| `agent/app/main.py`（285 行） | 小改 | 新增 `runs/{id}/resume` 端点 |
| Java `RunService.java` | **小改** | 事件常量表（`:70-75`）需补 `need_clarification` 等；新增 resume 转发 |
| Java `AgentRun` 状态机 | 小改 | 新增 `WAITING_INPUT`（架构已设计 `WAITING_APPROVAL`） |
| H5 `user-client/index.html` | 小改 | **复用 `approval.required` 卡片通道**（§1.4），新增单选表单渲染 |
| `docs/04-接口契约/internal-agent.yaml` | 不改 | **契约早已预留** |

**结论：约 700 行核心 + 1 个适配器 + 少量映射；其余 ~2750 行 agent 代码和几乎所有 Java/H5 契约**不动**。这是「限定范围的替换」，不是「重写 agent 服务」。**

---

## 5. 明确选型建议

### 5.1 首选：LangGraph（范围限定）

**做什么**：把 `agent/app/core/agent_runtime.py` 的循环改为 LangGraph 图，挂在 `core/runtime.py` 门面后，用开关控制新旧路径并存。

**为什么**：
1. 回归已批准架构（`docs/01` 第 30/49 行），且原设计就是为这份需求（interrupt + checkpointer + HITL 状态机）准备的；
2. 低层框架 → **保住自研 model_gateway / 知识库 / 工具网关 / SSE 契约**，净改造量最小；
3. 1.0+ 稳定、MIT、生产案例最多、人才最好招；
4. 风险已知可管（§3.4）。

**明确不做**：不重写 echo 路径、不动 `answer_shape`/`events`/`guards`、不动 Java 侧 SSE 契约。

### 5.2 备选：AgentScope 2.0 —— 满足以下**任一**条件时改选它

- 组织决定**长期绑定阿里/通义生态**（Qwen、DashScope 已是我们的 provider 之一），且希望官方中文支持与阿里背书；
- 团队希望**少写基础设施**：直接要内置的 Permission/HITL/结构化输出/OTel/沙箱，接受用其 Agent Service 承担服务层（**此时需重新审视铁律「SSE 走 Java 中转」**）；
- 试点证明 AgentScope 的 `structured_schema` + Permission confirmation **显著**比 LangGraph 方案省工（用 §7 的试点同时量一次）。

### 5.3 第三选项（必须诚实列出）：不引框架，自研中断-恢复

把 `ask_user` 实现为：`ask_user` 工具 → 命中即产出 `need_clarification` 事件并**结束本轮 run**（不挂起）→ Java 落 `WAITING_INPUT` → 用户选择后**以新 run 续跑**，把「问题的答案」作为额外上下文注入。

- **优点**：零新依赖、零新基础设施、保持 Python 无状态（符合现有铁律）、无锁定、契合「agent 可替换」。
- **代价**：**对话中间态无法精确恢复**（当前循环的多轮工具结果不在 Java 侧，续跑即丢失中间推理），只能做「重放 + 追加答案」的近似语义；持久化执行的正确性（重放/幂等/并发恢复）要我们**永久自担**。
- **何时选它**：若 §7 试点证明「澄清只需单轮往返、不需要保留中间态」，则 C 的语义足够，此时**C 是性价比最高的解**。

**这是本次分析中最重要的一个「不该被跳过」的选项**：用户的痛点是「澄清」，不必然是「durable execution」。若澄清只是「问一句、答一句、继续」，那么引框架可能属于**为解决 20% 的问题引入 80% 的复杂度**。

---

## 6. 分阶段路线（若采纳 LangGraph）

| 阶段 | 内容 | 出口判据 |
|---|---|---|
| **P0 契约补齐**（与试点并行） | 补 `need_clarification` / `runs/{id}/resume` / `approval.*` 的事件常量与 Java 侧状态 `WAITING_INPUT` | ✅ 澄清链两项 + `WAITING_INPUT` **已交付**（2026-10-16，见 §7 落地状态）；`approval.*` 仍未做 |
| **P1 单点突破**（试点，见 §7） | LangGraph 图跑通「工具循环 + ask_user 中断 + resume」，门面后开关控制 | §7 的 5 条判据全绿 |
| **P2 多智能体** | planner → 域子 agent → 汇总，落 `run.plan`/`run.step`/`agent.switched` | 契约事件真实产出；失败有终态 |
| **P3 记忆与可观测** | checkpointer 长期化 + OTel/指标 | 会话跨天可续；有指标端点 |

---

## 7. 先做的验证性试点（2 周时间盒）

**目标**：端到端跑通用户描述的那条链，**并在门面后**，同时量与基线 C 的差异。

**试点交付**：
1. LangGraph 图替换 `agent_runtime.run()`（开关控制，echo 路径不受影响）；
2. `ask_user` 工具：入参 `question` + `options[]`（复用契约的 `suggested_options`），触发 `interrupt()`；
3. agent 侧产出 `need_clarification` 事件（含 `suggested_options`）；
4. Java 侧 `POST /internal/v1/runs/{id}/resume` 转发 + `AgentRun` 置 `WAITING_INPUT`；
5. H5 渲染单选卡（复用 `approval.required` 通道）→ 回填 → `Command(resume=...)` 续跑。

**验收判据（可执行，非「感觉好了」）**：
- **Q1 中断可达**：模型对「帮我处理一下」这类模糊输入，真实调用 `ask_user` 并产出 `need_clarification`（抓 SSE 帧断言，不是看 UI）；
- **Q2 真挂起**：run 状态落 `WAITING_INPUT`，且**进程重启后**仍能 resume（这是与基线 C 的分水岭）；
- **Q3 精确恢复**：resume 后**不重跑**已完成的工具调用（用工具网关的调用日志计数断言，防副作用重复）；
- **Q4 契约不破**：既有 SSE 契约回归全绿（`scripts/_check_kb_toggle.py`、`_check_answer_kb_strict.py` 等既有哨兵 0 失败）；
- **Q5 与 C 的对比量**：记录「澄清一轮的端到端耗时 / 代码行数 / 新增基础设施项 / 需自维护的持久化逻辑行数」——**四个数字**，作为扩大与否的依据。

### 落地状态（2026-10-16）

三层已实装。**Q1/Q3/Q4 有可复跑哨兵；Q2 只在生产 Redis 下成立**（本地内存 checkpointer 进程重启即丢断点）。

| 层 | 落点 | 证据（可复跑） |
|---|---|---|
| agent 内核 | `aios_ai/tools/ask_user.py`、`graph/nodes.py::clarify`、`graph/facade.py`（`_pause_events`/`resume`）、`graph/checkpoint.py`、`app/main.py::resume_run` | `scripts/_verify_ask_user_hitl.py` 11/11（含 **Q3**：已完成的工具调用计数=1；HITL 关闭时无 `need_clarification`）；`agent/tests/test_aios_ai_hitl.py` |
| Java 后端 | `AgentRun.STATUS_WAITING_INPUT`；`RunService` 的 `proxyAgentRun`/`resume`/`markWaitingInput`/`waitingInputNotice`；`RunController` `POST /api/v1/runs/{runId}/resume` | `scripts/_check_hitl_resume_wire.py` 7/7（含负向对照）；`./mvnw -q -pl aios-chat -am -DskipTests compile` EXIT=0 |
| H5 用户端 | `_backup_index_pre_oa.html`（`_sse` / `resumeStream` / `clarCardHtml` / `mountClarCard` / `cancelClarCard` + 经典 `send()` 回填循环）、`_oa_app.js`（OA `oaSend()`） | `scripts/_verify_h5_clarification.py`（拦截真实请求体 + 合成 SSE：OA 与经典各 N0–N8、三层线格式 L1–L10，0 失败；N8 为负向对照）；回归 `scripts/_e2e_oa.py` 105/106（唯一 FAIL 是 `/api/v1/asr/status` 401，与澄清链无关） |

**与 §8 未决项 8 的关系（口径未统一）**：`need_clarification` 与 `approval.required` **仍是两条独立链路**，未合并进同一状态机。澄清走 agent 的 `interrupt()`/`resume`（真挂起、断点可续）；审批仍是 Java 侧关键词启发式（`RunService.approvalCardJson`，演示级）。统一留待审批形态（M3）落地时再做，避免为演示级启发式引入真实 HITL 语义。

**本轮未验证（如实记录）**：未在真机跑通「新 Java + `AIOS_HITL=true` + 模型真实调用 `ask_user`」的整链闭环（`:8080` 上部署的是改动前的进程，Java 无热加载），故 Java 侧「暂停 → `WAITING_INPUT` → resume」的**运行时**行为仅由读码 + 编译 + 静态哨兵佐证；H5 行为由网络拦截 + 合成 SSE 验证（未走真实模型推理）。

**试点不通过时的判据**：若 Q2 无法在 2 周内达成或 Q3 反复失败（幂等模型没设计好），即为「LangGraph 的持久化收益未兑现」的**负向证据**，应转方案 C。

---

## 8. 风险与未决问题

| # | 风险 / 未决项 | 影响 | 处置 |
|---|---|---|---|
| 1 | **checkpointer 存储选型**：栈内只有 MySQL8/Redis7/MinIO（`docs/01` 第 32、55 行），**无 Postgres**；LangGraph 生产级 checkpointer 官方首选 Postgres | 阻塞 P1 | 试点中优先验证 **Redis checkpointer**（Redis 已在栈内）；若不可靠，评估补 Postgres 的运维代价 |
| 2 | **每节点 checkpoint 写库**的延迟 | 首字延迟与吞吐 | 只在「有意义的重启点」checkpoint（如工具调用后、interrupt 前），不要每节点都写 |
| 3 | **state 膨胀撑爆上下文** | token 成本与失败率 | 复用 AgentScope 的「Offloader」思路自建：工具结果入库 + 只回灌摘要 |
| 4 | **恢复时节点重跑**的副作用重复 | **真实业务影响**（重复调用业务系统） | 写操作必须带幂等键（架构第 59 行 `idempotency_required` 已有设计）+ Q3 断言 |
| 5 | LangGraph 版本漂移 | 升级破坏 | 架构已写「pin 版本 + 门面」（`docs/01` 第 99 行）；门面已存在，继续 pin |
| 6 | AgentScope 2.0 的 RAG/记忆成熟度口径不一致 | 若改选 AS，影响其收益评估 | 列为 AS 选型的**待核项**；试点时一并验证 |
| 7 | 团队学习曲线（2-3 周） | 交付节奏 | 限范围 + 门面隔离，避免全团队被拖入 |
| 8 | **未决的产品口径**：`need_clarification` 与 `approval.required` 是**两条独立链路**还是**统一到一个 HITL 状态机**？ | 影响 Java 状态机与 H5 组件数量 | 建议**统一**：都是「暂停等人」，只是触发源不同（模型澄清 vs 工具风险）；待定实现前先定口径 |

---

## 9. 一页话总结

- **痛点是真的**：当前 agent 确实没有澄清/中断/恢复，且**契约与状态机早已设计完**（`internal-agent.yaml`、`docs/01` 第 69 行），只是没落地。
- **但它不是「框架选弱了」**：agent 模块压根没用框架（`agent/pyproject.toml` 无 any framework 依赖），是一个 707 行的自研循环。
- **两个框架都能补这个洞**：LangGraph 用 `interrupt()` + checkpointer；AgentScope 用 Permission confirmation + interruption。能力上都够。
- **差别在改造成本与成熟度**：LangGraph 是低层 → 保住自研栈，净改造量小、成熟度最高；AgentScope 是平台 → 与我们的模型网关/知识库/工具网关/SSE 契约重叠，且 2.0 年轻。
- **推荐**：限定范围用 **LangGraph**；**先跑 2 周试点**（§7 的 Q1-Q5），并在试点中**同时量基线 C**，用数字决定是否扩大。
- **不要跳过的选项**：若澄清只需单轮往返，**方案 C（不引框架）**可能才是性价比最高的解 —— 引框架的本质是用「持久化执行」换「澄清能力」，只有当澄清确实需要保留中间态时才划算。
