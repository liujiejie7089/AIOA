package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbChunk;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.mapper.KbChunkMapper;
import cn.aioa.resource.mapper.KbDocumentMapper;
import cn.aioa.resource.service.EmbeddingProvider;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
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
 * <p>切换 Elasticsearch：{@code aioa.kb.store=elasticsearch} 启用
 * {@link ElasticKnowledgeStore}，本类自动让位（@ConditionalOnProperty），业务层零改动。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "aioa.kb.store", havingValue = "mysql", matchIfMissing = true)
public class MysqlKnowledgeStore implements KnowledgeStore {

    /** RRF 融合常数（Elasticsearch 生产默认）。 */
    static final double RRF_K = 60.0;

    private final KbDocumentMapper kbDocumentMapper;
    private final KbChunkMapper kbChunkMapper;
    private final EmbeddingProvider embeddingProvider;

    @Override
    public String type() {
        return "mysql";
    }

    @Override
    public KbDocument saveDocument(KbDocument doc) {
        kbDocumentMapper.insert(doc);
        return doc;
    }

    @Override
    public KbDocument updateDocument(KbDocument doc) {
        kbDocumentMapper.updateById(doc);
        return doc;
    }

    @Override
    public KbDocument findDocById(Long docId) {
        return docId == null ? null : kbDocumentMapper.selectById(docId);
    }

    @Override
    public void deleteDocument(Long docId) {
        kbChunkMapper.delete(new LambdaQueryWrapper<KbChunk>().eq(KbChunk::getDocId, docId));
        kbDocumentMapper.deleteById(docId);
    }

    @Override
    public List<KbDocument> listVisible(Long tenantId, Long userId) {
        long tid = tenantId == null ? 0L : tenantId;
        long uid = userId == null ? 0L : userId;
        return kbDocumentMapper.selectList(new LambdaQueryWrapper<KbDocument>()
                .eq(KbDocument::getTenantId, tid)
                .and(w -> w.eq(KbDocument::getUserId, uid)
                        .or().eq(KbDocument::getUserId, 0L)
                        .or().eq(KbDocument::getScope, KbDocument.SCOPE_TENANT))
                .orderByDesc(KbDocument::getCreatedAt));
    }

    @Override
    public List<KbDocument> listTenant(Long tenantId) {
        return kbDocumentMapper.selectList(new LambdaQueryWrapper<KbDocument>()
                .eq(KbDocument::getTenantId, tenantId == null ? 0L : tenantId)
                .orderByDesc(KbDocument::getCreatedAt));
    }

    @Override
    public int replaceChunks(KbDocument doc, List<String> chunks) {
        // 重跑入库先清旧切片，避免重复命中（幂等）
        kbChunkMapper.delete(new LambdaQueryWrapper<KbChunk>().eq(KbChunk::getDocId, doc.getId()));
        int i = 0;
        for (String c : chunks) {
            KbChunk chunk = new KbChunk();
            chunk.setTenantId(doc.getTenantId());
            chunk.setDocId(doc.getId());
            chunk.setUserId(doc.getUserId());
            chunk.setChunkIndex(i++);
            chunk.setContent(c);
            chunk.setCreatedAt(LocalDateTime.now());
            kbChunkMapper.insert(chunk);
        }
        return i;
    }

    @Override
    public void saveEmbedding(Long chunkId, String content, float[] vector, String provider, int dims) {
        KbChunk chunk = kbChunkMapper.selectById(chunkId);
        if (chunk == null) {
            return;
        }
        chunk.setEmbedding(embeddingProvider.toBytes(vector));
        chunk.setEmbeddingProvider(provider);
        chunk.setEmbeddingDims(dims);
        chunk.setEmbeddingAt(LocalDateTime.now());
        kbChunkMapper.updateById(chunk);
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String query, float[] queryVec,
                              int topK, double threshold, String mode, List<Long> docIdScope) {
        long tid = tenantId == null ? 0L : tenantId;
        int max = Math.max(1, topK);

        // 可见文档 + 知识库范围过滤
        List<Long> visible = listVisible(tid, userId).stream().map(KbDocument::getId).toList();
        List<Long> scope = (docIdScope == null || docIdScope.isEmpty()) ? visible
                : docIdScope.stream().filter(visible::contains).toList();
        if (scope.isEmpty()) {
            return List.of();
        }

        String m = mode == null ? "hybrid" : mode.toLowerCase(Locale.ROOT);
        boolean wantVector = "vector".equals(m) || "hybrid".equals(m);
        boolean wantBm25 = "bm25".equals(m) || "hybrid".equals(m);

        List<KbChunk> candidates = kbChunkMapper.selectList(new LambdaQueryWrapper<KbChunk>()
                .eq(KbChunk::getTenantId, tid)
                .in(KbChunk::getDocId, scope));

        // 双路打分
        Map<Long, Double> bm25Score = wantBm25 ? bm25(candidates, query) : Map.of();
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
        Map<Long, Double> fused = new HashMap<>();
        addRrf(fused, rankBy(bm25Score));
        addRrf(fused, rankBy(vecScore));

        // 组装命中并按融合分降序、截断
        List<KbHit> hits = new ArrayList<>();
        for (Map.Entry<Long, Double> e : fused.entrySet()) {
            KbChunk c = candidates.stream().filter(x -> x.getId().equals(e.getKey())).findFirst().orElse(null);
            if (c == null) {
                continue;
            }
            KbDocument doc = kbDocumentMapper.selectById(c.getDocId());
            if (doc == null) {
                continue;
            }
            Double vec = vecScore.get(c.getId());
            hits.add(new KbHit(doc.getId(), doc.getDocName(), c.getContent(), c.getChunkIndex(),
                    vec == null ? null : vec.floatValue()));
        }
        hits.sort((a, b) -> {
            double sa = fused.getOrDefault(chunkIdOf(a, candidates), 0.0);
            double sb = fused.getOrDefault(chunkIdOf(b, candidates), 0.0);
            return Double.compare(sb, sa);
        });
        return hits.size() > max ? new ArrayList<>(hits.subList(0, max)) : hits;
    }

    private Long chunkIdOf(KbHit hit, List<KbChunk> candidates) {
        return candidates.stream()
                .filter(x -> x.getDocId().equals(hit.docId())
                        && Integer.valueOf(x.getChunkIndex()).equals(hit.chunkIndex()))
                .map(KbChunk::getId).findFirst().orElse(null);
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String keyword, int limit) {
        return search(tenantId, userId, keyword, embeddingProvider.embed(keyword),
                limit, 0.0, "bm25", null);
    }

    // ---------- 打分与融合 ----------

    /** 关键词打分：查询词 n-gram 在切片中的覆盖率（近似 BM25 的轻量版，可复现）。 */
    private Map<Long, Double> bm25(List<KbChunk> chunks, String query) {
        Map<Long, Double> out = new HashMap<>();
        if (query == null || query.isBlank()) {
            return out;
        }
        List<String> qgrams = ngrams(query);
        if (qgrams.isEmpty()) {
            return out;
        }
        for (KbChunk c : chunks) {
            String content = c.getContent() == null ? "" : c.getContent();
            int hit = 0;
            for (String g : qgrams) {
                if (content.contains(g)) {
                    hit++;
                }
            }
            if (hit > 0) {
                out.put(c.getId(), (double) hit / qgrams.size() * (1.0 + Math.log1p(hit)));
            }
        }
        return out;
    }

    private static List<String> ngrams(String s) {
        List<String> out = new ArrayList<>();
        String t = s.trim();
        if (t.length() <= 2) {
            if (!t.isEmpty()) {
                out.add(t);
            }
            return out;
        }
        for (int i = 0; i + 2 <= t.length(); i++) {
            out.add(t.substring(i, i + 2));
        }
        return out;
    }

    private static List<Long> rankBy(Map<Long, Double> scores) {
        return scores.entrySet().stream()
                .sorted(Map.Entry.<Long, Double>comparingByValue().reversed())
                .map(Map.Entry::getKey)
                .toList();
    }

    private static void addRrf(Map<Long, Double> fused, List<Long> ranked) {
        for (int i = 0; i < ranked.size(); i++) {
            fused.merge(ranked.get(i), 1.0 / (RRF_K + i + 1), Double::sum);
        }
    }
}
