package cn.aioa.org.service;

import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.AuditRecorder;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 两级审计查询（FR-F2 租户级 / FR-K2 机构级）。
 *
 * <p>不可篡改：只提供查询，不提供更新 / 删除接口；并提供哈希链完整性校验。</p>
 */
@Service
@RequiredArgsConstructor
public class AuditQueryService {

    private final OrgStatMapper statMapper;
    private final AuditRecorder auditRecorder;

    /** FR-F2：租户级审计（不过滤 institutionId，可见全部机构操作）。 */
    public Map<String, Object> tenantAudit(Long tenantId, Long institutionId, int limit) {
        int n = clamp(limit);
        List<Map<String, Object>> rows = statMapper.selectAuditLogs(tenantId, institutionId, n);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("scope", AuditRecorder.SCOPE_TENANT);
        out.put("tenantId", tenantId);
        out.put("institutionId", institutionId);
        out.put("total", statMapper.countAuditLogs(tenantId, institutionId));
        out.put("items", rows);
        return out;
    }

    /** FR-K2：机构级审计（强制注入 institution_id 硬边界）。 */
    public Map<String, Object> orgAudit(Long tenantId, Long institutionId, int limit) {
        int n = clamp(limit);
        List<Map<String, Object>> rows = statMapper.selectAuditLogs(tenantId, institutionId, n);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("scope", AuditRecorder.SCOPE_ORG);
        out.put("institutionId", institutionId);
        out.put("total", statMapper.countAuditLogs(tenantId, institutionId));
        out.put("items", rows);
        return out;
    }

    /** 审计链完整性校验（验收：两级操作留痕完整率 100%）。 */
    public Map<String, Object> verify(Long tenantId) {
        AuditRecorder.ChainResult r = auditRecorder.verifyChain(tenantId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", tenantId);
        out.put("intact", r.isIntact());
        out.put("brokenRecordId", r.getBrokenRecordId());
        out.put("count", r.getTotal());
        // 真正做了「自哈希 + 链接」双重校验的行数与遗留行数，便于判断是否真的被完整校验
        out.put("verifiedRows", r.getVerified());
        out.put("legacyRows", r.getLegacy());
        return out;
    }

    private static int clamp(int limit) {
        return Math.max(1, Math.min(limit <= 0 ? 100 : limit, 500));
    }
}
