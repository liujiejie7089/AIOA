# 32 · 向量库迁移 Milvus 实施计划

> 目标：把知识库检索的**向量存储**从「MySQL BLOB + 应用层余弦」换成 **Milvus**，沿既有
> `KnowledgeStore` SPI 以 `aioa.kb.store=milvus` 一步切换，业务层（管理端 / 用户端 / agent / 工具网关）
> **零改动**；并**同步把嵌入模型从 256 维哈希升级为语义向量**——否则换库几乎没有收益（见 §2）。
>
> 状态：**已落地**（2026-09-19 实施完成；代码 / 配置 / 部署 / 测试已就绪，收口记录见 §11）。
> 撰写日期：2026-09-19。
> ⚠️ **验证边界**：实施机无 Docker / 无 WSL / 内网无 Milvus 实例，因此「活体 Milvus 集成」**未在本机执行**。
> 已实测的是：编译、纯逻辑单测（26 条）、`store=mysql` 全量回归（155/155）、`store=milvus` 的 fail-fast、部署件与配置解析。
> 逐项边界与补验步骤见 **§11.3**（不谎报全绿）。

---

## 0. 一句话结论

本计划把「换 Milvus」与「换嵌入模型」视为**一个目标、两步交付**：

1. **先升级嵌入**（不碰 Milvus，可独立验收、可回滚）；
2. **再接 Milvus**（SPI 新增一个实现类，配置切换）。

MySQL 始终保留为**切片权威底座**，Milvus 是**可随时重建的向量索引副本** ⇒ 回滚 = 改一行配置，索引损坏 = 一条回填命令。

---

## 1. 现状盘点

| 组件 | 位置 | 现状 |
|---|---|---|
| 存储 SPI | `aioa-resource/…/store/KnowledgeStore.java` | 接口已就位，9 个方法（文档 CRUD / 切片替换 / 向量落库 / 混合检索） |
| 默认实现 | `…/store/MysqlKnowledgeStore.java` | `@ConditionalOnProperty(aioa.kb.store=mysql, matchIfMissing=true)`；文档与切片均在 MySQL；`embedding` = float32 小端 BLOB；检索 = n-gram 关键词 + 余弦 + **RRF(k=60)** |
| 预留实现 | `…/store/ElasticKnowledgeStore.java` | **骨架**：写操作抛 `UnsupportedOperationException`，读操作**静默返回空列表** |
| 嵌入 provider | `…/service/EmbeddingProvider.java` | 仅 `local` = **256 维 char 2-gram 哈希 + L2 归一化**（确定性、零依赖，但**无语义**） |
| 嵌入装配 | `…/config/EmbeddingConfig.java` | 硬编码 `EmbeddingProvider.local()`；`aioa.kb.embedding-provider` 目前只有文档注释、**未接线** |
| 配置键 | `application.yml` | `aioa.kb.store: ${AIOA_KB_STORE:mysql}`（`vector` 仅在注释里被提及） |
| 消费方 | `KbService`（唯一注入点）、`ToolGatewayService.searchKb` | 经 `KbService` → `store`；上层拿 `KbHit(docId, docName, snippet, chunkIndex, score)` |
| 调用链 | agent → 工具网关 → KbService → store | agent 侧工具名 `search_kb_documents`，经 HTTP 调后端 `/api/v1/workbench/tools/invoke`；专家配置 `topK/threshold/retrievalMode/kbScope` 透传生效 |
| 数据 | `kb_document` / `kb_chunk` | 文档 **21** 份；切片 **556** 条，**已向量化仅 62 条（11%）**；全部 `local / 256` |
| 部署 | `deploy/docker-compose.yml`、`deploy/k8s/*` | compose 含 minio / vllm / ollama / prometheus / grafana / loki；**mysql 服务被注释**；无任何 Milvus 痕迹；`pymilvus` 未安装 |
| 设计文档口径 | `docs/01-架构设计.md` | 写的是「向量库 pgvector（PG16）」，与现状（MySQL）**已不一致**，本次一并修正 |

**现有 SPI 契约（迁移不可破坏的硬约束）**
- `listVisible / search` 只返回「本人 + 租户共享（TENANT）+ 公共（user_id=0）」，**跨租户零泄露**；
- `replaceChunks` 先清后写，**幂等**；
- 命中返回**原文片段 + 分数**，供引用溯源与阈值过滤。

---

## 2. 关键判断：换库 ≠ 提质（本计划最重要的前置结论）

| | 当前 `local` | 目标（语义模型） |
|---|---|---|
| 向量含义 | 字符 2-gram 频率哈希 | 语义嵌入 |
| 相似度等价于 | **n-gram 字面重叠** | 语义相近 |
| 512 维 vs 256 维 | dims 可配但含义不变 | 维度随模型固定 |
| Milvus 收益 | 仅「换了个存储」 | HNSW 近似最近邻 + 原生混合检索 + 多租户 partition + 水平扩展 |

> 结论：**若保持 `local` 哈希不变而只换 Milvus，检索质量与今日基本持平（甚至可能变差——会丢掉现有 BM25-lite 的字面命中优势），收益只是基础设施换代。**
> 因此本计划**必须先换嵌入**，再用 Milvus 承接真实向量。这也是把交付拆成两步的原因。

---

## 3. 目标架构

```
                   ┌─────────────────────────────────────────────┐
 agent(search_kb_  │  MySQL（权威事实源，回滚底座）                │
   documents) ──►  │   kb_document  文档元数据 / 可见范围 / 状态    │
      │ HTTP       │   kb_chunk     切片正文 + embedding BLOB     │
      ▼            └──────────────┬──────────────────────────────┘
 ToolGatewayService.searchKb     │ 写：切片 → 嵌入 → 回写 BLOB
      │                          │ 　　　　　　　　　 └─► upsert Milvus
      ▼                          ▼
   KbService  ──►  EmbeddingProvider（Ph1 升级为语义模型）
      │                          │
      ▼                          ▼
 KnowledgeStore SPI  ──►  MilvusKnowledgeStore（Ph2 新增，store=milvus）
                            collection kb_chunk_v1（partition_key=tenant_id）
                            ├─ 标量：tenant_id / user_id / doc_id / chunk_index / scope
                            ├─ 文本：content（供原生 BM25 与免回查）
                            ├─ 向量：vector[512]  HNSW / COSINE
                            └─ 检索：dense ⊕ BM25 → RRFRanker(60) ＋ expr 过滤
```

**为什么不把文档元数据也迁进 Milvus**：文档列表 / 重命名 / 改可见范围 / 软删是高频**关系型**操作，
放进向量库得不偿失。保持 **MySQL 为权威**，Milvus 只做「向量检索」这一件它擅长的事：

- 回滚 = `AIOA_KB_STORE=mysql`（零数据迁移）；
- Milvus 索引损坏 = 从 `kb_chunk` 一条回填命令重建；
- 双写失败不阻断入库（与现状 `embedAll` 的 try/catch 语义一致）。

**数据流**
- 写：上传 → 解析/切片 → 写 `kb_chunk`(MySQL) → 嵌入 → 回写 `kb_chunk.embedding` ＋ `upsert` Milvus
- 读：query → 嵌入 → Milvus `hybrid_search`（expr 过滤 tenant/user/scope/docScope）→ 命中 → 组装 `KbHit`

---

## 4. 决策点（D1–D6，含推荐）

| # | 决策 | 选项 | 推荐 | 理由 |
|---|---|---|---|---|
| **D1** | 嵌入模型与维度 | ① `bge-small-zh-v1.5`(512) ② `bge-m3`(1024) ③ 保持 `local`(256) | **① 512 维** | 中文场景成熟、体积小（≈100MB）、CPU/GPU 都友好；1024 维收益边际小、索引与存储翻倍 |
| **D2** | 嵌入执行位置 | ① Java 侧 ONNX ② HTTP 服务（Ollama/vLLM） ③ Python 侧 | **② HTTP** | compose **已有 ollama/vllm**，复用它零新增部署；Java 侧新增 `HttpEmbeddingProvider`，`EmbeddingProvider` 接口不变；`local` 保留为无外网兜底 |
| **D3** | Milvus 版本 | ① 2.4 LTS ② 2.5.x | **② 2.5.x** | 原生 **BM25 Function** + `hybrid_search` + `RRFRanker`，可省掉自研 BM25（保底见 R2） |
| **D4** | Milvus 职责范围 | ① 仅向量 ② 向量+内容+过滤元数据 | **②** | 免回查、且原生 BM25 需要文本进 Milvus |
| **D5** | 多租户隔离方式 | ① 仅 expr 过滤 ② `partition_key=tenant_id` + expr | **②** | Milvus 官方多租户模式，隔离与删除都更干净，且是 SPI 契约的硬要求 |
| **D6** | Milvus 不可用时的行为 | ① fail-fast ② 静默降级空结果 | **① fail-fast** | 明确避免重蹈 `ElasticKnowledgeStore` **静默空结果**的坑（会让检索无声失效） |

---

## 5. 分批次实施计划

### Ph0 · 决策锁定 + 环境就绪
- **动作**：锁定 D1–D6；compose 增加 `etcd` + `minio`（独立 bucket/卷）+ `milvus-standalone`（含 attu 可选）；
  验证 `milvus-sdk-java` 版本对 **2.5 BM25 Function / hybrid_search** 的支持度（D3 的验证项）。
- **交付**：决策记录、compose 增量、最小连通性单测、Milvus 本地启动脚本。
- **验收**：`:9091/healthz` 为 `OK`；Java 侧能建集合 / 插一条 / 查回来。
- **产出**：`deploy/docker-compose.yml` 增量、`server/aioa-resource/pom.xml` 增 `milvus-sdk-java`。

### Ph1 · 嵌入升级（**不碰 Milvus**）
- **动作**：新增 `HttpEmbeddingProvider`（指向 ollama/vllm 的 embedding 端点）；`EmbeddingConfig` 按
  `aioa.kb.embedding-provider=local|http` 装配（同时接线 `dims`）；**全量重算 556 条切片向量**（一次性 job/脚本）；
  `kb_chunk.embedding_dims` 落库校验。
- **交付**：provider 实现、配置接线、重算脚本、`scripts/e2e_v62_embedding.py`。
- **验收**：现有 29 套 E2E 全绿；新增套件绿；**检索质量抽样对比**（升级前 vs 升级后，人工核对 top-N）。
- **回滚**：配置回 `local`（注意：dims 已变，回滚需重算；或接受混维——`cosine()` 对长度不等直接返回 0，不会崩，只会不命中）。

### Ph2 · `MilvusKnowledgeStore`（核心）
- **动作**：新增实现类（`@ConditionalOnProperty(aioa.kb.store=milvus)`），业务层零改动；
  集合自动创建（schema + 索引 + `partition_key=tenant_id`），集合名带版本后缀 `kb_chunk_v1` 便于平滑重建；
  实现 9 个方法（upsert 以 `kb_chunk.id` 为主键幂等、`delete by doc_id`）；
  回填 job（`aioa.kb.milvus.backfill=true` 时把 MySQL 全量切片+向量灌入 Milvus）。
- **交付**：`MilvusKnowledgeStore.java`、集合自建与索引、回填 job、`scripts/e2e_v62_milvus_kb.py`。
- **验收**：单测 + 在 `store=milvus` 下套件绿；「上传即可检索」；删除后不再命中；重试/重跑幂等。
- **回滚**：`AIOA_KB_STORE=mysql`。

### Ph3 · 混合检索对齐
- **动作**：dense（HNSW/COSINE）⊕ BM25（优先 Milvus 2.5 原生；保底客户端 RRF，即现有形态）→ `RRFRanker(60)`；
  **同一批用例在 `mysql` 与 `milvus` 两种 store 下双跑**，命中集合与排序做对齐/容差断言。
- **交付**：双跑回归脚本与对齐报告、跨租户隔离专项用例。
- **验收**：`mode ∈ {vector, bm25, hybrid}` 三态均正确；`topK/threshold/kbScope` 真实生效；
  **t2 用户不得命中 t9 文档**，同租户越权同理（隔离矩阵）。

### Ph4 · 切换与全量回归
- **动作**：`e2e_full_system.py`(155) + 按钮级（H5 27 / shell 145）+ 新增两套，全绿；
  部署环境变量切默认值（**代码默认仍为 `mysql`**，保证无 Milvus 环境照样能跑）。
- **验收**：三端服务在线、套件全绿；管理端 `KbView.vue` 与 H5 知识库页**零改动**即功能正常（SPI 隔离的证明）。

### Ph5 · 运维加固与文档
- **动作**：compose/k8s 落地 Milvus（卷持久化 + 健康检查 + 重启策略）；Milvus 指标接 prometheus；
  备份与「从 MySQL 重建索引」演练；文档更新（修正 `docs/01` 的 pgvector 表述、本计划收口、记忆更新）。
- **验收**：重启后数据不丢；重建演练通过；监控有面板。

---

## 6. 风险与对策

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | 集合维度**创建后不可改**，换模型必须重建 | 高 | Ph2 前锁死 D1；集合名带版本后缀；重建走回填 job |
| R2 | `milvus-sdk-java` 对 2.5 原生 BM25 Function 支持不确定 | 中 | **Ph0 实测**；不通则退回**客户端 RRF 融合**（正是现有代码形态，零新增风险） |
| R3 | standalone 依赖 etcd + 对象存储，重启易丢数据 | 中 | compose 显式命名卷；文档化重启流程；k8s 用 PVC |
| R4 | 一致性延迟导致「刚上传检索不到」 | 中 | 写入后 `flush` 或用 `Strong` 一致性；用例显式断言「上传即可检索」 |
| R5 | 跨租户泄露（最严重） | **高** | `partition_key=tenant_id` + expr 过滤 + **专项隔离用例**（对齐 SPI 契约） |
| R6 | 双写失败阻断入库 | 中 | 与现状一致：Milvus 写失败只告警、不置 `FAILED`；MySQL 底座保证可重建 |
| R7 | 历史 62 条 `local/256` 与新维度不兼容 | 低 | 全量重算（本来也要重算） |
| R8 | 复制 `ElasticKnowledgeStore` 的**静默空结果**反模式 | **高** | D6：Milvus 不可用即 **fail-fast**，禁止静默降级 |
| R9 | 误把文档元数据也迁进 Milvus 导致关系查询退化 | 中 | 范围边界：**不迁**（见 §9） |

---

## 7. 测试策略

| 类别 | 内容 |
|---|---|
| **复用（回归基线）** | `e2e_full_system.py`（含 KB 段）、`e2e_agent_orchestrator.py`（citations 引用溯源）、按钮级 `e2e_v61_h5_all_buttons.py` / `e2e_v61_shell_all_buttons.py`（知识库页） |
| **新增** | `e2e_v62_embedding.py`（Ph1）、`e2e_v62_milvus_kb.py`（Ph2–3） |
| **双跑矩阵** | `store ∈ {mysql, milvus}` × `mode ∈ {vector, bm25, hybrid}` |
| **隔离矩阵** | 跨租户（期望零命中/不泄露）、同租户跨机构、个人 / 租户共享 / 公共三类可见性 |
| **一致性** | 上传→立即检索；删除→不再命中；重跑入库幂等 |
| **验收口径** | 两种 store 下同批用例**均绿**；Milvus 下命中质量抽样**不低于 MySQL 基线** |

---

## 8. 交付物清单

| 层 | 文件 |
|---|---|
| 代码 | `store/MilvusKnowledgeStore.java`（新）、`service/HttpEmbeddingProvider.java`（新）、`config/EmbeddingConfig.java`（改）、`config/MilvusConfig.java`（新）、回填 job |
| 构建 | `server/aioa-resource/pom.xml`（增 `milvus-sdk-java`） |
| 配置 | `application.yml`：`aioa.kb.store` 增 `milvus`、`aioa.kb.embedding-provider` 接线、新增 `aioa.kb.embedding.*` 与 `aioa.kb.milvus.*` |
| 部署 | `deploy/docker-compose.yml`（etcd/minio/milvus）、`deploy/k8s/*` |
| 测试 | `scripts/e2e_v62_embedding.py`、`scripts/e2e_v62_milvus_kb.py` |
| 文档 | 本文件（收口记录）、`docs/01-架构设计.md`（pgvector 口径修正）、记忆要点 |

---

## 9. 范围边界（明确不做）

- ❌ 不把**文档元数据**迁入 Milvus（MySQL 权威不变）
- ❌ 不自研 / 不训练稀疏向量
- ❌ 不改管理端 / 用户端 / agent 的**业务代码**（全部靠 SPI 隔离）
- ❌ 本阶段不做 Milvus **集群**（单机 standalone 够用，水平扩展留作后续）
- ❌ 不动假种 / 审批 / 计费 / 权限等无关模块

---

## 10. 落地顺序速查

```
Ph0 决策+环境 ──► Ph1 嵌入升级(可独立验收/回滚) ──► Ph2 Milvus 实现 ──► Ph3 混合检索对齐
                                                                        │
                                                      Ph4 双跑回归+切换 ◄┘ ──► Ph5 运维加固+文档
```

**最小的「今天就能做」的一步**：Ph0 —— 在 compose 里起 Milvus 单机并跑通 Java 侧连通性，
同时实测 `milvus-sdk-java` 对 2.5 BM25 的支持（R2）。这一步不碰任何业务代码，风险为零。

---

## 11. 收口记录（2026-09-19 实施）

### 11.1 交付物对照

| 层 | 计划 | 实际 | 状态 |
|---|---|---|---|
| 构建 | `aioa-resource/pom.xml` 增 `milvus-sdk-java` | 父 pom 加 `milvus-sdk.version=2.6.25` + dependencyManagement；resource 模块加依赖 + `spring-boot-starter-test` | ✅ 编译通过（fat-jar 82MB → 110MB，SDK 及 gRPC 传递依赖所致） |
| 代码 | `store/MilvusKnowledgeStore.java`（新） | 已建，实现 SPI 9 方法 + `backfill()` | ✅ 编译通过，**活体未验** |
| 代码 | `service/HttpEmbeddingProvider.java`（新） | 已建，兼容 Ollama 三种端点形状 + OpenAI 形状 | ✅ 9 条单测绿 |
| 代码 | `config/MilvusConfig.java`（新） | 已建：连接 + 集合自建（partition_key=tenant_id、HNSW/COSINE、BM25 Function）+ 维度校验 + load | ✅ 编译通过，**活体未验** |
| 代码 | `config/EmbeddingConfig.java`（改） | 按 `aioa.kb.embedding-provider` 装配 local/http | ✅ |
| 代码 | 回填 job | `service/KbIndexMaintenanceRunner.java`：`reembed-on-start`（Ph1 重算）+ `milvus.backfill-on-start`（Ph2 回填），先重算后回填 | ✅ 默认全关，mysql 档启动行为不变 |
| 代码 | —（计划外新增） | `store/KbRelationalDao.java`、`store/RrfFusion.java`、`store/KeywordScorer.java`、`store/MilvusFilter.java` | ✅ 见 §11.2 偏离 1/2/5 |
| 配置 | `application.yml` | `aioa.kb.{store,embedding-provider,reembed-on-start,embedding.*,milvus.*}` 共 22 键全接线 | ✅ |
| 部署 | `deploy/docker-compose.yml`（etcd/minio/milvus） | `etcd` + `milvus-minio` + `milvus`（profile=`milvus`），3 个命名卷、健康检查、重启策略、日志轮转 | ✅ YAML 解析 + profile 依赖检查通过；**未实际拉起** |
| 部署 | `deploy/k8s/*` | 新增 **`40-milvus.yaml`**：etcd + milvus-minio + milvus 三组 Deployment/Service + 三个 PVC（同镜像 tag、同服务名、同环境变量，切档时 server 侧只改 `AIOA_KB_STORE`）；`00-namespace-config.yaml` 补 kb/milvus 22 键（令牌与 API Key 归 Secret）；`k8s/README.md` 补「切到 Milvus」五步 | ✅ YAML 解析通过（9 docs）、与 compose 键逐项对齐；**未对真机集群应用过** |
| 测试 | `scripts/e2e_v62_embedding.py`、`e2e_v62_milvus_kb.py` | 合并为 **`scripts/e2e_v62_milvus_kb.py`**（一份脚本两档跑，用 `AIOA_KB_STORE` 声明期望档位 + M1 自检） | ✅ mysql 档 25/25；milvus 档待有实例时跑 |
| 测试 | —（计划外新增） | `aioa-resource/src/test/java/...` 4 个测试类 26 条用例 | ✅ 26/26 |
| 文档 | 本文件收口 + `docs/01` 口径修正 | 已完成（`docs/01` 的 pgvector 两处口径已改为 MySQL/Milvus 实际形态） | ✅ |
| 部署 | —（计划外补正） | `deploy/ops/prometheus.yml`（**原文件缺失**，而 compose 的 `prometheus` 服务会挂载它 ⇒ 缺文件时 Docker 建同名目录、Prometheus 起不来）：scrape `milvus:9091/metrics` + `etcd:2379/metrics` | ✅ YAML 解析通过；**未在真实 Prometheus 中验证抓取**。`server`/`agent` 业务指标仍未接（后端未引 `micrometer-registry-prometheus`、actuator 只暴露 `health`，抓 `/actuator/prometheus` 必 404），前置条件写在文件头 |
| 配置 | `deploy/.env.development` / `.env.production` | 各 99 键、键序逐行一致；新增 §7.0 嵌入 8 键 + §7.1 Milvus 13 键 | ✅ `set -a && .` 零报错 |
| 配置 | —（计划外补正） | `deploy/.env.example` 补知识库/Milvus 22 键模板；`deploy/ENV.md` §3.7 从「**预留（注释）／后端未读取**」改为真实键清单 + fail-fast 与回滚说明 | ✅ 脚本核对：与 `application.yml` 的 22 个占位键**无缺键**（旧文案属事实错误，见 §11.2 偏离 11） |

### 11.2 实施中对计划的偏离（及理由）

1. **新增 `KbRelationalDao`（计划外）** —— 计划假定 `MilvusKnowledgeStore` 直接复用 MySQL 的文档/切片逻辑，
   但 `MysqlKnowledgeStore` 是 `@ConditionalOnProperty(store=mysql)`，milvus 档下根本不装配。
   若在 milvus 档重写一遍文档 CRUD，**可见性隔离规则就有了两份实现**（跨租户泄露是 R5，最高风险）。
   做法：把「文档 + 切片 + 向量 BLOB」抽成不走 `@ConditionalOnProperty` 的 `KbRelationalDao`，两档共用。
   代价是动了默认路径 ⇒ 已用 `store=mysql` 全量 E2E **155/155** 证明零退化。
2. **新增 `RrfFusion` / `KeywordScorer`（计划外）** —— R2 的兜底「客户端 RRF」若另写一份，
   两档排序口径必然漂移，Ph3 的双跑对齐无从谈起。抽成公共纯函数，并由单测把 `1/(60+rank+1)` 钉死。
3. **`threshold` 与原生混合检索的取舍** —— Milvus `hybrid_search` 只回传融合分，拿不到「向量腿的分」，
   阈值无法只作用在向量召回上（而 mysql 档是这么做的）。若一律用服务端融合，`threshold` 就变成「配了不生效」。
   做法：`threshold <= 0`（默认）走服务端 `hybrid_search` + `RRFRanker(60)`（一次 RPC）；
   `threshold > 0` 时分腿检索 + 客户端 `RrfFusion`，保证 **topK / threshold / mode / kbScope 四参数两档语义一致**。
4. **命中回填 docName 仍回查一次 MySQL（偏离 D4「免回查」）** —— 正确性优先。
   文档删除是「MySQL 删 + Milvus 删」两处操作，Milvus 行可能滞后；
   只看 Milvus 就会把**已删文档的正文**返回给用户。故：MySQL 查不到即丢弃该命中（与 mysql 档一致）。
   `doc_name` 仍写入 Milvus，但只作运维排查用，权威值始终取 `kb_document.doc_name`。
5. **`MilvusFilter` 对空范围列表抛 `IllegalArgumentException`** —— 空列表有两种危险读法
   （静默当「不限范围」⇒ 越权；拼成 `doc_id in []` ⇒ 非法表达式）。调用方必须先短路。
6. **compose 用独立 `milvus-minio`（计划写的是复用 minio + 独立 bucket）** —— 转而逐项对齐
   **Milvus 官方 standalone compose**（未自创环境变量）：官方镜像假定 `minioadmin/minioadmin`，
   复用业务 MinIO 需额外对齐 access key，且业务文件与向量段文件混桶；独立 MinIO 只在 profile 打开时存在，代价很小。
7. **不引入 Attu（计划中本为「可选」）** —— 改用 Milvus 自带 WebUI（`http://<host>:9091/webui/`），
   少一个无法在本机验证 tag 的镜像依赖。
8. **新增 `/api/v1/kb/store` 诊断端点 + `/kb/search` 参数化** —— 双跑矩阵需要「知道自己在哪一档」与
   「能按 mode/topk/threshold/kbScope 检索」的入口。`/kb/search` 四个参数均为可选，
   **不传时行为与改造前逐字一致**（等效 `mode=bm25`、`topk=limit`、`threshold=0`、不限范围）。
9. **`MilvusConfig` 把 SDK 构造器也包进 fail-fast try** —— 实测发现连不上时异常在 `new MilvusClientV2()`
   就抛出（`enablePrecheck` 默认 true），在 try 之外；否则运维只能看到裸 `DEADLINE_EXCEEDED`，
   不知道该改哪个配置项。
10. **嵌入 provider 的维度强校验** —— 响应维度 ≠ 配置 `dims` 直接失败。
    Milvus 集合维度创建后不可改（R1），写进去就是永久坏数据。

11. **`.env.example` / `ENV.md` 补正（计划外）** —— 上一版 `ENV.md` §3.7 把嵌入与 Milvus 键写成
   「预留（注释）／后端未读取」，而代码已真实读取这 22 个键。这种「文档说它没用、代码在用」
   会让运维按旧文档判断「配了也不生效」⇒ 属于**事实错误**（与「展示字段必须与事实同源」同一类），
   已在 §11.1 记录并改为真实键清单。

### 11.3 验证边界（**不谎报全绿**）

**已在本机实测通过：**

| 项 | 证据 |
|---|---|
| 全 11 模块编译（主代码 + 测试代码） | `mvnw -DskipTests test-compile` → BUILD SUCCESS |
| 纯逻辑单测 26 条 | `MilvusFilterTest` 6 · `RrfFusionTest` 5 · `KeywordScorerTest` 6 · `HttpEmbeddingProviderTest` 9 → **26/26 绿** |
| `store=mysql` 全量系统 E2E | `e2e_full_system.py` → **155/155**（含 S11 知识库段、S12 H5 段）⇒ KbRelationalDao 重构零退化 |
| V62 套件（mysql 档） | `AIOA_KB_STORE=mysql e2e_v62_milvus_kb.py` → **25/25**（M1–M9） |
| **fail-fast（D6）** | `AIOA_KB_STORE=milvus` + Milvus 不可达 → 启动失败 `EXIT=1`，**无静默空结果** |
| compose 结构 | YAML 解析通过；默认 `up` 无跨 profile 依赖（profile 未开启不会打断默认启动） |
| env 两份 | 各 99 键、键序 `diff` 为空、`set -a && .` 零报错、prod 21 处 `CHANGE_ME__` 占位 |

**未在本机实测（受限于：无 Docker / `wsl.exe` 被安全策略拦截 / 内网无 Milvus 实例 / Windows 无 milvus-lite 轮子）：**

- Milvus 集合自建是否被服务端接受（尤其 **BM25 Function + SparseFloatVector**，即 R2 的落地验证项）；
- 活体 `hybrid_search` / `RRFRanker(60)` 的返回与排序；
- `backfill()` 的实际写入条数；
- `store=milvus` 下 V62 套件全绿（M1–M9）；
- 双跑对齐（同批用例 mysql vs milvus 的命中集合与排序容差）；
- compose 实际拉起后的连通性与重启不丢数据（R3）。

**补验步骤（在装有 Docker 的机器上，约 10 分钟）：**

```bash
# 1) 起向量库栈（etcd + milvus-minio + milvus-standalone）
AIOA_KB_STORE=milvus docker compose --profile milvus up -d
curl -f http://127.0.0.1:9091/healthz          # 期望 OK
# 2) 起后端并首次全量回填（跑完把 AIOA_MILVUS_BACKFILL 改回 false）
AIOA_KB_STORE=milvus AIOA_MILVUS_BACKFILL=true <启动 server>
grep -aE "Milvus 集合|回填完成|BM25" <server 日志>
# 3) 双档跑同一套用例
AIOA_KB_STORE=mysql  python scripts/e2e_v62_milvus_kb.py   # 期望 25/25
AIOA_KB_STORE=milvus python scripts/e2e_v62_milvus_kb.py   # 期望 25/25
```

预期需要现场确认的两点（都属于**代码已兜住、无需改代码**的情形）：

- **建集合时 BM25 被服务端拒绝**（服务端 < 2.5 或缺 analyzer）→ 日志出现 WARN，自动退回「纯稠密」，
  此后 `bm25` / `hybrid` 的关键词腿由 MySQL 切片 + `KeywordScorer` 兜底（口径与 mysql 档一致）。
- **集合维度与配置不符**（例如沿用旧集合）→ 启动即带明确文案失败，按提示新建集合名（`kb_chunk_v2`）+ 回填。

### 11.4 遗留

- ~~`deploy/k8s/*` 的 Milvus 清单未做~~ → 已补 `deploy/k8s/40-milvus.yaml`（etcd + milvus-minio +
  milvus 三组 Deployment/Service + 三个 PVC），但**未经真机集群应用验证**（本机无 K8s 集群）；
  清单顶部已写明必改项：`storageClassName`、资源配额、镜像仓库地址。
- ~~Milvus 指标接入 prometheus（Ph5）~~ → 已补 `deploy/ops/prometheus.yml`（scrape `milvus:9091/metrics`
  与 `etcd:2379/metrics`）；该文件此前**不存在**而 compose 会挂载它，属顺带修掉的既有缺陷。
  但 `server` / `agent` 的**业务指标仍然抓不到**：后端未引 `micrometer-registry-prometheus`、
  actuator 只暴露 `health` ⇒ `/actuator/prometheus` 必 404；接入前置条件写在配置文件头部。
- 「从 MySQL 重建索引」的实战演练（本地无实例，见 §11.3）。
- 现有数据里 **854 条切片仅 62 条有向量**（11%）：`store=milvus` 首次接入前建议先跑一次
  `AIOA_KB_REEMBED_ON_START=true` 把 BLOB 补齐，再 `AIOA_MILVUS_BACKFILL=true` 回填（顺序不能反）。
