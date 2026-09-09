package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.store.KnowledgeStore;
import lombok.RequiredArgsConstructor;
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
@Service
@RequiredArgsConstructor
public class KbService {

    /** 单个切片的最大字符数，超长按此长度二次切分。 */
    private static final int CHUNK_SIZE = 500;

    /** 可见范围：个人（仅本人可见）。 */
    public static final String SCOPE_PERSONAL = "PERSONAL";
    /** 可见范围：租户共享（同租户全员可见、可被全员检索）。 */
    public static final String SCOPE_TENANT = "TENANT";

    private final KnowledgeStore store;

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
        try {
            List<String> chunks = split(doc.getContent());
            if (chunks.isEmpty()) {
                throw new IllegalArgumentException("正文为空，无法入库");
            }
            int count = store.replaceChunks(doc, chunks);
            doc.setState(KbDocument.STATE_OK);
            doc.setChunkCount(count);
            doc.setErrorMsg(null);
            doc.setIndexedAt(LocalDateTime.now());
        } catch (Exception e) {
            doc.setState(KbDocument.STATE_FAILED);
            doc.setErrorMsg(e.getMessage() == null ? "入库失败" : e.getMessage());
        }
        doc.setUpdatedAt(LocalDateTime.now());
        store.updateDocument(doc);
        return doc;
    }

    /** 失败重试：重新切片入库。 */
    public KbDocument retry(Long docId) {
        KbDocument doc = store.findDocById(docId);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + docId);
        }
        if (doc.getContent() == null || doc.getContent().isBlank()) {
            doc.setState(KbDocument.STATE_FAILED);
            doc.setErrorMsg("资料无正文内容，请重新上传");
            doc.setUpdatedAt(LocalDateTime.now());
            store.updateDocument(doc);
            return doc;
        }
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

    /** 按段落切分：先按换行分段，超长段按 CHUNK_SIZE 二次切分。 */
    static List<String> split(String content) {
        List<String> out = new ArrayList<>();
        if (content == null) {
            return out;
        }
        for (String para : content.split("\\r?\\n")) {
            String p = para.trim();
            if (p.isEmpty()) {
                continue;
            }
            if (p.length() <= CHUNK_SIZE) {
                out.add(p);
            } else {
                for (int s = 0; s < p.length(); s += CHUNK_SIZE) {
                    out.add(p.substring(s, Math.min(p.length(), s + CHUNK_SIZE)));
                }
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
