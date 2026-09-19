package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.KbChunk;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.store.KbRelationalDao;
import cn.aioa.resource.store.KnowledgeStore;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 知识库资料（FR-F）：上传入库 → 切片 → 检索 → 引用溯源。
 * state 三态：WAIT 解析中 / OK 已入库 / FAILED 失败（可重试）。
 * 检索命中返回原文片段，经工具网关回传 agent，落 message.completed.citations（FR-D5）。
 *
 * <p>存储物理实现委托 {@link KnowledgeStore}（SPI）：现阶段为 MySQL 实现（LIKE 检索），
 * 后续切换向量数据库只需提供新实现类并配置 {@code aioa.kb.store=vector}，
 * 本类、工具网关、管理端/用户端与已接入的业务系统均零改动。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KbService {

    /** 单个切片的最大字符数，超长按此长度二次切分（默认，可被专家配置 chunkSize 覆盖）。 */
    private static final int CHUNK_SIZE = 500;

    /** 切分重叠字符数（默认）。 */
    private static final int CHUNK_OVERLAP = 50;

    /** 可见范围：个人（仅本人可见）。 */
    public static final String SCOPE_PERSONAL = "PERSONAL";
    /** 可见范围：租户共享（同租户全员可见、可被全员检索）。 */
    public static final String SCOPE_TENANT = "TENANT";

    private final KnowledgeStore store;
    private final KbRelationalDao relationalDao;
    private final EmbeddingProvider embeddingProvider;

    /**
     * 当前用户可见的资料：本人资料 + 公共资源（user_id=0）+ 本租户共享（scope=TENANT）。
     * 跨租户数据零泄露（FR-B3）。可见性规则由存储实现保证，与物理实现无关。
     */
    public List<KbDocument> list(Long tenantId, Long userId) {
        return store.listVisible(tenantId, userId);
    }

    /** 按主键读取一条资料（控制器做权限校验前先拿到实体）。 */
    public KbDocument findOne(Long docId) {
        return store.findDocById(docId);
    }

    /** 管理端运营视角：租户内全部资料（不按归属人过滤），调用方需校验 ROLE_ADMIN。 */
    public List<KbDocument> listTenant(Long tenantId) {
        return store.listTenant(tenantId);
    }

    /** 带原文片段的检索结果，供工具网关 citations 与用户端检索测试使用。 */
    public List<KnowledgeStore.KbHit> searchHits(Long tenantId, Long userId, String keyword, int limit) {
        return store.search(tenantId, userId, keyword, limit);
    }

    /** 当前生效的存储实现（mysql / milvus）——供运维排查与 E2E 双跑矩阵判断档位。 */
    public String storeType() {
        return store.type();
    }

    /** 当前生效的嵌入 provider 标识（local / http:模型名）。 */
    public String embeddingProviderName() {
        return embeddingProvider.name();
    }

    /** 当前嵌入维度（必须与 Milvus 集合维度一致）。 */
    public int embeddingDims() {
        return embeddingProvider.dims();
    }

    /**
     * 混合检索（带参数，方案 P2 / B5）：topK / threshold / mode / kbScope 全部真实生效。
     *
     * @param docIdScope 知识库范围（kbScope）：null/空=ALL，否则逗号分隔文档ID已解析为 List
     */
    public List<KnowledgeStore.KbHit> search(Long tenantId, Long userId, String query,
                                             int topK, double threshold, String mode,
                                             List<Long> docIdScope) {
        float[] queryVec = embeddingProvider.embed(query);
        return store.search(tenantId, userId, query, queryVec, topK, threshold, mode, docIdScope);
    }

    /**
     * 登记并入库一份资料：携带正文则同步切片入库并置 OK；无正文置 WAIT 等待异步解析。
     * 切片异常置 FAILED 并记录原因，用户端可重试。
     */
    public KbDocument register(Long tenantId, Long userId, String docName, String icon,
                               Long sizeBytes, String content, String scope) {
        KbDocument doc = new KbDocument();
        doc.setTenantId(tenantId == null ? 0L : tenantId);
        doc.setUserId(userId == null ? 0L : userId);
        doc.setDocName(docName);
        doc.setIcon(icon == null || icon.isBlank() ? guessIcon(docName) : icon);
        doc.setState(KbDocument.STATE_WAIT);
        doc.setSizeBytes(sizeBytes == null
                ? (long) (content == null ? 0 : content.getBytes().length) : sizeBytes);
        doc.setContent(content);
        doc.setScope(normalizeScope(scope));
        doc.setStage(KbDocument.STAGE_PARSING);
        doc.setProgress(0);
        doc.setRetryCount(0);
        doc.setCreatedAt(LocalDateTime.now());
        doc.setCreatedBy(userId);
        store.saveDocument(doc);
        if (content != null && !content.isBlank()) {
            index(doc);
        }
        return doc;
    }

    /** 兼容旧签名（仅登记元信息）。 */
    public KbDocument register(Long tenantId, Long userId, String docName, String icon, Long sizeBytes) {
        return register(tenantId, userId, docName, icon, sizeBytes, null, null);
    }

    /** 切片入库：成功置 OK 并回填切片数，失败置 FAILED 并记录原因。 */
    public KbDocument index(KbDocument doc) {
        return index(doc, CHUNK_SIZE, CHUNK_OVERLAP);
    }

    /**
     * 切片 + 向量化入库（方案 P2 / A4 / B5）。
     *
     * <p>流程：切分（chunkSize/chunkOverlap 可配置）→ 写切片 → 逐个向量化 →
     * 置 OK 并回填切片数；任一步异常置 FAILED 并留痕，可重试。</p>
     */
    public KbDocument index(KbDocument doc, int chunkSize, int chunkOverlap) {
        try {
            List<String> chunks = split(doc.getContent(), chunkSize, chunkOverlap);
            if (chunks.isEmpty()) {
                throw new IllegalArgumentException("正文为空，无法入库");
            }
            int count = store.replaceChunks(doc, chunks);
            embedAll(doc.getId(), doc.getTenantId(), chunks);
            doc.setState(KbDocument.STATE_OK);
            doc.setChunkCount(count);
            doc.setErrorMsg(null);
            doc.setStage(KbDocument.STAGE_OK);
            doc.setProgress(100);
            doc.setChunkSize(chunkSize);
            doc.setChunkOverlap(chunkOverlap);
            doc.setIndexedAt(LocalDateTime.now());
        } catch (Exception e) {
            doc.setState(KbDocument.STATE_FAILED);
            doc.setStage(KbDocument.STAGE_FAILED);
            doc.setErrorMsg(e.getMessage() == null ? "入库失败" : e.getMessage());
        }
        doc.setUpdatedAt(LocalDateTime.now());
        store.updateDocument(doc);
        return doc;
    }

    /** 对切片逐条向量化并回写（失败不中断整体，仅记录日志，检索时自动退化关键词）。 */
    private void embedAll(Long docId, Long tenantId, List<String> chunks) {
        List<KbChunk> rows = relationalDao.chunksOfDoc(docId);
        for (int i = 0; i < rows.size() && i < chunks.size(); i++) {
            KbChunk c = rows.get(i);
            try {
                float[] vec = embeddingProvider.embed(chunks.get(i));
                store.saveEmbedding(c.getId(), chunks.get(i), vec, embeddingProvider.name(), embeddingProvider.dims());
            } catch (Exception e) {
                log.warn("切片向量化失败 chunkId={}: {}", c.getId(), e.getMessage());
            }
        }
    }

    /**
     * 用**当前** embedding provider 全量重算切片向量（docs/32 Ph1「重算 job」）。
     *
     * <p>触发场景：{@code aioa.kb.embedding-provider} 从 {@code local} 换成 {@code http}、
     * 或换了 embedding 模型 / 维度。**不重算的后果是静默的**——
     * 旧向量维度与新 query 向量不符，{@link EmbeddingProvider#cosine} 直接返回 0，
     * 检索「不出错但永远不命中」。</p>
     *
     * <p>幂等：只处理 {@code embedding_provider} 或 {@code embedding_dims} 与当前 provider 不符的切片，
     * 已是最新的跳过；单条失败只告警、继续下一条（与 {@link #embedAll} 一致，便于分批重跑收敛）。</p>
     *
     * @return 实际重算条数
     */
    public int reembedAll() {
        final int batchSize = 200;
        final String wantProvider = embeddingProvider.name();
        final int wantDims = embeddingProvider.dims();
        long cursor = 0L;
        int done = 0;
        int scanned = 0;
        while (true) {
            List<KbChunk> batch = relationalDao.chunksAfterId(cursor, batchSize);
            if (batch.isEmpty()) {
                break;
            }
            for (KbChunk c : batch) {
                cursor = Math.max(cursor, c.getId());
                scanned++;
                if (wantProvider.equals(c.getEmbeddingProvider())
                        && c.getEmbeddingDims() != null && c.getEmbeddingDims() == wantDims) {
                    continue;
                }
                try {
                    float[] vec = embeddingProvider.embed(c.getContent());
                    store.saveEmbedding(c.getId(), c.getContent(), vec, wantProvider, wantDims);
                    done++;
                } catch (Exception e) {
                    log.warn("切片重算向量失败 chunkId={}: {}", c.getId(), e.getMessage());
                }
            }
            if (batch.size() < batchSize) {
                break;
            }
        }
        log.info("知识库向量全量重算完成：扫描={} 重算={} provider={} dims={}", scanned, done, wantProvider, wantDims);
        return done;
    }

    /** 失败重试：重新切片入库。 */
    public KbDocument retry(Long docId) {
        KbDocument doc = store.findDocById(docId);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + docId);
        }
        if (doc.getContent() == null || doc.getContent().isBlank()) {
            doc.setState(KbDocument.STATE_FAILED);
            doc.setStage(KbDocument.STAGE_FAILED);
            doc.setErrorMsg("资料无正文内容，请重新上传");
            doc.setUpdatedAt(LocalDateTime.now());
            store.updateDocument(doc);
            return doc;
        }
        doc.setRetryCount((doc.getRetryCount() == null ? 0 : doc.getRetryCount()) + 1);
        return index(doc);
    }

    /** 修改资料元信息：重命名与可见范围（PERSONAL / TENANT）。 */
    public KbDocument update(Long docId, String name, String scope) {
        KbDocument doc = store.findDocById(docId);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + docId);
        }
        if (name != null && !name.isBlank()) {
            doc.setDocName(name.trim());
        }
        if (scope != null && !scope.isBlank()) {
            doc.setScope(normalizeScope(scope));
        }
        doc.setUpdatedAt(LocalDateTime.now());
        store.updateDocument(doc);
        return doc;
    }

    /** 删除资料（逻辑删除文档与切片）。 */
    public void remove(Long docId) {
        store.deleteDocument(docId);
    }

    /** 用户端自助检索测试（FR-F3 配套）：返回原文片段。 */
    public List<KnowledgeStore.KbHit> searchMine(Long tenantId, Long userId, String keyword, int limit) {
        return searchHits(tenantId, userId, keyword, limit);
    }

    /** 按段落切分：先按换行分段，超长段按 chunkSize 二次切分（带 chunkOverlap 重叠）。 */
    static List<String> split(String content) {
        return split(content, CHUNK_SIZE, CHUNK_OVERLAP);
    }

    /** 带参数的切分：chunkSize 为单块字符数，chunkOverlap 为相邻块重叠字符数。 */
    static List<String> split(String content, int chunkSize, int chunkOverlap) {
        List<String> out = new ArrayList<>();
        if (content == null) {
            return out;
        }
        int size = chunkSize <= 0 ? CHUNK_SIZE : chunkSize;
        int overlap = Math.max(0, Math.min(chunkOverlap, size / 2));
        for (String para : content.split("\\r?\\n")) {
            String p = para.trim();
            if (p.isEmpty()) {
                continue;
            }
            if (p.length() <= size) {
                out.add(p);
                continue;
            }
            int step = size - overlap;
            for (int s = 0; s < p.length(); s += step) {
                out.add(p.substring(s, Math.min(p.length(), s + size)));
            }
        }
        return out;
    }

    private static String normalizeScope(String scope) {
        return SCOPE_TENANT.equalsIgnoreCase(scope) ? SCOPE_TENANT : SCOPE_PERSONAL;
    }

    /** 按文件名后缀猜一个图标，前端可覆盖。 */
    private static String guessIcon(String name) {
        if (name == null) {
            return "doc";
        }
        String lower = name.toLowerCase();
        if (lower.endsWith(".xlsx") || lower.endsWith(".xls") || lower.endsWith(".csv")) {
            return "sheet";
        }
        if (lower.endsWith(".docx") || lower.endsWith(".doc") || lower.endsWith(".txt")) {
            return "doc";
        }
        if (lower.endsWith(".pdf")) {
            return "pdf";
        }
        return "file";
    }
}
