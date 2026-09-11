# AIOA 多租户专家知识库 · 差距清单与改进实现方案

> 版本：v1.0 ｜ 日期：2026-09-11
> 目标：租户可按需配置通用专家（≥6 领域，支持导入），配置维度完整且**每一处都真实生效**；
> 知识库接入形成「上传 → 解析 → 清洗 → 切分 → 向量化 → 入库 → 检索召回」完整链路，
> 采用 Elasticsearch + ES 向量库；底层大模型本地 mock（不打真实 API），但闭环与参数生效必须可验证。

---

## 一、现状盘点（已具备的能力，不重复造）

| 能力 | 现状 | 位置 |
|---|---|---|
| 文档解析 | **已支持** PDF/Word(doc,docx)/Excel(xls,xlsx)/TXT/MD/CSV，PDFBox + POI | `server/aioa-resource/.../service/KbFileParser.java` |
| 知识库存储抽象 | `KnowledgeStore` 接口 + `MysqlKnowledgeStore`，**已预留** `aioa.kb.store=vector` 切换点 | `.../store/KnowledgeStore.java`<br>`.../store/MysqlKnowledgeStore.java` |
| 文档/切片表 | `kb_document`(54 条，42 条 OK) / `kb_chunk`(792 条) | MySQL `aioa` |
| 专家表 | `ai_expert`(4 条，均为全局模板 tenant_id=0) | 政策咨询/法律援助/企业开办/办文助手 |
| 智能体定义 | `agent_definition`(4 条)，含 system_prompt / model_ref / context_turns / max_steps | model_ref 全为 `echo` |
| 工具注册表 | `tool_definition`(**0 条**)、`tool_permission`、`tool_invocation_log` | 表已建模，未填充 |
| Agent 推理链路 | OpenAI 兼容调用 + function-calling 循环（最多 `MAX_TOOL_ROUNDS` 轮），含引用溯源 `citations` | `agent/app/core/agent_runtime.py` |
| 事件契约 | `run.started → tool.call → tool.result → message.delta×N → message.completed → run.completed` | `agent/app/schemas.py` |
| 多租户骨架 | 9 个租户、14 家机构、88+ 员工、资源池/配额/费用分摊 | 2026-09-11 已填充 |

**结论**：骨架（解析、切片、存储抽象、工具注册表、Agent 循环）都在，缺的是
**向量化与检索、租户级配置内核、工具实例、意图路由、参数生效链路**。

---

## 二、差距清单

### A. 知识库 RAG 链路

| # | 差距 | 现状 | 目标 | 优先级 |
|---|---|---|---|---|
| A1 | **无向量化** | `kb_chunk` 无 embedding 列，检索是 `LIKE` 关键词匹配 | chunk 生成 embedding 并持久化，支持余弦向量检索 | P0 |
| A2 | **无向量库** | 无 ES、无 docker（本机未安装） | Elasticsearch `dense_vector` + HNSW；本地可降级为内置实现 | P0 |
| A3 | **检索为纯 LIKE** | 无 BM25、无语义、无阈值 | 混合检索（BM25 + 向量）经 RRF 融合，`rank_constant=60` | P0 |
| A4 | **入库流水线断点** | 9 条文档停在 `WAIT`，无 chunk；`FAILED` 无重试 | 状态机 `WAIT→PARSING→CHUNKING→INDEXING→OK/FAILED` + 失败重试与错误留痕 | P1 |
| A5 | **无清洗/切分策略配置** | 切分逻辑写死 | 切分策略（定长/按段落/按标题）、块大小、重叠率可配置且生效 | P1 |
| A6 | **无中文分词** | MySQL LIKE 无法处理中文语义 | ES 侧 `ik_max_word`/`ik_smart`；本地侧二元切分 | P1 |

### B. 专家与配置

| # | 差距 | 现状 | 目标 | 优先级 |
|---|---|---|---|---|
| B1 | **专家领域不足** | 仅 4 个（政策/法律/开办/办文） | ≥6 领域：法律咨询、劳动用工、合同审查、知识产权、合规风控、财税，另加综合数据分析师 | P0 |
| B2 | **无租户级专家实例** | `ai_expert` 全是 `tenant_id=0` 全局模板 | 租户从模板导入生成租户副本，可改、可关、可排序 | P0 |
| B3 | **无配置维度** | 无开关/可见范围/默认启用/知识库范围 | 见下方「配置维度表」 | P0 |
| B4 | **无覆盖规则（override）** | — | 全局 < 租户 < 机构 < 部门 < 个人，逐级 merge，可解释 | P0 |
| B5 | **参数不生效** | 温度在 `agent_runtime.py` **硬编码 0.3**；无 topK、无相似度阈值配置项 | 全部参数来自配置解析结果，并回传 `effective_params` | P0 |
| B6 | **无配置可解释性** | 无法得知某个专家最终用了哪套配置 | 提供 resolve 接口，返回每层来源与最终值 | P1 |

### C. 工具与 Agent 闭环

| # | 差距 | 现状 | 目标 | 优先级 |
|---|---|---|---|---|
| C1 | **无工具实例** | `tool_definition` 0 条 | 至少：`sql_query`（真实查 MySQL）、`python_script`（沙箱执行）、`kb_search` | P0 |
| C2 | **无意图识别/工具路由** | 完全依赖 LLM function-calling（mock 下不可用） | 本地规则引擎：意图识别 → 工具路由 → 参数抽取 | P0 |
| C3 | **无企业模拟数据集** | 仅 `approval_order`(82)/`payment_order`(8)/`biz_kpi`(9) | 建销售/客户/产品/库存/财务/人力/合同主题表，≥2000 行/表 | P0 |
| C4 | **无 Python 沙箱** | — | 受限执行：白名单 import、禁文件/网络、超时与内存限制 | P0 |
| C5 | **SQL 无安全约束** | — | 只读账号、表白名单、禁 DML/DDL、强制 LIMIT、超时 | P0 |
| C6 | **无执行过程可观测** | 只有 tool.call/tool.result | 逐步记录 `agent_run_step`，前端可展开看链路 | P1 |

### D. 验证与工程

| # | 差距 | 现状 | 目标 | 优先级 |
|---|---|---|---|---|
| D1 | 无参数生效验证手段 | — | A/B 自检脚本：改一个参数 → 断言输出随之变化 | P0 |
| D2 | 无自检清单文档 | — | 配置/验证/回滚三栏清单 | P1 |
| D3 | 无回归测试 | agent 有 4 个测试文件 | 新增 RAG/工具/配置解析/参数生效的测试 | P1 |

---

## 三、改进方案

### 3.1 目标架构（数据/控制流）

```
用户提问
  │
  ▼
[专家解析] resolve(tenant, institution, dept, user, expertKey)
  │  全局默认 → 租户 → 机构 → 部门 → 个人（逐级 merge，返回每层来源）
  ▼
[生效配置] { model, temperature, topK, threshold, kbScope, enabled, tools, ... }
  │
  ├──► [意图识别] 本地规则引擎 → intent + 槽位抽取
  │         ├─ DATA_ANALYSIS → 工具路由: sql_query / python_script
  │         ├─ KB_QA        → 工具路由: kb_search
  │         └─ CHAT         → 直接生成
  │
  ├──► [工具执行] sql_query(只读+白名单+LIMIT) │ python_script(沙箱) │ kb_search(混合检索)
  │
  ▼
[结果整合] mock LLM 按 temperature 生成 → 输出正文 + citations + effective_params
```

### 3.2 配置维度（租户可在管理端配置）

| 维度 | 键 | 取值 | 默认值 | 作用点 | 生效验证方式 |
|---|---|---|---|---|---|
| 专家开关 | `enabled` | on/off | on | 关闭后专家不可见、调用返回 403 | 关掉后列表不出现 + 调用被拒 |
| 可见范围 | `visibleScope` | ALL / TENANT / INSTITUTION:ids / DEPT:ids / USER:ids | ALL | 决定谁能看到该专家 | 切到指定机构，其他角色看不到 |
| 默认启用 | `defaultEnabled` | on/off | off | 新用户进入时默认挂载 | 新用户登录即见 |
| 知识库范围 | `kbScope` | ALL / docIds[] / tagIds[] | ALL | 只在该范围内检索 | 换 kbScope 后命中文档集合变化 |
| 模型 | `model` | 模型标识 | `mock-default` | `run.started.model` | 切换后事件里 model 字段变化 |
| 温度 | `temperature` | 0.0–1.0 | 0.3 | mock LLM 采样 | 0.1 vs 0.9 输出分布可区分 |
| 召回条数 | `topK` | 1–20 | 5 | 检索返回条数 | topK=3 与 10 时 citations 数不同 |
| 相似度阈值 | `threshold` | 0.0–1.0 | 0.35 | 过滤低分 chunk | 调高后低分片段被剔除 |
| 检索模式 | `retrievalMode` | vector / bm25 / hybrid | hybrid | 决定召回算法 | 同 query 三模式结果不同 |
| 工具开关 | `tools.sql_query` 等 | on/off | on | 关闭后该工具不可路由 | 关闭后走兜底回答 |
| 排序 | `sort` | 数字 | 100 | 展示顺序 | 调整后列表顺序变化 |

### 3.3 数据模型改动

**新增表**

| 表 | 用途 | 关键字段 |
|---|---|---|
| `expert_config` | 统一配置与覆盖（一张表覆盖 B3/B4） | `tenant_id, scope_type, scope_id, expert_key, config_json, priority` |
| `kb_ingest_task` | 入库流水线任务（A4） | `doc_id, stage, progress, error_msg, retry_count` |
| `biz_*` 企业模拟数据 | 供数据分析师查询（C3） | 销售/客户/产品/库存/财务/人力/合同 |

**改表**

| 表 | 改动 | 说明 |
|---|---|---|
| `kb_chunk` | +`embedding BLOB`、`embedding_provider`、`embedding_dims`、`embedding_at` | 向量持久化 |
| `ai_expert` | +`category`、`template_version`、`source_template_id` | 支持从模板导入与版本追溯 |

**配置覆盖优先级**（`scope_type`）：
`GLOBAL(0) < TENANT(1) < INSTITUTION(2) < DEPT(3) < USER(4)`，
同 `expert_key` 按优先级升序 merge，高优先级覆盖低优先级；`expert_key='*'` 为全局默认。

### 3.4 代码改动清单

| 模块 | 文件 | 改动 |
|---|---|---|
| 后端 | `.../store/ElasticKnowledgeStore.java` | **新增**：ES 实现，`dense_vector`+HNSW，混合检索 + 客户端 RRF |
| 后端 | `.../store/MysqlKnowledgeStore.java` | 增加向量列读写 + BM25(FULLTEXT ngram) 兜底 |
| 后端 | `.../service/EmbeddingProvider.java` | **新增**：`local`(默认，确定性哈希/TF-IDF) / `bge-small-zh`(可选) 两实现 |
| 后端 | `.../service/KbService.java` | 接流水线：解析→清洗→切分(可配置)→向量化→入库，状态机 + 重试 |
| 后端 | `.../controller/ExpertConfigController.java` | **新增**：专家列表/导入/配置读写/resolve 可解释接口 |
| 后端 | `.../service/ExpertConfigService.java` | **新增**：merge 解析 + 缓存 |
| 后端 | `.../controller/ToolController.java` | 工具注册、启停、测试执行 |
| 后端 | `.../service/tools/SqlQueryTool.java` | **新增**：只读 + 白名单 + 禁 DML/DDL + LIMIT + 超时 |
| agent | `app/tools/local_tools.py` | **新增**：SQL / Python 沙箱 / KB 检索 三个本地工具 |
| agent | `app/tools/sandbox.py` | **新增**：受限 Python 执行（AST 白名单 + 子进程 + 超时 + 内存限制） |
| agent | `app/core/intent_router.py` | **新增**：规则意图识别 + 工具路由 |
| agent | `app/model_gateway/mock_llm.py` | **新增**：可受 temperature/topK 影响的确定性 mock LLM |
| agent | `app/core/agent_runtime.py` | **改造**：温度改为配置传入；新增 `effective_params` 回传 |
| 前端 | `src/views/ExpertConfigView.vue` | **新增**：租户专家配置页（开关/可见范围/知识库范围/参数） |
| 前端 | `src/views/KbIngestView.vue` | **新增**：文档入库流水线可视化（阶段、进度、失败重试） |
| 前端 | `src/views/ToolRegistryView.vue` | **新增**：工具注册与测试 |
| 脚本 | `scripts/seed_biz_dataset.py` | **新增**：企业模拟数据集 |
| 脚本 | `scripts/verify_config_effect.py` | **新增**：参数生效 A/B 自检 |

### 3.5 关键设计决策

**D-1 向量库抽象（不阻塞本地联调）**
`KnowledgeStore` 保持接口不变，提供两种实现：
- `elasticsearch`（**目标形态**）：`dense_vector(dims, index:true, similarity:cosine)` + `text`(ik) + `tenant_id` keyword filter；
  检索用 `knn` + `match`，**客户端 RRF 融合**（`rank_constant=60`）——因 ES 原生 RRF retriever 需 Enterprise 许可；
- `local`（**默认，零依赖**）：内存/文件持久化向量索引 + 二元切分 BM25，保证本机无 ES 也能跑通全链路。

切换方式：`aioa.kb.store=elasticsearch|local`，一次配置、无代码改动。
当你本机装好 ES（或给我可用的 ES 地址），改配置即可切到真 ES，检索行为一致、可对比。

**D-2 Embedding 可插拔**
`EmbeddingProvider`：`local`（默认，确定性哈希 + TF-IDF 加权，无需下载模型、结果可复现）/
`bge-small-zh`（可选，需下载 ~100MB，语义更准）。维度固定 768 以对齐 ES mapping。

**D-3 参数真实生效的可验证机制（核心）**
每次运行返回 **`effective_params` 生效参数快照**（含每个参数的最终值与来源层级），
并记录进 `agent_run_step`。验证时只需断言「改配置 → `effective_params` 变 → 输出行为变」三者一致。

**D-4 mock LLM 也要让温度有意义**
mock LLM 用「种子化采样」：温度越低越偏向最高概率候选（确定性），温度越高越均匀采样。
这样温度 0.1 与 0.9 的输出**可被客观区分**，不是摆设。

**D-5 意图路由不依赖 LLM**
本地规则引擎（关键词 + 正则 + 打分），规则可配置、可测试，保证 mock 环境下闭环稳定可复现。

---

## 四、实施阶段

| 阶段 | 内容 | 交付物 | 依赖 |
|---|---|---|---|
| P1 | 配置内核：`expert_config` 表 + ExpertConfigService + resolve/导入接口 | 配置有处存、能解析、可解释 | — |
| P2 | RAG 链路：向量化 + ES/本地双实现 + 混合检索 + 入库流水线 | 上传文档可被检索命中，带分数与来源 | P1 |
| P3 | 工具中心：企业模拟数据集 + SQL 工具 + Python 沙箱 + 工具注册 | 工具可执行、可观测、有安全边界 | — |
| P4 | 数据分析师专家：意图路由 + 完整闭环（取数→计算→整合→输出） | 一次提问跑通全链路 | P1,P2,P3 |
| P5 | 通用专家模板：法律咨询、劳动用工、合同审查、知识产权、合规风控、财税 | 租户可一键导入 | P1 |
| P6 | 参数生效验证 + A/B 自检 + 自检清单文档 | 逐参数可验证 | P1–P5 |
| P7 | 管理端页面：专家配置 / 入库流水线 / 工具注册 | 可在界面操作 | P1–P3 |

---

## 五、每处改动「如何影响配置 / 如何验证生效」（节选）

| 改动 | 影响的配置 | 验证方式（可复现命令/断言） |
|---|---|---|
| `expert_config` 表 + merge 解析 | 所有专家参数 | `GET /api/v1/expert-config/resolve?expertKey=legal` 返回每层来源与最终值；改租户层后最终值随之变 |
| 温度改为配置传入 | `temperature` | 同一 query 跑 `temperature=0.1` 与 `0.9` 各 20 次，输出去重数应显著不同（0.1 更集中） |
| topK 接入检索 | `topK` | `topK=3` 时 `citations.length<=3`；`topK=10` 时条数增加 |
| 阈值过滤 | `threshold` | 阈值从 0.2 提到 0.8，低分 chunk 消失，返回片段的 `score` 全部 ≥0.8 |
| kbScope 过滤 | `kbScope` | 指定单文档后，命中集合仅含该文档；切 ALL 后恢复全量 |
| 检索模式 | `retrievalMode` | 同 query 下 `vector`/`bm25`/`hybrid` 三模式 Top5 结果不完全相同，且 hybrid 含两路命中 |
| 专家开关 | `enabled` | 关闭后列表不返回该专家，直接调用返回 403 且 message 明确 |
| 可见范围 | `visibleScope` | 以范围内/外两个账号调用，一个可见一个不可见 |
| 工具开关 | `tools.sql_query` | 关闭后同类问题不再路由到 SQL，走兜底；`tool_calls` 为空 |
| 向量库切换 | `aioa.kb.store` | 切 `local`/`elasticsearch` 后同一 query 的 Top1 文档一致（向量与检索算法一致） |
| Python 沙箱 | 沙箱策略 | 尝试 `import os` / 写文件 / 死循环 → 分别被拦截/超时，且不影响主进程 |

---

## 六、待确认决策点（确认后即进入落地）

1. **向量库**：本机无 ES、无 docker。
   - 方案 A（推荐）：双实现，默认 `local` 跑通闭环，`elasticsearch` 实现同步写好，有 ES 时改配置即用。
   - 方案 B：我下载并本地安装 ES 8.x（约 600MB，需占用一个端口与 ~1.5GB 内存）后再只做 ES 单实现。
   - 方案 C：你提供可访问的 ES 地址，直连真 ES。

2. **Embedding**：`local`（默认，零下载、可复现）还是下载 `bge-small-zh`（语义更准，需 ~100MB）。

3. **Python 沙箱强度**：严格（禁一切 import，仅内置函数 + 注入的 `db.query`）还是适度（开放 pandas/numpy/json/math 用于数据分析）。

4. **企业模拟数据规模**：建议每表 2000–5000 行（能体现聚合分析价值，生成约 1–2 分钟）；也可按需增减。
