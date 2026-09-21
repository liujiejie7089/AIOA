package cn.aioa.resource.store;

import cn.aioa.resource.config.KbProperties;
import cn.aioa.resource.config.MilvusConfig;
import cn.aioa.resource.entity.KbChunk;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.service.EmbeddingProvider;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.common.ConsistencyLevel;
import io.milvus.v2.common.IndexParam;
import io.milvus.v2.service.vector.request.AnnSearchReq;
import io.milvus.v2.service.vector.request.DeleteReq;
import io.milvus.v2.service.vector.request.HybridSearchReq;
import io.milvus.v2.service.vector.request.SearchReq;
import io.milvus.v2.service.vector.request.UpsertReq;
import io.milvus.v2.service.vector.request.data.EmbeddedText;
import io.milvus.v2.service.vector.request.data.FloatVec;
import io.milvus.v2.service.vector.request.ranker.RRFRanker;
import io.milvus.v2.service.vector.response.SearchResp;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Milvus 向量存储实现（docs/32 Ph2/Ph3，{@code aioa.kb.store=milvus} 时启用）。
 *
 * <h3>职责切分：Milvus 只做它擅长的那一件事</h3>
 * <ul>
 *   <li><b>MySQL 是权威底座</b>（{@link KbRelationalDao}）：文档元数据、可见范围、切片正文、
 *       向量 BLOB 全部照旧落 MySQL。文档列表 / 重命名 / 改可见范围 / 软删都是高频**关系型**操作，
 *       放进向量库得不偿失（决策 D4 范围注释 / R9）；</li>
 *   <li><b>Milvus 是向量索引副本</b>：只承载「检索」所需的最小字段（id / 向量 / 正文 / 过滤元数据），
 *       全部可从 MySQL 重建。回滚 = {@code AIOA_KB_STORE=mysql}（零数据迁移）；
 *       索引损坏 = 跑一次 {@link #backfill()}。</li>
 * </ul>
 *
 * <h3>检索形态</h3>
 * <table border="1">
 *   <tr><th>mode</th><th>服务端支持原生 BM25 且 threshold≤0</th><th>其它情况</th></tr>
 *   <tr><td>vector</td><td colspan="2">Milvus dense（HNSW/COSINE）+ 阈值过滤</td></tr>
 *   <tr><td>bm25</td><td>Milvus sparse（BM25 Function）</td><td>MySQL 关键词兜底（{@link KeywordScorer}）</td></tr>
 *   <tr><td>hybrid</td><td>Milvus {@code hybrid_search} + {@code RRFRanker(60)}（服务端融合，一次 RPC）</td>
 *       <td>两腿分别检索 → 客户端 {@link RrfFusion}（与 MySQL 档位同一套口径）</td></tr>
 * </table>
 * <b>为什么 threshold&gt;0 时不用服务端融合</b>：Milvus 的 {@code hybrid_search} 只回传融合分，
 * 拿不到「向量腿的分」，阈值就没法只作用在向量召回上（而 MySQL 档位是这么做的）。
 * 与其让参数「配了不生效」，不如在阈值非默认时走分腿 + 客户端融合，保证
 * {@code topK / threshold / mode / kbScope} 四个参数**在两个档位下语义一致**。
 *
 * <h3>失败语义（决策 D6）</h3>
 * <ul>
 *   <li><b>写路径</b>：Milvus 不可用时**只告警不阻断**——MySQL 已落库，索引副本可由回填重建。
 *       与现状 {@code KbService.embedAll} 的 try/catch 语义一致（风险 R6）；</li>
 *   <li><b>读路径</b>：Milvus 报错**向上抛**，不做「静默返回空列表」。
 *       静默空结果是 {@code ElasticKnowledgeStore} 的坑：检索无声失效、没人发现（风险 R8）。
 *       宁可让调用方看到错误，也不要让它以为「知识库里没有相关内容」。</li>
 * </ul>
 *
 * <h3>与 D4「免回查」的一处有意偏离</h3>
 * 命中回填 {@code docName} 时**仍然批量回查一次 MySQL**（{@link KbRelationalDao#docsByIds}）。
 * 理由是正确性：文档删除后 Milvus 行可能还在（删除是两处操作），
 * 若只看 Milvus 就会把**已删文档的正文**返回给用户。MySQL 查不到即视为已删、直接丢弃命中。
 * 代价是每次检索多一次按主键的批量查询（≤ topK 行），可接受。
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "aioa.kb.store", havingValue = "milvus")
public class MilvusKnowledgeStore implements KnowledgeStore {

    /** 客户端融合时单腿过取倍数（每腿取 max×N，再融合截断到 max）。 */
    private static final int LEG_OVER_FETCH = 4;

    /** 客户端融合时单腿过取上限。 */
    private static final int LEG_OVER_FETCH_CAP = 200;

    private final KbRelationalDao dao;
    private final EmbeddingProvider embeddingProvider;
    private final MilvusClientV2 client;
    private final MilvusConfig.CollectionInfo info;
    private final KbProperties props;

    @Override
    public String type() {
        return "milvus";
    }

    // ---------- 文档 / 切片：一律以 MySQL 为准 ----------

    @Override
    public KbDocument saveDocument(KbDocument doc) {
        return dao.saveDocument(doc);
    }

    @Override
    public KbDocument updateDocument(KbDocument doc) {
        KbDocument saved = dao.updateDocument(doc);
        // 可见范围 / 文档名可能变了，Milvus 里的副本必须同步——
        // scope 是检索过滤条件，不同步会导致「改成租户共享后别人检不到」这种静默错误。
        try {
            resyncDocument(doc.getId());
        } catch (Exception e) {
            log.warn("Milvus 元数据同步失败（MySQL 已更新，可由回填重建）docId={}: {}", doc.getId(), e.getMessage());
        }
        return saved;
    }

    @Override
    public KbDocument findDocById(Long docId) {
        return dao.findDocById(docId);
    }

    @Override
    public void deleteDocument(Long docId) {
        KbDocument doc = dao.findDocById(docId);
        dao.deleteDocument(docId);
        if (doc == null) {
            return;
        }
        try {
            client.delete(DeleteReq.builder()
                    .collectionName(info.name())
                    // 必须带 tenant_id：它既是隔离条件，也是分区裁剪条件
                    .filter(MilvusFilter.docInTenant(doc.getTenantId() == null ? 0L : doc.getTenantId(), docId))
                    .consistencyLevel(ConsistencyLevel.STRONG)
                    .build());
        } catch (Exception e) {
            log.warn("Milvus 删除失败（MySQL 已删除，检索侧仍按「MySQL 查不到即丢弃」保证不可见）docId={}: {}",
                    docId, e.getMessage());
        }
    }

    @Override
    public List<KbDocument> listVisible(Long tenantId, Long userId) {
        return dao.listVisible(tenantId, userId);
    }

    @Override
    public List<KbDocument> listTenant(Long tenantId) {
        return dao.listTenant(tenantId);
    }

    @Override
    public int replaceChunks(KbDocument doc, List<String> chunks) {
        return dao.replaceChunks(doc, chunks);
    }

    @Override
    public void saveEmbedding(Long chunkId, String content, float[] vector, String provider, int dims) {
        // 1) 先落 MySQL（权威）；2) 再 upsert Milvus（副本，失败只告警）
        dao.saveEmbedding(chunkId, content, vector, provider, dims);
        try {
            indexChunk(chunkId, content, vector);
        } catch (Exception e) {
            log.warn("Milvus 索引写入失败（已落 MySQL，可由回填重建）chunkId={}: {}", chunkId, e.getMessage());
        }
    }

    // ---------- 检索 ----------

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String query, float[] queryVec,
                              int topK, double threshold, String mode, List<Long> docIdScope) {
        long tid = tenantId == null ? 0L : tenantId;
        long uid = userId == null ? 0L : userId;
        int max = Math.max(1, topK);
        String m = mode == null ? "hybrid" : mode.toLowerCase(Locale.ROOT);

        // 可见性 + 知识库范围：与 MySQL 档位走同一个 dao，保证隔离口径同源
        List<Long> visible = dao.visibleDocIds(tid, uid);
        List<Long> scope = (docIdScope == null || docIdScope.isEmpty()) ? visible
                : docIdScope.stream().filter(visible::contains).distinct().toList();
        if (scope.isEmpty()) {
            return List.of();
        }
        List<Long> restricted = (docIdScope == null || docIdScope.isEmpty()) ? null : scope;
        String expr = MilvusFilter.visibility(tid, uid, restricted);

        boolean wantVector = "vector".equals(m) || "hybrid".equals(m);
        boolean wantKeyword = "bm25".equals(m) || "hybrid".equals(m);
        boolean denseUsable = wantVector && queryVec != null && queryVec.length > 0;

        // 快路：服务端原生混合检索（dense ⊕ BM25 → RRFRanker(60)），一次 RPC
        if (denseUsable && wantKeyword && info.bm25() && threshold <= 0) {
            List<Row> rows = nativeHybrid(expr, query, queryVec, max);
            return toHits(rows, max, denseScoreIndex(rows));
        }

        int legLimit = legLimit(max);

        // 稠密腿（带阈值，与 MySQL 档位「s >= threshold」一致）
        List<Row> denseRows = List.of();
        if (denseUsable) {
            denseRows = denseRows(expr, queryVec, legLimit, threshold);
        }

        // 关键词腿：优先 Milvus 原生 BM25；集合没有稀疏列时退回 MySQL 关键词打分
        List<Row> keywordRows = List.of();
        if (wantKeyword) {
            keywordRows = info.bm25()
                    ? sparseRows(expr, query, legLimit)
                    : mysqlKeywordRows(tid, scope, query, legLimit);
        }

        return fuseAndBuild(denseRows, keywordRows, max);
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String keyword, int limit) {
        return search(tenantId, userId, keyword, embeddingProvider.embed(keyword),
                limit, 0.0, "bm25", null);
    }

    // ---------- 索引写入 ----------

    /** 单个切片 upsert 到 Milvus（以 kb_chunk.id 为主键，天然幂等）。 */
    private void indexChunk(Long chunkId, String content, float[] vector) {
        if (vector == null || vector.length == 0) {
            return;
        }
        if (info.dims() > 0 && vector.length != info.dims()) {
            // 走到这里说明该切片存的是**旧 provider 的向量**（集合维度已由 MilvusConfig 与当前 provider 对齐）。
            // 曾经是 debug 级：结果是「Milvus 一条都不进、日志上什么都看不到」——静默失效，
            // 与本类读路径「不打静默空结果」的立场自相矛盾。改 warn 并给出修复动作。
            log.warn("切片向量维度 {} 与集合 {} 的 {} 不一致，跳过索引（该切片存的是旧 provider 的向量，"
                            + "需开 AIOA_KB_REEMBED_ON_START=true 重算一次）chunkId={}",
                    vector.length, info.name(), info.dims(), chunkId);
            return;
        }
        KbChunk c = dao.findChunk(chunkId);
        if (c == null) {
            return;
        }
        KbDocument doc = dao.findDocById(c.getDocId());
        if (doc == null) {
            return;
        }
        upsert(List.of(row(c, doc, content, vector)));
    }

    /**
     * 把某文档在 Milvus 的副本按 MySQL 现状整体重刷（元数据变更 / 回填共用）。
     *
     * @return 实际写入的切片数
     */
    private int resyncDocument(Long docId) {
        KbDocument doc = dao.findDocById(docId);
        if (doc == null) {
            return 0;
        }
        List<JsonObject> rows = new ArrayList<>();
        for (KbChunk c : dao.chunksOfDoc(docId)) {
            float[] v = embeddingProvider.fromBytes(c.getEmbedding());
            if (v == null || v.length == 0) {
                continue;
            }
            if (info.dims() > 0 && v.length != info.dims()) {
                continue;
            }
            rows.add(row(c, doc, c.getContent(), v));
        }
        if (rows.isEmpty()) {
            return 0;
        }
        upsert(rows);
        return rows.size();
    }

    /**
     * 从 MySQL 全量重建 Milvus 索引（docs/32：索引副本可随时重建）。
     *
     * <p>按主键游标分批扫描 {@code kb_chunk}，跳过无向量或维度不符的行。
     * 只 upsert、**不删**——真正「删干净重建」应先 {@code dropCollection} 再重跑。</p>
     *
     * @return 写入条数
     */
    public int backfill() {
        int limit = Math.max(1, props.getMilvus().getBackfillBatchSize());
        long cursor = 0L;
        int total = 0;
        int skippedNoVector = 0;
        int skippedDim = 0;
        Map<Long, KbDocument> docCache = new HashMap<>();
        while (true) {
            List<KbChunk> batch = dao.chunksAfterId(cursor, limit);
            if (batch.isEmpty()) {
                break;
            }
            List<JsonObject> rows = new ArrayList<>(batch.size());
            for (KbChunk c : batch) {
                cursor = Math.max(cursor, c.getId());
                KbDocument doc = docCache.computeIfAbsent(c.getDocId(), dao::findDocById);
                if (doc == null) {
                    continue;
                }
                float[] v = embeddingProvider.fromBytes(c.getEmbedding());
                if (v == null || v.length == 0) {
                    skippedNoVector++;
                    continue;
                }
                if (info.dims() > 0 && v.length != info.dims()) {
                    skippedDim++;
                    continue;
                }
                rows.add(row(c, doc, c.getContent(), v));
            }
            if (!rows.isEmpty()) {
                upsert(rows);
                total += rows.size();
            }
            if (batch.size() < limit) {
                break;
            }
        }
        log.info("Milvus 回填完成：写入={} 跳过(无向量)={} 跳过(维度不符)={} collection={}",
                total, skippedNoVector, skippedDim, info.name());
        return total;
    }

    private void upsert(List<JsonObject> rows) {
        // 分批，避免单次 RPC 过大
        int batch = Math.max(1, props.getMilvus().getBackfillBatchSize());
        for (int i = 0; i < rows.size(); i += batch) {
            List<JsonObject> slice = rows.subList(i, Math.min(rows.size(), i + batch));
            client.upsert(UpsertReq.builder()
                    .collectionName(info.name())
                    .data(slice)
                    .build());
        }
    }

    private JsonObject row(KbChunk c, KbDocument doc, String content, float[] vector) {
        JsonObject row = new JsonObject();
        row.addProperty(MilvusConfig.F_PK, c.getId());
        JsonArray arr = new JsonArray(vector.length);
        for (float v : vector) {
            arr.add(v);
        }
        row.add(MilvusConfig.F_VECTOR, arr);
        row.addProperty(MilvusConfig.F_CONTENT, clip(content, 8000));
        row.addProperty(MilvusConfig.F_TENANT, c.getTenantId() == null ? 0L : c.getTenantId());
        row.addProperty(MilvusConfig.F_USER, c.getUserId() == null ? 0L : c.getUserId());
        row.addProperty(MilvusConfig.F_DOC, c.getDocId());
        row.addProperty(MilvusConfig.F_CHUNK_INDEX, c.getChunkIndex() == null ? 0 : c.getChunkIndex());
        row.addProperty(MilvusConfig.F_SCOPE, doc.getScope() == null ? "PERSONAL" : doc.getScope());
        row.addProperty(MilvusConfig.F_DOC_NAME, clip(doc.getDocName(), 500));
        return row;
    }

    // ---------- 检索内部实现 ----------

    /** 服务端原生混合检索：dense ⊕ BM25 → RRFRanker(60)，一次 RPC。 */
    private List<Row> nativeHybrid(String expr, String query, float[] queryVec, int max) {
        int legLimit = legLimit(max);
        IndexParam.MetricType metric = metric();

        AnnSearchReq dense = AnnSearchReq.builder()
                .vectorFieldName(MilvusConfig.F_VECTOR)
                .vectors(List.of(new FloatVec(queryVec)))
                .filter(expr).expr(expr)
                .topK(legLimit).limit(legLimit)
                .metricType(metric)
                .build();
        AnnSearchReq sparse = AnnSearchReq.builder()
                .vectorFieldName(MilvusConfig.F_SPARSE)
                .vectors(List.of(new EmbeddedText(query == null ? "" : query)))
                .filter(expr).expr(expr)
                .topK(legLimit).limit(legLimit)
                .metricType(IndexParam.MetricType.BM25)
                .build();

        SearchResp resp = client.hybridSearch(HybridSearchReq.builder()
                .collectionName(info.name())
                .searchRequests(List.of(dense, sparse))
                .ranker(new RRFRanker((int) RrfFusion.RRF_K))
                .topK(max)
                .outFields(outFields())
                .consistencyLevel(ConsistencyLevel.STRONG)
                .build());
        return toRows(resp, Double.NEGATIVE_INFINITY);
    }

    /** 稠密召回（COSINE，带阈值过滤）。 */
    private List<Row> denseRows(String expr, float[] queryVec, int limit, double threshold) {
        Map<String, Object> params = Map.of("ef", Math.max(64, limit));
        SearchResp resp = client.search(SearchReq.builder()
                .collectionName(info.name())
                .annsField(MilvusConfig.F_VECTOR)
                .data(List.of(new FloatVec(queryVec)))
                .filter(expr)
                .topK(limit)
                .outputFields(outFields())
                .metricType(metric())
                .searchParams(params)
                .consistencyLevel(ConsistencyLevel.STRONG)
                .build());
        return toRows(resp, threshold);
    }

    /** 稀疏（BM25）召回。查询串直接交给服务端的 BM25 Function，无需客户端分词。 */
    private List<Row> sparseRows(String expr, String query, int limit) {
        SearchResp resp = client.search(SearchReq.builder()
                .collectionName(info.name())
                .annsField(MilvusConfig.F_SPARSE)
                .data(List.of(new EmbeddedText(query == null ? "" : query)))
                .filter(expr)
                .topK(limit)
                .outputFields(outFields())
                .metricType(IndexParam.MetricType.BM25)
                .consistencyLevel(ConsistencyLevel.STRONG)
                .build());
        return toRows(resp, Double.NEGATIVE_INFINITY);
    }

    /** 关键词兜底腿：集合没有 BM25 稀疏列时，用 MySQL 切片 + 与 MySQL 档位完全相同的打分口径。 */
    private List<Row> mysqlKeywordRows(long tenantId, List<Long> scope, String query, int limit) {
        List<KbChunk> chunks = dao.chunksOfDocs(tenantId, scope);
        Map<Long, Double> scores = KeywordScorer.score(chunks, query);
        if (scores.isEmpty()) {
            return List.of();
        }
        Set<Long> docIds = new HashSet<>();
        for (KbChunk c : chunks) {
            docIds.add(c.getDocId());
        }
        Map<Long, KbDocument> docs = dao.docsByIds(docIds);
        List<Row> rows = new ArrayList<>();
        for (KbChunk c : chunks) {
            Double s = scores.get(c.getId());
            KbDocument doc = docs.get(c.getDocId());
            if (s == null || doc == null) {
                continue;
            }
            rows.add(new Row(c.getId(), c.getDocId(), c.getChunkIndex() == null ? 0 : c.getChunkIndex(),
                    c.getContent(), doc.getDocName(), s.floatValue()));
        }
        rows.sort(Comparator.comparingDouble(Row::score).reversed());
        return rows.size() > limit ? new ArrayList<>(rows.subList(0, limit)) : rows;
    }

    /** 两腿融合 + 组装命中（口径与 MySQL 档位一致：score 只在有稠密腿时给出）。 */
    private List<KbHit> fuseAndBuild(List<Row> denseRows, List<Row> keywordRows, int max) {
        if (denseRows.isEmpty() && keywordRows.isEmpty()) {
            return List.of();
        }
        if (keywordRows.isEmpty()) {
            List<Row> sorted = new ArrayList<>(denseRows);
            sorted.sort(Comparator.comparingDouble(Row::score).reversed());
            return toHits(sorted, max, null);
        }
        if (denseRows.isEmpty()) {
            return toHits(keywordRows, max, null);
        }
        Map<Long, Double> keywordLeg = new LinkedHashMap<>();
        for (Row r : keywordRows) {
            keywordLeg.put(r.chunkId(), (double) r.score());
        }
        Map<Long, Double> denseLeg = new LinkedHashMap<>();
        for (Row r : denseRows) {
            denseLeg.put(r.chunkId(), (double) r.score());
        }
        Map<Long, Double> fused = RrfFusion.fuse(List.of(keywordLeg, denseLeg));

        Map<Long, Row> byId = new HashMap<>();
        for (Row r : denseRows) {
            byId.put(r.chunkId(), r);
        }
        for (Row r : keywordRows) {
            byId.putIfAbsent(r.chunkId(), r);
        }
        List<Long> ordered = RrfFusion.topK(fused, max);
        List<Row> rows = new ArrayList<>(ordered.size());
        for (Long id : ordered) {
            Row r = byId.get(id);
            if (r != null) {
                rows.add(r);
            }
        }
        return toHits(rows, max, denseScoreIndex(denseRows));
    }

    private Map<Long, Float> denseScoreIndex(List<Row> denseRows) {
        Map<Long, Float> out = new HashMap<>();
        for (Row r : denseRows) {
            out.put(r.chunkId(), r.score());
        }
        return out;
    }

    /**
     * Milvus 结果 → 命中（带权威性校正）。
     *
     * @param denseScores 稠密腿分数；null 表示本次检索没有稠密腿（score 落 null，与 MySQL 档位一致）
     */
    private List<KbHit> toHits(List<Row> rows, int max, Map<Long, Float> denseScores) {
        if (rows.isEmpty()) {
            return List.of();
        }
        Set<Long> docIds = new HashSet<>();
        for (Row r : rows) {
            docIds.add(r.docId());
        }
        // 回查 MySQL：文档已删 / 已越权 → 命中作废（Milvus 行可能滞后）
        Map<Long, KbDocument> docs = dao.docsByIds(docIds);

        List<KbHit> hits = new ArrayList<>(Math.min(max, rows.size()));
        for (Row r : rows) {
            if (hits.size() >= max) {
                break;
            }
            KbDocument doc = docs.get(r.docId());
            if (doc == null) {
                log.debug("丢弃命中：MySQL 中已不存在该文档（Milvus 副本滞后）docId={} chunkId={}", r.docId(), r.chunkId());
                continue;
            }
            Float score = denseScores == null ? null : denseScores.get(r.chunkId());
            hits.add(new KbHit(doc.getId(), doc.getDocName(), r.content(), r.chunkIndex(), score));
        }
        return hits;
    }

    /** Milvus 统一响应 → 内部行模型（阈值只作用在有分的腿上）。 */
    private List<Row> toRows(SearchResp resp, double threshold) {
        if (resp == null || resp.getSearchResults() == null || resp.getSearchResults().isEmpty()) {
            return List.of();
        }
        List<SearchResp.SearchResult> list = resp.getSearchResults().get(0);
        if (list == null || list.isEmpty()) {
            return List.of();
        }
        List<Row> rows = new ArrayList<>(list.size());
        for (SearchResp.SearchResult sr : list) {
            Map<String, Object> e = sr.getEntity();
            if (e == null) {
                continue;
            }
            float score = sr.getScore() == null ? 0f : sr.getScore();
            if (score < threshold) {
                continue;
            }
            rows.add(new Row(longOf(e.get(MilvusConfig.F_PK)),
                    longOf(e.get(MilvusConfig.F_DOC)),
                    (int) longOf(e.get(MilvusConfig.F_CHUNK_INDEX)),
                    strOf(e.get(MilvusConfig.F_CONTENT)),
                    strOf(e.get(MilvusConfig.F_DOC_NAME)),
                    score));
        }
        return rows;
    }

    private List<String> outFields() {
        return List.of(MilvusConfig.F_PK, MilvusConfig.F_DOC, MilvusConfig.F_CHUNK_INDEX,
                MilvusConfig.F_CONTENT, MilvusConfig.F_DOC_NAME);
    }

    private IndexParam.MetricType metric() {
        return MilvusConfig.metricOf(props.getMilvus().getMetricType());
    }

    private static int legLimit(int max) {
        return Math.min(LEG_OVER_FETCH_CAP, Math.max(max * LEG_OVER_FETCH, max + 16));
    }

    private static long longOf(Object o) {
        if (o == null) {
            return 0L;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(o.toString().trim());
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    private static String strOf(Object o) {
        return o == null ? null : o.toString();
    }

    private static String clip(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max);
    }

    /** 内部行模型：一条召回的切片。 */
    private record Row(long chunkId, long docId, int chunkIndex, String content, String docName, float score) {
    }
}
