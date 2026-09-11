package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.service.EmbeddingProvider;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Elasticsearch 向量存储实现（方案 P2 / D-1，预留）。
 *
 * <p>仅当 {@code aioa.kb.store=elasticsearch} 时激活；默认（mysql）下本类不装配。
 * 目标形态：索引含 {@code text}（ik 分词，BM25）+ {@code dense_vector}（cosine，HNSW），
 * 检索用 knn + match 双路，经客户端 RRF（rank_constant=60）融合——
 * 因 ES 原生 RRF retriever 需 Enterprise 许可，免费版在应用层融合。</p>
 *
 * <p>当前阶段（决策点 1 选 A）本机未部署 ES，本类为「预留骨架」：
 * 方法与 MySQL 实现保持同构，接入 ES 客户端后填充即可，业务层零改动。
 * 为避免误用，本类在无 ES 连接时对写操作抛明确异常、读操作降级空结果。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "aioa.kb.store", havingValue = "elasticsearch")
public class ElasticKnowledgeStore implements KnowledgeStore {

    @Override
    public String type() {
        return "elasticsearch";
    }

    @Override
    public KbDocument saveDocument(KbDocument doc) {
        throw new UnsupportedOperationException("Elasticsearch 未在本机部署；请先配置 ES 连接并实现索引写入");
    }

    @Override
    public KbDocument updateDocument(KbDocument doc) {
        throw new UnsupportedOperationException("Elasticsearch 未在本机部署");
    }

    @Override
    public KbDocument findDocById(Long docId) {
        return null;
    }

    @Override
    public void deleteDocument(Long docId) {
        throw new UnsupportedOperationException("Elasticsearch 未在本机部署");
    }

    @Override
    public List<KbDocument> listVisible(Long tenantId, Long userId) {
        return List.of();
    }

    @Override
    public List<KbDocument> listTenant(Long tenantId) {
        return List.of();
    }

    @Override
    public int replaceChunks(KbDocument doc, List<String> chunks) {
        throw new UnsupportedOperationException("Elasticsearch 未在本机部署");
    }

    @Override
    public void saveEmbedding(Long chunkId, String content, float[] vector, String provider, int dims) {
        throw new UnsupportedOperationException("Elasticsearch 未在本机部署");
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String query, float[] queryVec,
                              int topK, double threshold, String mode, List<Long> docIdScope) {
        return List.of();
    }

    @Override
    public List<KbHit> search(Long tenantId, Long userId, String keyword, int limit) {
        return List.of();
    }
}
