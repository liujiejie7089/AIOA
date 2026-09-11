package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.DeptQuota;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgQuota;
import cn.aioa.org.entity.QuotaAllocLog;
import cn.aioa.org.entity.TenantResourcePool;
import cn.aioa.org.mapper.DeptQuotaMapper;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgQuotaMapper;
import cn.aioa.org.mapper.QuotaAllocLogMapper;
import cn.aioa.org.mapper.TenantResourcePoolMapper;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 四级配额链路（FR-C 资源池与配额分配 / FR-H 机构额度管理）。
 *
 * <pre>
 * 租户资源池 ──分配──> 机构配额 ──二次分配──> 部门额度 ──> 个人额度(tenant_quota)
 * </pre>
 *
 * 一致性口径：剩余 = quota_tokens + free_tokens - used_tokens；
 * 任一层调整均写 quota_alloc_log（before/delta/after + reason + operator）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuotaService {

    private final TenantResourcePoolMapper poolMapper;
    private final OrgQuotaMapper orgQuotaMapper;
    private final DeptQuotaMapper deptQuotaMapper;
    private final QuotaAllocLogMapper allocLogMapper;
    private final OrgInstitutionMapper institutionMapper;
    private final OrgDepartmentMapper deptMapper;
    private final AuditRecorder audit;

    // ================================================================== FR-C1/C4 资源池

    public Map<String, Object> pool(Long tenantId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                .eq(TenantResourcePool::getTenantId, tenantId)
                .eq(TenantResourcePool::getPeriod, p)
                .last("limit 1"));
        // 已分配总量（Σ 机构配额）与剩余可分配
        List<OrgQuota> quotas = orgQuotaMapper.selectList(new LambdaQueryWrapper<OrgQuota>()
                .eq(OrgQuota::getTenantId, tenantId)
                .eq(OrgQuota::getPeriod, p));
        long allocated = quotas.stream().mapToLong(q -> nz(q.getQuotaTokens())).sum();
        long freeAllocated = quotas.stream().mapToLong(q -> nz(q.getFreeTokens())).sum();
        long total = pool == null ? 0L : nz(pool.getTokenTotal());
        long used = pool == null ? 0L : nz(pool.getTokenUsed());

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("period", p);
        m.put("delivered", pool != null);
        m.put("tokenTotal", total);
        m.put("tokenUsed", used);
        m.put("tokenRemain", Math.max(0, total - used));
        m.put("allocatedTokens", allocated);
        m.put("allocatableTokens", Math.max(0, total - allocated));
        m.put("freeAllocatedTokens", freeAllocated);
        m.put("expertSeats", pool == null ? 0 : nz(pool.getExpertSeats()));
        m.put("expertUsed", pool == null ? 0 : nz(pool.getExpertUsed()));
        m.put("skillSeats", pool == null ? 0 : nz(pool.getSkillSeats()));
        m.put("skillUsed", pool == null ? 0 : nz(pool.getSkillUsed()));
        m.put("warnThreshold", pool == null ? 20 : nz(pool.getWarnThreshold()));
        m.put("unitPrice", pool == null ? null : pool.getUnitPrice());
        m.put("expireAt", pool != null && pool.getExpireAt() != null ? pool.getExpireAt().toString() : null);
        m.put("status", pool == null ? "NOT_DELIVERED" : pool.getStatus());
        m.put("usageRatio", total == 0 ? 0d : round2(used * 100.0 / total));
        m.put("allocRatio", total == 0 ? 0d : round2(allocated * 100.0 / total));
        m.put("warn", total > 0 && used * 100.0 / total >= (100 - (pool == null ? 20 : nz(pool.getWarnThreshold()))));
        return m;
    }

    /** FR-C1：平台向租户交付 / 扩容资源池（FR-C4 池扩容）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> upsertPool(Long tenantId, AuthUser actor, Map<String, Object> body) {
        String p = Vals.str(body, "period", Vals.nowPeriod());
        TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                .eq(TenantResourcePool::getTenantId, tenantId)
                .eq(TenantResourcePool::getPeriod, p)
                .last("limit 1"));
        Map<String, Object> before = pool == null ? null : pool(tenantId, p);
        long newTotal = Vals.lng(body, "tokenTotal", pool == null ? 0L : nz(pool.getTokenTotal()));
        if (newTotal <= 0) {
            throw BizException.badRequest("资源池词元总量必须大于 0");
        }
        // 不得低于已分配量
        long allocated = orgQuotaMapper.selectList(new LambdaQueryWrapper<OrgQuota>()
                        .eq(OrgQuota::getTenantId, tenantId).eq(OrgQuota::getPeriod, p))
                .stream().mapToLong(q -> nz(q.getQuotaTokens())).sum();
        if (newTotal < allocated) {
            throw BizException.badRequest("资源池总量（" + newTotal + "）不得低于已分配到机构的量（"
                    + allocated + "），请先回收机构配额");
        }
        boolean isNew = pool == null;
        if (isNew) {
            pool = new TenantResourcePool();
            pool.setTenantId(tenantId);
            pool.setPeriod(p);
            pool.setStatus("ACTIVE");
            pool.setCreatedAt(LocalDateTime.now());
            pool.setCreatedBy(actor == null ? 0L : actor.getUserId());
        }
        pool.setTokenTotal(newTotal);
        if (body != null && body.containsKey("expertSeats")) {
            pool.setExpertSeats(Vals.integer(body, "expertSeats", (int) nz(pool.getExpertSeats())));
        }
        if (body != null && body.containsKey("skillSeats")) {
            pool.setSkillSeats(Vals.integer(body, "skillSeats", (int) nz(pool.getSkillSeats())));
        }
        if (body != null && body.containsKey("warnThreshold")) {
            pool.setWarnThreshold(Vals.integer(body, "warnThreshold", 20));
        }
        if (body != null && body.containsKey("unitPrice")) {
            pool.setUnitPrice(Vals.dec(body, "unitPrice", pool.getUnitPrice()));
        }
        if (Vals.date(body, "expireAt") != null) {
            pool.setExpireAt(Vals.date(body, "expireAt"));
        }
        pool.setUpdatedAt(LocalDateTime.now());
        if (isNew) {
            poolMapper.insert(pool);
        } else {
            poolMapper.updateById(pool);
        }
        if (isNew) {
            logAlloc(tenantId, 0L, QuotaAllocLog.SCOPE_TENANT, tenantId, p,
                    QuotaAllocLog.ACTION_ALLOCATE, 0, newTotal, newTotal, "平台交付词元套餐", actor);
        }
        audit.record(tenantId, 0L, actor, isNew ? "RESOURCE_POOL_DELIVER" : "RESOURCE_POOL_EXPAND",
                "TENANT_RESOURCE_POOL", pool.getId(),
                (isNew ? "交付" : "扩容") + "资源池至 " + newTotal + " 词元（周期 " + p + "）",
                before, pool(tenantId, p));
        return pool(tenantId, p);
    }

    // ================================================================== FR-C2/C3 机构配额

    public List<Map<String, Object>> listOrgQuotas(Long tenantId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        List<OrgQuota> rows = orgQuotaMapper.selectList(new LambdaQueryWrapper<OrgQuota>()
                .eq(OrgQuota::getTenantId, tenantId)
                .eq(OrgQuota::getPeriod, p)
                .orderByAsc(OrgQuota::getInstitutionId));
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (OrgQuota q : rows) {
            out.add(orgQuotaView(tenantId, q));
        }
        return out;
    }

    public Map<String, Object> orgQuotaView(Long tenantId, OrgQuota q) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", q.getId());
        m.put("tenantId", q.getTenantId());
        m.put("institutionId", q.getInstitutionId());
        m.put("period", q.getPeriod());
        m.put("quotaTokens", q.getQuotaTokens());
        m.put("usedTokens", q.getUsedTokens());
        m.put("freeTokens", q.getFreeTokens());
        m.put("remainTokens", Math.max(0, nz(q.getQuotaTokens()) + nz(q.getFreeTokens()) - nz(q.getUsedTokens())));
        m.put("warnThreshold", q.getWarnThreshold());
        m.put("frozen", q.getFrozen());
        m.put("effectiveFrom", q.getEffectiveFrom() == null ? null : q.getEffectiveFrom().toString());
        m.put("effectiveTo", q.getEffectiveTo() == null ? null : q.getEffectiveTo().toString());
        m.put("status", q.getStatus());
        long cap = nz(q.getQuotaTokens()) + nz(q.getFreeTokens());
        double ratio = cap == 0 ? 0d : nz(q.getUsedTokens()) * 100.0 / cap;
        m.put("usageRatio", round2(ratio));
        m.put("warn", cap > 0 && ratio >= (100 - nz(q.getWarnThreshold())));
        m.put("exhausted", cap > 0 && nz(q.getUsedTokens()) >= cap);
        OrgInstitution it = institutionMapper.selectById(q.getInstitutionId());
        m.put("institutionName", it == null ? null : it.getName());
        m.put("institutionCode", it == null ? null : it.getCode());
        m.put("orgType", it == null ? null : it.getOrgType());
        return m;
    }

    /**
     * FR-C2：向机构分配配额（幂等：同周期同机构为 upsert）。
     * 校验门禁：Σ 机构配额 ≤ 资源池总量。
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> allocateOrgQuota(Long tenantId, AuthUser actor, Map<String, Object> body) {
        Long institutionId = Vals.lngObj(body, "institutionId");
        if (institutionId == null) {
            throw BizException.badRequest("institutionId 不能为空");
        }
        OrgInstitution it = institutionMapper.selectById(institutionId);
        if (it == null || !tenantId.equals(it.getTenantId())) {
            throw BizException.notFound("机构不存在于本租户：" + institutionId);
        }
        String p = Vals.str(body, "period", Vals.nowPeriod());
        long quota = Vals.lng(body, "quotaTokens", 0L);
        long free = Vals.lng(body, "freeTokens", 0L);
        if (quota < 0 || free < 0) {
            throw BizException.badRequest("配额与赠送额度不能为负");
        }
        TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                .eq(TenantResourcePool::getTenantId, tenantId)
                .eq(TenantResourcePool::getPeriod, p)
                .last("limit 1"));
        if (pool == null) {
            throw BizException.badRequest("周期 " + p + " 的资源池尚未交付，无法分配机构配额（请先执行入驻第 1 步）");
        }
        OrgQuota existing = orgQuotaMapper.selectOne(new LambdaQueryWrapper<OrgQuota>()
                .eq(OrgQuota::getTenantId, tenantId)
                .eq(OrgQuota::getInstitutionId, institutionId)
                .eq(OrgQuota::getPeriod, p)
                .last("limit 1"));
        long others = orgQuotaMapper.selectList(new LambdaQueryWrapper<OrgQuota>()
                        .eq(OrgQuota::getTenantId, tenantId)
                        .eq(OrgQuota::getPeriod, p)
                        .ne(existing != null, OrgQuota::getId, existing == null ? -1L : existing.getId()))
                .stream().mapToLong(q -> nz(q.getQuotaTokens())).sum();
        if (others + quota > nz(pool.getTokenTotal())) {
            throw BizException.badRequest("分配超额：其它机构已占 " + others + "，本次 " + quota
                    + "，超过资源池总量 " + nz(pool.getTokenTotal()) + "（FR-C2）");
        }

        Map<String, Object> before = existing == null ? null : orgQuotaView(tenantId, existing);
        long beforeTokens = existing == null ? 0L : nz(existing.getQuotaTokens());
        boolean isNew = existing == null;
        OrgQuota q = isNew ? new OrgQuota() : existing;
        if (isNew) {
            q.setTenantId(tenantId);
            q.setInstitutionId(institutionId);
            q.setPeriod(p);
            q.setUsedTokens(0L);
            q.setFrozen(false);
            q.setStatus("ACTIVE");
            q.setEffectiveFrom(Vals.date(body, "effectiveFrom"));
            q.setEffectiveTo(Vals.date(body, "effectiveTo"));
            q.setCreatedAt(LocalDateTime.now());
            q.setCreatedBy(actor.getUserId());
        } else {
            if (Vals.date(body, "effectiveFrom") != null) {
                q.setEffectiveFrom(Vals.date(body, "effectiveFrom"));
            }
            if (Vals.date(body, "effectiveTo") != null) {
                q.setEffectiveTo(Vals.date(body, "effectiveTo"));
            }
        }
        q.setQuotaTokens(quota);
        q.setFreeTokens(free);
        if (body != null && body.containsKey("warnThreshold")) {
            q.setWarnThreshold(Vals.integer(body, "warnThreshold", 20));
        }
        q.setUpdatedAt(LocalDateTime.now());
        if (isNew) {
            orgQuotaMapper.insert(q);
        } else {
            orgQuotaMapper.updateById(q);
        }

        String reason = Vals.str(body, "reason", isNew ? "入驻第 3 步：向机构分配配额上限" : "调整机构配额");
        logAlloc(tenantId, institutionId, QuotaAllocLog.SCOPE_ORG, institutionId, p,
                isNew ? QuotaAllocLog.ACTION_ALLOCATE : QuotaAllocLog.ACTION_ADJUST,
                beforeTokens, quota - beforeTokens, quota, reason, actor);
        Map<String, Object> after = orgQuotaView(tenantId, q);
        audit.record(tenantId, institutionId, actor,
                isNew ? "ORG_QUOTA_ALLOCATE" : "ORG_QUOTA_ADJUST", "ORG_QUOTA", q.getId(),
                (isNew ? "分配" : "调整") + "机构「" + it.getName() + "」配额为 " + quota + " 词元", before, after);
        return after;
    }

    /**
     * 按增量调整机构配额（FR-H3 扩容申请通过后自动加额）。
     * 仍受「Σ 机构配额 ≤ 资源池总量」约束；加额后自动解冻。
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> applyOrgQuotaDelta(Long tenantId, Long institutionId, long delta,
                                                  String reason, AuthUser actor) {
        if (delta == 0) {
            throw BizException.badRequest("调整量不能为 0");
        }
        OrgQuota q = requireOrgQuota(tenantId, institutionId, null);
        long before = nz(q.getQuotaTokens());
        long after = before + delta;
        if (after < 0) {
            throw BizException.badRequest("调整后配额不能为负（当前 " + before + "）");
        }
        if (delta > 0) {
            TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                    .eq(TenantResourcePool::getTenantId, tenantId)
                    .eq(TenantResourcePool::getPeriod, q.getPeriod())
                    .last("limit 1"));
            long others = orgQuotaMapper.selectList(new LambdaQueryWrapper<OrgQuota>()
                            .eq(OrgQuota::getTenantId, tenantId)
                            .eq(OrgQuota::getPeriod, q.getPeriod())
                            .ne(OrgQuota::getId, q.getId()))
                    .stream().mapToLong(x -> nz(x.getQuotaTokens())).sum();
            long poolTotal = pool == null ? 0L : nz(pool.getTokenTotal());
            if (poolTotal > 0 && others + after > poolTotal) {
                throw BizException.badRequest("扩容超额：其它机构已占 " + others + "，本机构调整后 " + after
                        + "，超过资源池总量 " + poolTotal + "；请先扩容租户资源池（FR-C4）");
            }
        }
        Map<String, Object> beforeView = orgQuotaView(tenantId, q);
        q.setQuotaTokens(after);
        if (delta > 0) {
            q.setFrozen(false);
        }
        q.setUpdatedAt(LocalDateTime.now());
        orgQuotaMapper.updateById(q);
        logAlloc(tenantId, institutionId, QuotaAllocLog.SCOPE_ORG, institutionId, q.getPeriod(),
                QuotaAllocLog.ACTION_ADJUST, before, delta, after,
                reason == null ? "配额调整" : reason, actor);
        Map<String, Object> afterView = orgQuotaView(tenantId, q);
        audit.record(tenantId, institutionId, actor, "ORG_QUOTA_ADJUST", "ORG_QUOTA", q.getId(),
                "机构配额 " + before + " → " + after + "（" + (delta > 0 ? "+" : "") + delta + "）",
                beforeView, afterView);
        return afterView;
    }

    /** FR-C3：冻结 / 解冻机构配额（耗尽自动冻结亦走此路径）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> freezeOrgQuota(Long tenantId, Long institutionId, boolean frozen,
                                              AuthUser actor, String reason) {
        OrgQuota q = requireOrgQuota(tenantId, institutionId, null);
        Map<String, Object> before = orgQuotaView(tenantId, q);
        if (Boolean.valueOf(frozen).equals(q.getFrozen())) {
            throw BizException.badRequest("机构配额当前已是「" + (frozen ? "冻结" : "正常") + "」状态");
        }
        q.setFrozen(frozen);
        q.setUpdatedAt(LocalDateTime.now());
        orgQuotaMapper.updateById(q);
        logAlloc(tenantId, institutionId, QuotaAllocLog.SCOPE_ORG, institutionId, q.getPeriod(),
                frozen ? QuotaAllocLog.ACTION_FREEZE : QuotaAllocLog.ACTION_UNFREEZE,
                nz(q.getQuotaTokens()), 0, nz(q.getQuotaTokens()),
                reason == null ? (frozen ? "机构配额冻结" : "机构配额解冻") : reason, actor);
        audit.record(tenantId, institutionId, actor,
                frozen ? "ORG_QUOTA_FREEZE" : "ORG_QUOTA_UNFREEZE", "ORG_QUOTA", q.getId(),
                (frozen ? "冻结" : "解冻") + "机构 #" + institutionId + " 配额", before, orgQuotaView(tenantId, q));
        return orgQuotaView(tenantId, q);
    }

    public OrgQuota requireOrgQuota(Long tenantId, Long institutionId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        OrgQuota q = orgQuotaMapper.selectOne(new LambdaQueryWrapper<OrgQuota>()
                .eq(OrgQuota::getTenantId, tenantId)
                .eq(OrgQuota::getInstitutionId, institutionId)
                .eq(OrgQuota::getPeriod, p)
                .last("limit 1"));
        if (q == null) {
            throw BizException.notFound("机构配额未分配（机构 #" + institutionId + " 周期 " + p + "）");
        }
        return q;
    }

    // ================================================================== FR-H1/H2 部门额度

    public List<Map<String, Object>> listDeptQuotas(Long institutionId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        List<DeptQuota> rows = deptQuotaMapper.selectList(new LambdaQueryWrapper<DeptQuota>()
                .eq(DeptQuota::getInstitutionId, institutionId)
                .eq(DeptQuota::getPeriod, p)
                .orderByAsc(DeptQuota::getDepartmentId));
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (DeptQuota d : rows) {
            out.add(deptQuotaView(d));
        }
        return out;
    }

    public Map<String, Object> deptQuotaView(DeptQuota d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", d.getId());
        m.put("institutionId", d.getInstitutionId());
        m.put("departmentId", d.getDepartmentId());
        m.put("period", d.getPeriod());
        m.put("quotaTokens", d.getQuotaTokens());
        m.put("usedTokens", d.getUsedTokens());
        m.put("remainTokens", Math.max(0, nz(d.getQuotaTokens()) - nz(d.getUsedTokens())));
        m.put("warnThreshold", d.getWarnThreshold());
        long cap = nz(d.getQuotaTokens());
        double ratio = cap == 0 ? 0d : nz(d.getUsedTokens()) * 100.0 / cap;
        m.put("usageRatio", round2(ratio));
        m.put("warn", cap > 0 && ratio >= (100 - nz(d.getWarnThreshold())));
        OrgDepartment dept = deptMapper.selectById(d.getDepartmentId());
        m.put("departmentName", dept == null ? null : dept.getName());
        m.put("departmentCode", dept == null ? null : dept.getCode());
        m.put("departmentLevel", dept == null ? null : dept.getLevel());
        return m;
    }

    /** FR-H1：企业管理员向部门二次分配额度，校验 Σ 部门额度 ≤ 机构配额。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> allocateDeptQuota(Long tenantId, Long institutionId, AuthUser actor,
                                                 Map<String, Object> body) {
        Long departmentId = Vals.lngObj(body, "departmentId");
        if (departmentId == null) {
            throw BizException.badRequest("departmentId 不能为空");
        }
        OrgDepartment dept = deptMapper.selectById(departmentId);
        if (dept == null || !institutionId.equals(dept.getInstitutionId())) {
            throw BizException.notFound("部门不存在或不属于本机构：" + departmentId);
        }
        String p = Vals.str(body, "period", Vals.nowPeriod());
        long quota = Vals.lng(body, "quotaTokens", 0L);
        if (quota < 0) {
            throw BizException.badRequest("部门额度不能为负");
        }
        OrgQuota orgQuota = requireOrgQuota(tenantId, institutionId, p);
        DeptQuota existing = deptQuotaMapper.selectOne(new LambdaQueryWrapper<DeptQuota>()
                .eq(DeptQuota::getInstitutionId, institutionId)
                .eq(DeptQuota::getDepartmentId, departmentId)
                .eq(DeptQuota::getPeriod, p)
                .last("limit 1"));
        long others = deptQuotaMapper.selectList(new LambdaQueryWrapper<DeptQuota>()
                        .eq(DeptQuota::getInstitutionId, institutionId)
                        .eq(DeptQuota::getPeriod, p)
                        .ne(existing != null, DeptQuota::getId, existing == null ? -1L : existing.getId()))
                .stream().mapToLong(x -> nz(x.getQuotaTokens())).sum();
        if (others + quota > nz(orgQuota.getQuotaTokens())) {
            throw BizException.badRequest("二次分配超额：其它部门已占 " + others + "，本次 " + quota
                    + "，超过机构配额 " + nz(orgQuota.getQuotaTokens()) + "（FR-H1）");
        }

        Map<String, Object> before = existing == null ? null : deptQuotaView(existing);
        long beforeTokens = existing == null ? 0L : nz(existing.getQuotaTokens());
        boolean isNew = existing == null;
        DeptQuota d = isNew ? new DeptQuota() : existing;
        if (isNew) {
            d.setTenantId(tenantId);
            d.setInstitutionId(institutionId);
            d.setDepartmentId(departmentId);
            d.setPeriod(p);
            d.setUsedTokens(0L);
            d.setCreatedAt(LocalDateTime.now());
            d.setCreatedBy(actor.getUserId());
        }
        d.setQuotaTokens(quota);
        if (body != null && body.containsKey("warnThreshold")) {
            d.setWarnThreshold(Vals.integer(body, "warnThreshold", 20));
        }
        d.setUpdatedAt(LocalDateTime.now());
        if (isNew) {
            deptQuotaMapper.insert(d);
        } else {
            deptQuotaMapper.updateById(d);
        }

        String reason = Vals.str(body, "reason", isNew ? "入驻第 5 步：二次分配到部门" : "调整部门额度");
        logAlloc(tenantId, institutionId, QuotaAllocLog.SCOPE_DEPT, departmentId, p,
                isNew ? QuotaAllocLog.ACTION_ALLOCATE : QuotaAllocLog.ACTION_ADJUST,
                beforeTokens, quota - beforeTokens, quota, reason, actor);
        Map<String, Object> after = deptQuotaView(d);
        audit.record(tenantId, institutionId, actor,
                isNew ? "DEPT_QUOTA_ALLOCATE" : "DEPT_QUOTA_ADJUST", "DEPT_QUOTA", d.getId(),
                (isNew ? "分配" : "调整") + "部门「" + dept.getName() + "」额度为 " + quota + " 词元", before, after);
        return after;
    }

    // ================================================================== 链路总览 / 预警 / 消耗

    /** 四级链路总览（入驻向导与看板共用）。 */
    public Map<String, Object> chain(Long tenantId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        Map<String, Object> poolView = pool(tenantId, p);
        List<Map<String, Object>> orgs = listOrgQuotas(tenantId, p);
        long deptAllocated = 0L;
        List<Map<String, Object>> depts = new ArrayList<>();
        for (Map<String, Object> o : orgs) {
            Long institutionId = ((Number) o.get("institutionId")).longValue();
            List<Map<String, Object>> ds = listDeptQuotas(institutionId, p);
            ds.forEach(x -> x.put("institutionName", o.get("institutionName")));
            deptAllocated += ds.stream().mapToLong(x -> nz(x.get("quotaTokens"))).sum();
            depts.addAll(ds);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", p);
        out.put("level1Pool", poolView);
        out.put("level2Org", orgs);
        out.put("level3Dept", depts);
        out.put("summary", Map.of(
                "poolTotal", poolView.get("tokenTotal"),
                "orgAllocated", orgs.stream().mapToLong(x -> nz(x.get("quotaTokens"))).sum(),
                "deptAllocated", deptAllocated,
                "orgCount", orgs.size(),
                "deptCount", depts.size()));
        return out;
    }

    /** FR-C3 / FR-H2：预警清单（机构级 + 部门级）。 */
    public Map<String, Object> warnings(Long tenantId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        List<Map<String, Object>> orgWarn = new ArrayList<>();
        for (Map<String, Object> o : listOrgQuotas(tenantId, p)) {
            if (Boolean.TRUE.equals(o.get("warn")) || Boolean.TRUE.equals(o.get("frozen"))) {
                orgWarn.add(o);
            }
        }
        List<Map<String, Object>> deptWarn = new ArrayList<>();
        for (Map<String, Object> o : listOrgQuotas(tenantId, p)) {
            Long institutionId = ((Number) o.get("institutionId")).longValue();
            for (Map<String, Object> d : listDeptQuotas(institutionId, p)) {
                if (Boolean.TRUE.equals(d.get("warn"))) {
                    d.put("institutionName", o.get("institutionName"));
                    deptWarn.add(d);
                }
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", p);
        out.put("orgWarnings", orgWarn);
        out.put("deptWarnings", deptWarn);
        out.put("total", orgWarn.size() + deptWarn.size());
        return out;
    }

    /**
     * 消耗记帐：机构与部门 used_tokens 同步递增；耗尽自动冻结机构配额（FR-C3）。
     * 幂等由调用方（token_ledger 的 run_id 唯一键）保证。
     */
    @Transactional(rollbackFor = Exception.class)
    public void consume(Long tenantId, Long institutionId, Long departmentId, long tokens,
                        String reason, AuthUser actor) {
        if (tokens <= 0) {
            return;
        }
        String p = Vals.nowPeriod();
        OrgQuota q = orgQuotaMapper.selectOne(new LambdaQueryWrapper<OrgQuota>()
                .eq(OrgQuota::getTenantId, tenantId)
                .eq(OrgQuota::getInstitutionId, institutionId)
                .eq(OrgQuota::getPeriod, p)
                .last("limit 1"));
        if (q == null) {
            return;
        }
        long before = nz(q.getUsedTokens());
        q.setUsedTokens(before + tokens);
        long cap = nz(q.getQuotaTokens()) + nz(q.getFreeTokens());
        if (cap > 0 && q.getUsedTokens() >= cap && !Boolean.TRUE.equals(q.getFrozen())) {
            q.setFrozen(true);
            log.warn("org quota exhausted, auto-freeze: tenant={} institution={} used={} cap={}",
                    tenantId, institutionId, q.getUsedTokens(), cap);
        }
        q.setUpdatedAt(LocalDateTime.now());
        orgQuotaMapper.updateById(q);
        logAlloc(tenantId, institutionId, QuotaAllocLog.SCOPE_ORG, institutionId, p,
                QuotaAllocLog.ACTION_CONSUME, before, tokens, nz(q.getUsedTokens()), reason, actor);

        if (departmentId != null && departmentId > 0) {
            DeptQuota d = deptQuotaMapper.selectOne(new LambdaQueryWrapper<DeptQuota>()
                    .eq(DeptQuota::getInstitutionId, institutionId)
                    .eq(DeptQuota::getDepartmentId, departmentId)
                    .eq(DeptQuota::getPeriod, p)
                    .last("limit 1"));
            if (d != null) {
                long db = nz(d.getUsedTokens());
                d.setUsedTokens(db + tokens);
                d.setUpdatedAt(LocalDateTime.now());
                deptQuotaMapper.updateById(d);
                logAlloc(tenantId, institutionId, QuotaAllocLog.SCOPE_DEPT, departmentId, p,
                        QuotaAllocLog.ACTION_CONSUME, db, tokens, nz(d.getUsedTokens()), reason, actor);
            }
        }
    }

    /** 消耗前准入：机构冻结或额度不足 → 403 并引导申请扩容（FR-C3）。 */
    public void assertConsumable(Long tenantId, Long institutionId) {
        String p = Vals.nowPeriod();
        OrgQuota q = orgQuotaMapper.selectOne(new LambdaQueryWrapper<OrgQuota>()
                .eq(OrgQuota::getTenantId, tenantId)
                .eq(OrgQuota::getInstitutionId, institutionId)
                .eq(OrgQuota::getPeriod, p)
                .last("limit 1"));
        if (q == null) {
            return;
        }
        if (Boolean.TRUE.equals(q.getFrozen())) {
            throw BizException.forbidden("机构配额已耗尽并被冻结，请向租户管理员提交扩容申请（FR-H3）");
        }
        long cap = nz(q.getQuotaTokens()) + nz(q.getFreeTokens());
        if (cap > 0 && nz(q.getUsedTokens()) >= cap) {
            throw BizException.forbidden("机构配额已用尽，请向租户管理员提交扩容申请（FR-H3）");
        }
    }

    public List<QuotaAllocLog> allocLogs(Long tenantId, Long institutionId, int limit) {
        LambdaQueryWrapper<QuotaAllocLog> w = new LambdaQueryWrapper<QuotaAllocLog>()
                .eq(QuotaAllocLog::getTenantId, tenantId);
        if (institutionId != null) {
            w.eq(QuotaAllocLog::getInstitutionId, institutionId);
        }
        return allocLogMapper.selectList(w.orderByDesc(QuotaAllocLog::getId)
                .last("limit " + Math.max(1, Math.min(limit, 500))));
    }

    // ------------------------------------------------------------------ 内部工具

    private void logAlloc(Long tenantId, Long institutionId, String scopeType, Long scopeId,
                          String period, String action, long before, long delta, long after,
                          String reason, AuthUser actor) {
        QuotaAllocLog logRow = new QuotaAllocLog();
        logRow.setTenantId(tenantId);
        logRow.setInstitutionId(institutionId == null ? 0L : institutionId);
        logRow.setScopeType(scopeType);
        logRow.setScopeId(scopeId);
        logRow.setPeriod(period);
        logRow.setAction(action);
        logRow.setBeforeTokens(before);
        logRow.setDelta(delta);
        logRow.setAfterTokens(after);
        logRow.setReason(reason);
        if (actor != null) {
            logRow.setOperatorId(actor.getUserId());
            logRow.setOperatorName(AuditRecorder.displayName(actor));
            logRow.setOperatorRole(actor.getRoles() == null || actor.getRoles().isEmpty()
                    ? null : actor.getRoles().get(0));
        }
        logRow.setCreatedAt(LocalDateTime.now());
        allocLogMapper.insert(logRow);
    }

    static long nz(Number v) {
        return v == null ? 0L : v.longValue();
    }

    static long nz(Object v) {
        if (v == null) {
            return 0L;
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(v));
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
