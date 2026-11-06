package cn.aios.resource.store;

import cn.aios.resource.entity.KbChunk;
import cn.aios.resource.entity.KbDocument;
import cn.aios.resource.service.EmbeddingProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * MySQL 存储实现（默认，方案 P2）：文档正文 LONGTEXT + 切片 TEXT + 切片向量 BLOB。
 *
 * <p>检索为「关键词（n-gram 覆盖率）+ 向量（余弦）」双路召回，经 RRF（rank_constant=60）
 * 融合。向量由 {@link EmbeddingProvider} 产出并持久化到 kb_chunk.embedding，
 * 无向量数据（历史切片）时自动退化为纯关键词检索。</p>
 *
 * <p>切换 Milvus：{@code aios.kb.store=milvus} 启用 {@link MilvusKnowledgeStore}，
 * 本类自动让位（{@code @ConditionalOnProperty}），业务层零改动。</p>
 *
 * <p>2026-09-19（docs/32 Ph3）重构：文档/切片/向量落库被抽到 {@link KbRelationalDao}，
 * 关键词打分抽到 {@link KeywordScorer}，RRF 融合抽到 {@link RrfFusion}——
 * 目的是让 Milvus 档位的**兜底路径**与本体共用同一套口径，两种 store 的排序才能对齐。
 * <b>检索行为与重构前逐字等价</b>（同分、同序、同截断）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "aios.kb.store", havingValue = "mysql", matchIfMissing = true)
public class MysqlKnowledgeStore implements KnowledgeStore {

    /** RRF 融合常数（Elasticsearch 生产默认）。保留常量名以兼容外部引用。 */
    static final double RRF_K = RrfFusion.RRF_K;

    /** 聚合类问题最多置顶几块统计摘要（多于 2 块会挤占明细，反而更糟）。 */
    private static final int MAX_STATS_HITS = 2;

    private final KbRelationalDao dao;
    private final EmbeddingProvider embeddingProvider;

    @Override
    public String type() {
        return "mysql";
    }

    @Override
    public KbDocument saveDocument(KbDocument doc) {
        return dao.saveDocument(doc);
    }

    @Override
    public KbDocument updateDocument(KbDocument doc) {
        return dao.updateDocument(doc);
    }

    @Override
    public KbDocument findDocById(Long docId) {
        return dao.findDocById(docId);
    }

    @Override
    public void deleteDocument(Long docId) {
        dao.deleteDocument(docId);
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

    /**
     * 归一化检索模式：null/空白/认不出 一律退回 {@code hybrid}。
     *
     * <p>为什么必须兜底：认不出的模式会让「关键词」与「向量」两路都不打分，融合结果为空 ⇒
     * 恒返回 0 条，而调用方拿到的是 {@code ok:true, data:[]} —— 表现为「库里有资料却检索不到」。
     * 2026-11-06 实测踩过：工具入参没有 {@code mode} 时 {@code String.valueOf(null)} 得到的是
     * 字符串 {@code "null"}，正好落进这个盲区（docs/75）。</p>
     */
    static String normalizeMode(String mode) {
        if (mode == null || mode.isBlank()) {
            return "hybrid";
        }
        String m = mode.trim().toLowerCase(Locale.ROOT);
        if ("vector".equals(m) || "bm25".equals(m) || "hybrid".equals(m)) {
            return m;
        }
        log.warn("未知检索模式 '{}'，已退回 hybrid", mode);
        return "hybrid";
    }

    @Override
    public void saveEmbedding(Long chunkId, String content, float[] vector, String provider, int dims) {
        dao.saveEmbedding(chunkId, content, vector, provider, dims);
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String query, float[] queryVec,
                              int topK, double threshold, String mode, List<Long> docIdScope) {
        long tid = tenantId == null ? 0L : tenantId;
        int max = Math.max(1, topK);

        // 可见文档 + 知识库范围过滤（隔离口径来自 KbRelationalDao，与列表接口同源）
        List<Long> visible = dao.visibleDocIds(tid, userId);
        List<Long> scope = (docIdScope == null || docIdScope.isEmpty()) ? visible
                : docIdScope.stream().filter(visible::contains).toList();
        if (scope.isEmpty()) {
            return List.of();
        }

        String m = normalizeMode(mode);
        boolean wantVector = "vector".equals(m) || "hybrid".equals(m);
        boolean wantBm25 = "bm25".equals(m) || "hybrid".equals(m);

        List<KbChunk> candidates = dao.chunksOfDocs(tid, scope);

        // 双路打分
        Map<Long, Double> bm25Score = wantBm25 ? KeywordScorer.score(candidates, query) : Map.of();
        Map<Long, Double> vecScore = new HashMap<>();
        if (wantVector && queryVec != null) {
            for (KbChunk c : candidates) {
                float[] v = embeddingProvider.fromBytes(c.getEmbedding());
                if (v == null) {
                    continue;
                }
                double s = EmbeddingProvider.cosine(queryVec, v);
                if (s >= threshold) {
                    vecScore.put(c.getId(), s);
                }
            }
        }

        // RRF 融合：只按排名融合，规避关键词分与向量分数量纲不一致
        Map<Long, Double> fused = RrfFusion.fuse(List.of(bm25Score, vecScore));

        Map<Long, KbChunk> byId = new HashMap<>();
        for (KbChunk c : candidates) {
            byId.put(c.getId(), c);
        }

        // 组装命中并按融合分降序、截断
        List<Map.Entry<Long, KbHit>> ordered = new ArrayList<>();
        for (Map.Entry<Long, Double> e : fused.entrySet()) {
            KbChunk c = byId.get(e.getKey());
            if (c == null) {
                continue;
            }
            KbDocument doc = dao.findDocById(c.getDocId());
            if (doc == null) {
                continue;
            }
            Double vec = vecScore.get(c.getId());
            KbHit hit = new KbHit(doc.getId(), doc.getDocName(), c.getContent(), c.getChunkIndex(),
                    vec == null ? null : vec.floatValue());
            ordered.add(new AbstractMap.SimpleEntry<>(c.getId(), hit));
        }
        ordered.sort((a, b) -> Double.compare(
                fused.getOrDefault(b.getKey(), 0.0),
                fused.getOrDefault(a.getKey(), 0.0)));

        List<KbHit> hits = new ArrayList<>(ordered.size());
        // 单文档配额（docs/74 根因 4）：候选池是「全部可见切片」，一张 1241 行的大表
        // 会凭行数优势把另外几份文档整体挤出 topK —— 同时问 5 张名录时只见得到一张。
        // 仅在候选确实来自 ≥3 份文档时生效，否则单文档问答会被无谓截断。
        long distinctDocs = ordered.stream()
                .map(e -> e.getValue().docId()).filter(java.util.Objects::nonNull).distinct().count();
        int docCap = distinctDocs >= 3 ? Math.max(2, (max + 1) / 2) : max;
        Map<Long, Integer> perDoc = new HashMap<>();
        // 聚合意图 → 统计摘要块置顶注入：分数上与数据行块同分，靠排序拿第一是碰运气，
        // 必须按意图显式优先（docs/74 P0-2）。
        // 配额口径（旧注释写「不占普通配额」，与实现不符 —— B3）：摘要是**占** max 的，
        // 最多 MAX_STATS_HITS=2 条，余下 max-2 条才轮到数据行。不做「额外追加」的理由是
        // hits 就是回给模型的最终列表，多给一块就多一份 token，max 是硬预算。
        if (QueryIntent.aggregate(query)) {
            for (Map.Entry<Long, KbHit> e : ordered) {
                if (hits.size() >= MAX_STATS_HITS) {
                    break;
                }
                if (isStats(e.getValue())) {
                    hits.add(e.getValue());
                }
            }
        }
        for (Map.Entry<Long, KbHit> e : ordered) {
            if (hits.size() >= max) {
                break;
            }
            KbHit h = e.getValue();
            if (hits.contains(h)) {
                continue;
            }
            long docId = h.docId() == null ? -1L : h.docId();
            if (perDoc.getOrDefault(docId, 0) >= docCap) {
                continue;
            }
            perDoc.merge(docId, 1, Integer::sum);
            hits.add(h);
        }
        return hits;
    }

    /** 是否是统计摘要切片（入库时由 {@code MarkdownTable.statsText} 生成，带固定前缀）。 */
    private static boolean isStats(KbHit hit) {
        return hit != null && hit.snippet() != null
                && hit.snippet().startsWith(cn.aios.resource.support.MarkdownTable.STATS_MARK);
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String keyword, int limit) {
        return search(tenantId, userId, keyword, embeddingProvider.embed(keyword),
                limit, 0.0, "bm25", null);
    }
}
