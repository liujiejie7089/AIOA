package cn.aioa.org.service;

import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.Vals;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 用量看板与监控（FR-F1 租户跨机构用量总览 / FR-K1 机构用量看板）。
 */
@Service
@RequiredArgsConstructor
public class DashboardService {

    private final OrgInstitutionMapper institutionMapper;
    private final QuotaService quotaService;
    private final OrgStatMapper statMapper;

    /** FR-F1：租户级跨机构用量总览。 */
    public Map<String, Object> tenantOverview(Long tenantId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        List<OrgInstitution> insts = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .orderByAsc(OrgInstitution::getId));
        Map<Long, Map<String, Object>> quotaByInst = new LinkedHashMap<>();
        for (Map<String, Object> q : quotaService.listOrgQuotas(tenantId, p)) {
            quotaByInst.put(((Number) q.get("institutionId")).longValue(), q);
        }
        List<Map<String, Object>> rows = new ArrayList<>(insts.size());
        long totalQuota = 0, totalUsed = 0;
        for (OrgInstitution it : insts) {
            Map<String, Object> q = quotaByInst.get(it.getId());
            long quota = q == null ? 0L : QuotaService.nz(q.get("quotaTokens"));
            long used = q == null ? 0L : QuotaService.nz(q.get("usedTokens"));
            long free = q == null ? 0L : QuotaService.nz(q.get("freeTokens"));
            totalQuota += quota;
            totalUsed += used;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("institutionId", it.getId());
            m.put("institutionName", it.getName());
            m.put("orgType", it.getOrgType());
            m.put("status", it.getStatus());
            m.put("onboardStep", it.getOnboardStep());
            m.put("adminName", it.getAdminName());
            m.put("deptCount", statMapper.countActiveDepts(it.getId()));
            m.put("memberCount", statMapper.countActiveMembers(it.getId()));
            m.put("quotaTokens", quota);
            m.put("usedTokens", used);
            m.put("freeTokens", free);
            m.put("remainTokens", Math.max(0, quota + free - used));
            long cap = quota + free;
            m.put("usageRatio", cap == 0 ? 0d : QuotaService.round2(used * 100.0 / cap));
            m.put("frozen", q != null && Boolean.TRUE.equals(q.get("frozen")));
            m.put("warn", q != null && Boolean.TRUE.equals(q.get("warn")));
            m.put("kbCount", statMapper.countKbOfInstitution(it.getId()));
            m.put("pendingLeave", statMapper.countLeaveByStatus(it.getId(), "PENDING"));
            rows.add(m);
        }
        Map<String, Object> warnings = quotaService.warnings(tenantId, p);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", p);
        out.put("institutionCount", insts.size());
        out.put("activeCount", insts.stream()
                .filter(i -> OrgInstitution.STATUS_ACTIVE.equals(i.getStatus())).count());
        out.put("memberCount", rows.stream().mapToLong(r -> QuotaService.nz(r.get("memberCount"))).sum());
        out.put("deptCount", rows.stream().mapToLong(r -> QuotaService.nz(r.get("deptCount"))).sum());
        out.put("quotaTokens", totalQuota);
        out.put("usedTokens", totalUsed);
        out.put("usageRatio", totalQuota == 0 ? 0d : QuotaService.round2(totalUsed * 100.0 / totalQuota));
        out.put("pendingApprovals", statMapper.countPendingApprovals(tenantId));
        out.put("warningCount", warnings.get("total"));
        out.put("resourcePool", quotaService.pool(tenantId, p));
        out.put("institutions", rows);
        return out;
    }

    /** FR-K1：机构用量看板（企业端首页）。 */
    public Map<String, Object> orgUsage(Long tenantId, Long institutionId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        Map<String, Object> quota;
        try {
            quota = quotaService.orgQuotaView(tenantId, quotaService.requireOrgQuota(tenantId, institutionId, p));
        } catch (Exception e) {
            quota = null;
        }
        List<Map<String, Object>> depts = quotaService.listDeptQuotas(institutionId, p);
        List<Map<String, Object>> members = statMapper.usageByUserOfInstitution(tenantId, institutionId, p);
        long institutionUsage = statMapper.sumLedgerTokensOfInstitution(tenantId, institutionId, p);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", p);
        out.put("institutionId", institutionId);
        out.put("orgQuota", quota);
        out.put("institutionUsageTokens", institutionUsage);
        out.put("deptCount", depts.size());
        out.put("memberCount", statMapper.countActiveMembers(institutionId));
        out.put("kbCount", statMapper.countKbOfInstitution(institutionId));
        out.put("pendingLeaveCount", statMapper.countLeaveByStatus(institutionId, "PENDING"));
        out.put("approvedLeaveCount", statMapper.countLeaveByStatus(institutionId, "APPROVED"));
        out.put("departments", depts);
        out.put("members", members);
        out.put("personalQuotaTotal", statMapper.sumPersonalQuotaOfInstitution(tenantId, institutionId));
        return out;
    }
}
