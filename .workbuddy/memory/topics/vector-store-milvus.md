# 向量库（Milvus / KnowledgeStore）

> 摘自 `MEMORY.md §6`（2026-09-19 拆分）。计划与收口见 `docs/32`。

## 6. 向量库（Milvus 已落地）
- SPI = `KnowledgeStore`（9 方法），实现两档**互斥装配**：`MysqlKnowledgeStore`（`aioa.kb.store=mysql`，`matchIfMissing=true`）/ `MilvusKnowledgeStore`（`=milvus`）；`ElasticKnowledgeStore` 仍是**骨架**（写抛异常、读**静默返回空**，勿参照）。文档 + 切片**永远在 MySQL**（`KbRelationalDao` 两档共用，**不加 `@ConditionalOnProperty`**），Milvus 只是**可重建的向量索引副本** ⇒ 回滚 = 改一行配置。
- 嵌入：`EmbeddingProvider.local()` = **256 维 char 2-gram 哈希（无语义）**；`aioa.kb.embedding-provider=http` 走 `HttpEmbeddingProvider`（兼容 ollama `/api/embeddings`(prompt) 与 `/api/embed`(input)、openai `/v1/embeddings`；维度≠配置即抛；非 2xx/非 JSON/无向量均抛，**不返回零向量**）。
- `MilvusConfig` 自建集合（`partition_key=tenant_id`、HNSW/COSINE、BM25 Function 输出 SparseFloatVector；`enable-bm25=false` 退回纯稠密）；**集合维度创建后不可改**（须先锁）。`threshold<=0` 走服务端 `hybrid_search` + `RRFRanker(60)`，`>0` 分腿检索 + 客户端 `RrfFusion`（保证 topK/threshold/mode/kbScope 两档语义一致）。`RrfFusion`/`KeywordScorer`/`MilvusFilter` 抽成公共纯函数（**两档共用，防口径漂移**）；`MilvusFilter.visibility()` 的 `restrictedDocIds` **空列表必须抛 `IllegalArgumentException`**（空范围 ≠ 不限范围）。
- **Milvus 不可用必须 fail-fast**：`MilvusConfig.milvusClient()` 要把 `new MilvusClientV2(...)` **一起包进 try**（SDK 构造器默认 `enablePrecheck`，否则只出裸 `DEADLINE_EXCEEDED` 看不到自定义文案），抛带 uri/collection/原因的中文异常。**禁重蹈 ES 骨架静默空结果**。
- 启动补齐：`KbIndexMaintenanceRunner` 先 `reembedAll`(`AIOA_KB_REEMBED_ON_START`) 后 `backfill`(`AIOA_MILVUS_BACKFILL`)，默认全关。**首次切 milvus 前先开这两个**（现状：56 文档 / 854 切片，**已向量化仅 62 条**）。新接口 `GET /api/v1/kb/store`；`/kb/search` 参数化（mode/topk/threshold/docScope，不传逐字等价旧行为）。
- 依赖 `io.milvus:milvus-sdk-java:2.6.25`（父 pom `dependencyManagement`）。**本地 Maven 仓库不在 `~/.m2`**，真实路径 `D:\Program Files\develop\apache-maven-3.9.11\mvn_repo`（`mvnw help:evaluate settings.localRepository` 可查）。
- 部署：`deploy/docker-compose.yml` 新增 `etcd`/`milvus-minio`/`milvus`（profile=`milvus`，逐项对齐官方 standalone compose，**未自创环境变量**）+ 三个命名卷；`deploy/k8s/40-milvus.yaml` 已补同构清单（三组 Deployment/Service + 三个 PVC，**同镜像 tag / 同服务名 / 同环境变量** ⇒ 切档只改 `AIOA_KB_STORE`），`00-namespace-config.yaml` 补齐 22 键、`k8s/README.md` 补切换五步；`deploy/.env.*` §7 = 嵌入 8 键 + Milvus 13 键；`deploy/.env.example` 与 `deploy/ENV.md §3.7` 已从「预留/后端未读取」改为真实键清单（旧文案属事实错误）。**k8s 清单未对真机集群应用过**；`deploy/ops/prometheus.yml` 已补（原缺失，compose 却要挂载它 ⇒ Docker 会建成同名目录、Prometheus 起不来），scrape `milvus:9091/metrics` + `etcd:2379/metrics`；**server/agent 业务指标仍未接**（未引 `micrometer-registry-prometheus`，actuator 只暴露 `health` ⇒ `/actuator/prometheus` 必然 404）。
- ⚠️ **未实测**（本机无 Docker / `wsl.exe` 被安全策略拦 / 内网无 Milvus / Windows 无 milvus-lite 轮子）：活体 Milvus 集合自建 · 混合检索 · 回填 · `store=milvus` 下 V62 · 双档对齐 · compose 实际拉起。补验步骤见 `docs/32 §11.3`。**已实测**：全模块编译 SUCCESS、单测 26/26、`store=mysql` 全量 E2E 155/155、V62 mysql 档 25/25、fail-fast EXIT=1 且文案正确、compose YAML 解析 + profile 依赖检查、env 两份解析零报错。

## 7. 维度校验 + 本次部署档位（2026-09-21 补）

- **`provider.dims()` × `milvus.dims` 必须机器强制，不能只靠文档**（这是 §6 第 10 条「响应维度 vs 配置 dims」之外的**另一对**，此前完全没校验）。`MilvusConfig.assertDimsAgree(providerName, providerDims, milvusDims, collection)` 在**建集合之前**硬校验，不一致直接启动失败。**为什么必须硬**：不一致时后果完全静默——向量照写 MySQL，`MilvusKnowledgeStore.indexChunk` 维度不符 `log.debug`+return（Milvus 一条不收），检索侧 `EmbeddingProvider.cosine` 维度不符返回 0 ⇒ 接口全成功、永不命中。与 ES 骨架「静默空结果」同类（R8），只是藏在写入侧。同理 `indexChunk` 已升 `warn` 并写明「该切片存的是旧 provider 向量，需开 `AIOA_KB_REEMBED_ON_START` 重算」。
- `local` 的 256 维是**代码写死**（`EmbeddingProvider.local()` → `new LocalEmbeddingProvider(256, 2)`），**不受 `aioa.kb.embedding.dims` 影响** —— 只改那个键治不好，必须同时把 `milvus.dims` 设 256 **并换集合名**（维度不可改）。`MilvusDimGuardTest` 6 例锁死（含「local×512 必须失败」回归锁 + 文案必须含两个实际维度/换名提示/「静默」后果）。
- `provider=http` 时 `EmbeddingConfig` 启动探一次真实嵌入端点：**不通只打 ERROR、不阻断启动**（嵌入服务常与后端并行上线，避免把后端卡在与自身无关的上游上）。文案给出两条出路（起服务 / 改回 `local`）。
- **本次部署档位 = `store=milvus` + `provider=local` + `AIOA_MILVUS_DIMS=256` + 集合 `kb_chunk_v1_256`，不部署 Ollama**。`AIOA_MILVUS_BACKFILL` 从「可选」升级为**首次接入必做一次**（新集合是空的；不回填不报错，只是 Milvus 无历史数据 ⇒ 极易误判成没落库）。代价已写明：local 无语义，召回靠 `AIOA_MILVUS_ENABLE_BM25=true` 的关键词腿兜。
- **「数据是否真落进 Milvus」的权威判据 = `mode=vector` 命中且 `score` 非 null**（稠密腿只查 Milvus）。对照诊断：**同一条 q，`bm25` 有命中而 `vector` 空 ⇒ 典型「MySQL 有、Milvus 空」**（bm25 腿在集合 BM25 建失败时会回落 MySQL，所以 bm25 命中单独不足以证明 Milvus 有数据）。已写进手册 §6 第 9 条 + 排障表。
- **本机实跑验证（`store=mysql`/`provider=local`，:8080）**：上传 → `chunkCount=1` → `kb_chunk` 落 `provider=local / dims=256 / embedding=1024 字节`（=256×4 float32 小端）→ `mode=hybrid` 命中且 `score=0.1887`（说明稠密腿真算过）。⇒ **无 Ollama 时切片+向量化+检索在 mysql 档完全通**。
- ⚠️ **本机库数据量与旧记录不符**：§6 曾记「56 文档 / 854 切片、已向量化仅 62 条」，而 2026-09-21 实测 `aioa` 库 `kb_chunk` 仅 **17 行**且**全部有向量**（provider 全 `local`/256，无 NULL）。回填类验证前先按实测库判断，别照抄旧数字。

