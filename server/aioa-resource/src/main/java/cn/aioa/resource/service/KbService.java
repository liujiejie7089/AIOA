package cn.aioa.resource.service;

import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.mapper.KbDocumentMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 知识库资料。M1 只做登记与状态流转（WAIT → OK），真正的解析入库由 agent 侧异步完成。
 */
@Service
@RequiredArgsConstructor
public class KbService {

    private final KbDocumentMapper kbDocumentMapper;

    public List<KbDocument> list(Long tenantId, Long userId) {
        return kbDocumentMapper.selectList(new LambdaQueryWrapper<KbDocument>()
                .eq(KbDocument::getTenantId, tenantId == null ? 0L : tenantId)
                .in(KbDocument::getUserId, BillingService.scopeUsers(userId))
                .orderByDesc(KbDocument::getCreatedAt));
    }

    /** 管理端运营视角：租户内全部资料（不按归属人过滤），调用方需校验 ROLE_ADMIN。 */
    public List<KbDocument> listTenant(Long tenantId) {
        return kbDocumentMapper.selectList(new LambdaQueryWrapper<KbDocument>()
                .eq(KbDocument::getTenantId, tenantId == null ? 0L : tenantId)
                .orderByDesc(KbDocument::getCreatedAt));
    }

    /** 登记一份资料，初始状态「解析中」，并写一条操作记录。 */
    public KbDocument register(Long tenantId, Long userId, String docName, String icon, Long sizeBytes) {
        KbDocument doc = new KbDocument();
        doc.setTenantId(tenantId == null ? 0L : tenantId);
        doc.setUserId(userId == null ? 0L : userId);
        doc.setDocName(docName);
        doc.setIcon(icon == null || icon.isBlank() ? guessIcon(docName) : icon);
        doc.setState(KbDocument.STATE_WAIT);
        doc.setSizeBytes(sizeBytes);
        doc.setCreatedAt(LocalDateTime.now());
        doc.setCreatedBy(userId);
        kbDocumentMapper.insert(doc);
        return doc;
    }

    /** 按文件名后缀猜一个图标，前端可覆盖。 */
    private static String guessIcon(String name) {
        if (name == null) {
            return "📄";
        }
        String lower = name.toLowerCase();
        if (lower.endsWith(".xlsx") || lower.endsWith(".xls") || lower.endsWith(".csv")) {
            return "📊";
        }
        if (lower.endsWith(".docx") || lower.endsWith(".doc") || lower.endsWith(".txt")) {
            return "📝";
        }
        if (lower.endsWith(".pdf")) {
            return "📄";
        }
        return "📎";
    }
}
