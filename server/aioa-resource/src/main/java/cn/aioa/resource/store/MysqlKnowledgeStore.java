package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbChunk;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.mapper.KbChunkMapper;
import cn.aioa.resource.mapper.KbDocumentMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * MySQL 存储实现（默认）：文档正文 LONGTEXT + 切片 TEXT，检索用 LIKE 匹配。
 *
 * <p>切换向量库时：新增实现类（如 VectorKnowledgeStore）并配置 {@code aioa.kb.store=vector}，
 * 本类自动让位（@ConditionalOnProperty），业务层零改动。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "aioa.kb.store", havingValue = "mysql", matchIfMissing = true)
public class MysqlKnowledgeStore implements KnowledgeStore {

    private final KbDocumentMapper kbDocumentMapper;
    private final KbChunkMapper kbChunkMapper;

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
    public List<KbHit> search(Long tenantId, Long userId, String keyword, int limit) {
        long tid = tenantId == null ? 0L : tenantId;
        int max = Math.max(1, limit);
        List<KbHit> hits = new ArrayList<>();
        List<Long> docIds = listVisible(tid, userId).stream().map(KbDocument::getId).toList();
        if (docIds.isEmpty()) {
            return hits;
        }
        List<KbChunk> chunks = kbChunkMapper.selectList(new LambdaQueryWrapper<KbChunk>()
                .eq(KbChunk::getTenantId, tid)
                .in(KbChunk::getDocId, docIds)
                .like(KbChunk::getContent, keyword)
                .orderByAsc(KbChunk::getId)
                .last("limit " + max));
        for (KbChunk c : chunks) {
            KbDocument doc = kbDocumentMapper.selectById(c.getDocId());
            if (doc == null) {
                continue;
            }
            hits.add(new KbHit(doc.getId(), doc.getDocName(), c.getContent(), c.getChunkIndex()));
        }
        if (hits.isEmpty()) {
            // 无正文切片（如只登记元信息的旧数据）时退回按文档名匹配
            for (KbDocument d : kbDocumentMapper.selectList(new LambdaQueryWrapper<KbDocument>()
                    .eq(KbDocument::getTenantId, tid)
                    .in(KbDocument::getId, docIds)
                    .like(KbDocument::getDocName, keyword)
                    .last("limit " + max))) {
                hits.add(new KbHit(d.getId(), d.getDocName(), null, null));
            }
        }
        return hits;
    }
}
