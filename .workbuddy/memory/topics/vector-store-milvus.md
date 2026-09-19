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

