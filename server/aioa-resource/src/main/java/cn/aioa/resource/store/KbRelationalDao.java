package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbChunk;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.mapper.KbChunkMapper;
import cn.aioa.resource.mapper.KbDocumentMapper;
import cn.aioa.resource.service.EmbeddingProvider;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识库的**关系型权威底座**（MySQL）：文档元数据 + 切片正文 + 切片向量 BLOB。
 *
 * <p>为什么要把这段逻辑从 {@code MysqlKnowledgeStore} 里抽出来（docs/32 引入 Milvus 时的必要重构）：</p>
 * <ul>
 *   <li><b>单一事实源</b>：{@link #listVisible} 承载的是 SPI 里最重要的安全契约（本人 + 公共 + 租户共享，
 *       跨租户零泄露）。Milvus 档位下**文档列表仍然由 MySQL 提供**（决策 D4/R9：元数据不迁入 Milvus），
 *       若两个 store 各写一份，隔离规则就有了两个可能漂移的实现；</li>
 *   <li><b>可重建</b>：Milvus 只是「可随时从本底座重建的向量索引副本」，
 *       回滚 = 改一行配置（{@code AIOA_KB_STORE=mysql}），索引损坏 = 跑一次回填。</li>
 * </ul>
 *
 * <p>本类**不是** {@code KnowledgeStore} 实现（不参与 SPI 装配，永不被 {@code @ConditionalOnProperty} 排除），
 * 因此两种档位下都在，且不产生「同一接口多个 Bean」的歧义。</p>
 */
@Component
@RequiredArgsConstructor
public class KbRelationalDao {

    private final KbDocumentMapper kbDocumentMapper;
    private final KbChunkMapper kbChunkMapper;
    private final EmbeddingProvider embeddingProvider;

    // ---------- 文档 ----------

    public KbDocument saveDocument(KbDocument doc) {
        kbDocumentMapper.insert(doc);
        return doc;
    }

    public KbDocument updateDocument(KbDocument doc) {
        kbDocumentMapper.updateById(doc);
        return doc;
    }

    public KbDocument findDocById(Long docId) {
        return docId == null ? null : kbDocumentMapper.selectById(docId);
    }

    /** 批量取文档，用于把检索命中的 docId 一次性换成 docName（避免 N+1）。 */
    public Map<Long, KbDocument> docsByIds(Collection<Long> ids) {
        Map<Long, KbDocument> out = new HashMap<>();
        if (ids == null || ids.isEmpty()) {
            return out;
        }
        List<KbDocument> rows = kbDocumentMapper.selectBatchIds(ids);
        for (KbDocument d : rows) {
            out.put(d.getId(), d);
        }
        return out;
    }

    /**
     * 可见文档：本人 + 公共资源（user_id=0）+ 本租户共享（scope=TENANT），按创建时间倒序。
     * 跨租户零泄露（FR-B3）——**改动本方法前请先读 {@code docs/15-权限矩阵} 与 SPI 契约**。
     */
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

    /** 可见文档的主键（检索范围求交用）。 */
    public List<Long> visibleDocIds(Long tenantId, Long userId) {
        return listVisible(tenantId, userId).stream().map(KbDocument::getId).toList();
    }

    /** 租户内全部文档（管理端运营视角）。 */
    public List<KbDocument> listTenant(Long tenantId) {
        return kbDocumentMapper.selectList(new LambdaQueryWrapper<KbDocument>()
                .eq(KbDocument::getTenantId, tenantId == null ? 0L : tenantId)
                .orderByDesc(KbDocument::getCreatedAt));
    }

    /** 删除文档及其全部切片（逻辑删除由 {@code @TableLogic} 处理）。 */
    public void deleteDocument(Long docId) {
        kbChunkMapper.delete(new LambdaQueryWrapper<KbChunk>().eq(KbChunk::getDocId, docId));
        kbDocumentMapper.deleteById(docId);
    }

    // ---------- 切片 ----------

    /** 用给定切片整体替换该文档的切片（先清后写，幂等）。 */
    public int replaceChunks(KbDocument doc, List<String> chunks) {
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

    /** 某文档的切片，按 chunk_index 升序。 */
    public List<KbChunk> chunksOfDoc(Long docId) {
        return kbChunkMapper.selectList(new LambdaQueryWrapper<KbChunk>()
                .eq(KbChunk::getDocId, docId)
                .orderByAsc(KbChunk::getChunkIndex));
    }

    /** 指定文档集合下的全部切片（关键词兜底与回填共用）。 */
    public List<KbChunk> chunksOfDocs(Long tenantId, Collection<Long> docIds) {
        if (docIds == null || docIds.isEmpty()) {
            return List.of();
        }
        return kbChunkMapper.selectList(new LambdaQueryWrapper<KbChunk>()
                .eq(KbChunk::getTenantId, tenantId == null ? 0L : tenantId)
                .in(KbChunk::getDocId, docIds));
    }

    public KbChunk findChunk(Long chunkId) {
        return chunkId == null ? null : kbChunkMapper.selectById(chunkId);
    }

    /**
     * 按主键游标分批扫描**全库**切片（无租户过滤）——仅供索引回填使用。
     *
     * <p>用「id &gt; cursor」而不是 OFFSET：回填大表时 OFFSET 越翻越慢，
     * 且游标法能顺带纳入回填期间新增的行。</p>
     *
     * @param afterId 上一批的最大主键（首批发 0）
     * @param limit   批量大小（调用方约束，直接拼进 SQL，不接受外部输入）
     */
    public List<KbChunk> chunksAfterId(long afterId, int limit) {
        int n = Math.max(1, Math.min(limit, 5000));
        return kbChunkMapper.selectList(new LambdaQueryWrapper<KbChunk>()
                .gt(KbChunk::getId, afterId)
                .orderByAsc(KbChunk::getId)
                .last("limit " + n));
    }

    /**
     * 把向量写回 {@code kb_chunk.embedding}（float32 小端 BLOB）+ provider + dims + 时间戳。
     * 保留 BLOB 的意义：它是 MySQL 档位的检索数据源，也是 Milvus 索引的**重建来源**（决策 D4）。
     */
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
}
