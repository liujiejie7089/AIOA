# 专家配置与 RAG 全链路 自检清单（P1–P7）

> 版本：V27–V28 迁移 · 验收日期：2026-09-10
> 覆盖：配置内核、RAG 全链路、工具中心、数据分析师专家闭环、通用模板、参数生效、管理端三页。

## 一、交付物清单

| 编号 | 交付项 | 关键文件 | 状态 |
|------|--------|----------|------|
| P1 | 配置内核 | `V27__expert_config_and_kb_vector.sql`、`ExpertConfig`、`ExpertConfigService`、`ExpertConfigController` | ✅ |
| P2 | RAG 全链路 | `KbDocument/KbChunk`、`EmbeddingProvider`、`MysqlKnowledgeStore`、`KbService`、`KbController` | ✅ |
| P3 | 工具中心 | `SqlQueryToolService`、`ToolGatewayService`、`seed_biz_dataset.py`、`V28__biz_dataset.sql` | ✅ |
| P4 | 数据分析师专家闭环 | `agent/app/core/intent_router.py`、`mock_llm.py`、`sandbox.py` | ✅ |
| P5 | 通用专家模板 | `seed_expert_templates.py`（6 领域） | ✅ |
| P6 | 参数生效自检 | `scripts/verify_config_effect.py` | ✅ |
| P7 | 管理端三页 | `ExpertConfigView.vue`、`ToolRegistryView.vue`、`KbIngestView.vue` | ✅ |

## 二、配置内核（P1）验收

- [x] `expert_config` 表含 `tenant_id / scope_type / scope_id / expert_key / config_json / created_by` 唯一键 `(tenant_id, scope_type, scope_id, expert_key)`。
- [x] 分层覆盖：`GLOBAL → TENANT → USER → EXPERT` 逐层 merge，`resolve` 返回每个字段的 `sources`（来源层级）。
- [x] 支持 `merge=false` 整体替换 与 `merge=true` 增量合并。
- [x] `scopeType=*`（通配）与 `expertKey=*`（通配）占位匹配。
- [x] **关键坑已修**：`ExpertConfig` 原用 `@TableLogic` 软删，`save` 里 `selectOne` 查不到软删残留 → 唯一键冲突 500。已改为物理删除（去掉 `@TableLogic`），并在 `save` 前物理清理同键残留。

## 三、RAG 全链路（P2）验收

- [x] 上传文档（`POST /api/v1/kb/documents`，字段 `name`）→ 解析 → 切片 → 向量化入库（`kb_chunk.embedding`）。
- [x] 混合检索 `GET /api/v1/kb/search?q=` 命中正确（BM25 关键词路径 + 向量语义路径）。
- [x] 租户隔离正确注入（跨租户文档不可见）。
- [x] 流水线三态：`wait → parsing → ok / error`，失败可重试。
- [x] `DocView` 补齐 `stage/progress/retryCount` 字段（入库流水线可视化数据源）。
- [x] 存储层抽象为可替换接口（`KnowledgeStore` / `MysqlKnowledgeStore`）。

## 四、工具中心（P3）验收

- [x] 企业数据集 `biz_sales_order / biz_product` 灌入（`seed_biz_dataset.py`）。
- [x] `sql_query` 工具：真实 JOIN 聚合查询返回品类销售排行，租户隔离正确注入。
- [x] `sandbox.py`（Python 沙箱）与 `mock_llm.py`（数据分析师 mock 推理）。

## 五、数据分析师专家闭环（P4）验收

- [x] `intent_router.py` 意图路由：SQL 查询 / 检索 / 通用三类意图分发。
- [x] 工具循环：路由 → 工具调用 → 结果汇总 → 会话回写。

## 六、通用专家模板（P5）验收

- [x] `seed_expert_templates.py` 6 领域模板可导入（租户级）。
- [x] 租户导入后 `resolve` 正确返回租户覆盖配置。

## 七、参数生效 A/B 自检（P6）验收

- [x] `verify_config_effect.py` 11/11 全通过。
- [x] 验证维度：`temperature / enabled / topK / threshold / retrievalMode / tools / kbScope / visibleScope` 等参数真实生效并可回退默认。

## 八、管理端三页（P7）验收

- [x] `ExpertConfigView.vue`（专家配置）—— 路由 `/experts`，菜单「专家配置」。
- [x] `ToolRegistryView.vue`（业务工具）—— 路由 `/tools`，菜单「业务工具」，含 SQL 工具测试执行。
- [x] `KbIngestView.vue`（入库流水线）—— 状态/阶段/进度/重试展示。
- [x] 前端 `vue-tsc --noEmit` 零类型错误。
- [x] 浏览器冒烟：菜单两新入口显示，业务工具页正常渲染工具列表，无 console 错误。

## 九、已知边界与遗留

- 向量语义检索当前为「可替换实现」：默认 MySQL 余弦（或占位），生产可换 Milvus/Qdrant。
- 数据分析师 LLM 为 mock 实现，接入真实 DeepSeek 后闭环不变（工具循环已打通）。
- 管理端入库流水线页依赖 KB 文档接口的 `stage/progress` 字段（已补齐）。
