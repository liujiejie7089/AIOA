package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.CostAllocBill;
import cn.aioa.org.entity.CostAllocRule;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.TenantResourcePool;
import cn.aioa.org.mapper.CostAllocBillMapper;
import cn.aioa.org.mapper.CostAllocRuleMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.mapper.TenantResourcePoolMapper;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 费用分摊（FR-D）：
 *   D1 分摊规则（FIXED_RATIO 固定比例 / USAGE 按用量实摊 / COST_CENTER 成本中心），变更次期生效并留痕
 *   D2 分摊账单（序时流水号 + 与平台账本逐笔核对标记）
 *   D3 分摊试算
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CostAllocService {

    private final CostAllocRuleMapper ruleMapper;
    private final CostAllocBillMapper billMapper;
    private final OrgInstitutionMapper institutionMapper;
    private final TenantResourcePoolMapper poolMapper;
    private final OrgStatMapper statMapper;
    private final ObjectMapper objectMapper;
    private final AuditRecorder audit;

    // ------------------------------------------------------------------ D1 规则

    public List<CostAllocRule> listRules(Long tenantId) {
        return ruleMapper.selectList(new LambdaQueryWrapper<CostAllocRule>()
                .eq(CostAllocRule::getTenantId, tenantId)
                .orderByAsc(CostAllocRule::getName)
                .orderByDesc(CostAllocRule::getVersion));
    }

    @Transactional(rollbackFor = Exception.class)
    public CostAllocRule createRule(Long tenantId, AuthUser actor, Map<String, Object> body) {
        String name = Vals.require(body, "name", "规则名称");
        String ruleType = Vals.str(body, "ruleType", CostAllocRule.TYPE_FIXED_RATIO);
        if (!List.of(CostAllocRule.TYPE_FIXED_RATIO, CostAllocRule.TYPE_USAGE,
                CostAllocRule.TYPE_COST_CENTER).contains(ruleType)) {
            throw BizException.badRequest("不支持的分摊方式：" + ruleType);
        }
        String configJson = normalizeConfig(tenantId, ruleType, body);
        CostAllocRule r = new CostAllocRule();
        r.setTenantId(tenantId);
        r.setName(name);
        r.setRuleType(ruleType);
        r.setPeriodType(Vals.str(body, "periodType", CostAllocRule.PERIOD_MONTH));
        r.setConfigJson(configJson);
        r.setVersion(1);
        r.setEffectiveFrom(Vals.date(body, "effectiveFrom"));
        r.setStatus(CostAllocRule.STATUS_ACTIVE);
        r.setRemark(Vals.str(body, "remark"));
        r.setCreatedAt(LocalDateTime.now());
        r.setCreatedBy(actor.getUserId());
        ruleMapper.insert(r);
        audit.record(tenantId, 0L, actor, "COST_RULE_CREATE", "COST_ALLOC_RULE", r.getId(),
                "新建分摊规则「" + name + "」（" + ruleType + "，版本 v1）", null, r);
        return r;
    }

    /**
     * FR-D1：修改规则不覆盖历史 —— 旧版本置 RETIRED，新版本 version+1 置 ACTIVE（次期生效）。
     */
    @Transactional(rollbackFor = Exception.class)
    public CostAllocRule updateRule(Long tenantId, Long id, AuthUser actor, Map<String, Object> body) {
        CostAllocRule old = requireRule(tenantId, id);
        String ruleType = Vals.str(body, "ruleType", old.getRuleType());
        CostAllocRule fresh = new CostAllocRule();
        fresh.setTenantId(tenantId);
        fresh.setName(Vals.str(body, "name", old.getName()));
        fresh.setRuleType(ruleType);
        fresh.setPeriodType(Vals.str(body, "periodType", old.getPeriodType()));
        fresh.setConfigJson(normalizeConfig(tenantId, ruleType, body));
        fresh.setVersion(nzv(old.getVersion()) + 1);
        fresh.setEffectiveFrom(Vals.date(body, "effectiveFrom") == null
                ? java.time.LocalDate.now().withDayOfMonth(1).plusMonths(1) : Vals.date(body, "effectiveFrom"));
        fresh.setStatus(CostAllocRule.STATUS_ACTIVE);
        fresh.setRemark(Vals.str(body, "remark", old.getRemark()));
        fresh.setCreatedAt(LocalDateTime.now());
        fresh.setCreatedBy(actor.getUserId());
        ruleMapper.insert(fresh);

        CostAllocRule retire = new CostAllocRule();
        retire.setId(old.getId());
        retire.setStatus("RETIRED");
        retire.setUpdatedAt(LocalDateTime.now());
        ruleMapper.updateById(retire);

        audit.record(tenantId, 0L, actor, "COST_RULE_VERSION_BUMP", "COST_ALLOC_RULE", fresh.getId(),
                "分摊规则「" + fresh.getName() + "」升级至 v" + fresh.getVersion()
                        + "（旧版 v" + nzv(old.getVersion()) + " 置为 RETIRED，次期生效）", old, fresh);
        return fresh;
    }

    public CostAllocRule requireRule(Long tenantId, Long id) {
        CostAllocRule r = ruleMapper.selectById(id);
        if (r == null || !r.getTenantId().equals(tenantId)) {
            throw BizException.notFound("分摊规则不存在：" + id);
        }
        return r;
    }

    /** 校验并归一化 config_json：固定比例 / 成本中心必须比例合计 100%。 */
    private String normalizeConfig(Long tenantId, String ruleType, Map<String, Object> body) {
        Object raw = body == null ? null : body.get("config");
        if (raw == null) {
            if (CostAllocRule.TYPE_USAGE.equals(ruleType)) {
                return "{}";
            }
            // 未给配置时：按当前启用的机构等比生成默认比例
            List<OrgInstitution> insts = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                    .eq(OrgInstitution::getTenantId, tenantId)
                    .eq(OrgInstitution::getStatus, OrgInstitution.STATUS_ACTIVE)
                    .orderByAsc(OrgInstitution::getId));
            if (insts.isEmpty()) {
                throw BizException.badRequest("租户下暂无启用机构，无法生成默认分摊比例");
            }
            List<Map<String, Object>> ratios = new ArrayList<>();
            int each = 100 / insts.size();
            int acc = 0;
            for (int i = 0; i < insts.size(); i++) {
                int v = (i == insts.size() - 1) ? 100 - acc : each;
                acc += v;
                ratios.add(Map.of("institutionId", insts.get(i).getId(), "ratio", v));
            }
            try {
                return objectMapper.writeValueAsString(Map.of("ratios", ratios));
            } catch (Exception e) {
                throw BizException.badRequest("生成默认分摊比例失败：" + e.getMessage());
            }
        }
        String json = raw instanceof String s ? s : writeJson(raw);
        JsonNode node = readTree(json);
        JsonNode ratios = node.get("ratios") != null ? node.get("ratios") : node.get("centers");
        if (!CostAllocRule.TYPE_USAGE.equals(ruleType)) {
            if (ratios == null || !ratios.isArray() || ratios.isEmpty()) {
                throw BizException.badRequest("固定比例 / 成本中心分摊必须提供 config.ratios 数组");
            }
            double sum = 0;
            for (JsonNode r : ratios) {
                if (r.get("institutionId") == null || r.get("ratio") == null) {
                    throw BizException.badRequest("config.ratios 每项必须含 institutionId 与 ratio");
                }
                sum += r.get("ratio").asDouble();
            }
            if (Math.abs(sum - 100.0) > 0.01) {
                throw BizException.badRequest("比例合计必须为 100%，当前为 " + sum + "%（FR-D1）");
            }
        }
        return json;
    }

    // ------------------------------------------------------------------ D3 试算

    /** 分摊试算：给定期用量，按规则算出各机构应分摊金额（不落库）。 */
    public Map<String, Object> simulate(Long tenantId, Long ruleId, Map<String, Object> body) {
        CostAllocRule rule = requireRule(tenantId, ruleId);
        String period = Vals.str(body, "period", Vals.nowPeriod());
        BigDecimal unitPrice = resolveUnitPrice(tenantId, period, body);
        List<OrgInstitution> insts = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .orderByAsc(OrgInstitution::getId));
        Map<Long, Long> usage = usageOf(tenantId, period);
        long totalUsage = usage.values().stream().mapToLong(Long::longValue).sum();
        long override = Vals.lng(body, "totalTokens", 0L);
        if (override > 0) {
            totalUsage = override;
        }
        Map<Long, Double> ratios = ratiosOf(rule);
        List<Map<String, Object>> rows = new ArrayList<>();
        BigDecimal totalAmount = BigDecimal.ZERO;
        for (OrgInstitution it : insts) {
            long instUsage = usage.getOrDefault(it.getId(), 0L);
            double ratio;
            double amount;
            if (CostAllocRule.TYPE_USAGE.equals(rule.getRuleType())) {
                ratio = totalUsage == 0 ? 0d : instUsage * 100.0 / totalUsage;
                amount = unitPrice.multiply(BigDecimal.valueOf(instUsage)).doubleValue();
            } else {
                Double r = ratios.get(it.getId());
                ratio = r == null ? 0d : r;
                amount = unitPrice.multiply(BigDecimal.valueOf(totalUsage))
                        .multiply(BigDecimal.valueOf(ratio)).divide(BigDecimal.valueOf(100), 6, RoundingMode.HALF_UP)
                        .doubleValue();
            }
            BigDecimal amt = BigDecimal.valueOf(amount).setScale(2, RoundingMode.HALF_UP);
            totalAmount = totalAmount.add(amt);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("institutionId", it.getId());
            m.put("institutionName", it.getName());
            m.put("orgType", it.getOrgType());
            m.put("usageTokens", instUsage);
            m.put("ratio", round2(ratio));
            m.put("unitPrice", unitPrice);
            m.put("amount", amt);
            rows.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ruleId", rule.getId());
        out.put("ruleName", rule.getName());
        out.put("ruleType", rule.getRuleType());
        out.put("version", rule.getVersion());
        out.put("period", period);
        out.put("unitPrice", unitPrice);
        out.put("totalUsageTokens", totalUsage);
        out.put("totalAmount", totalAmount);
        out.put("rows", rows);
        out.put("simulated", true);
        return out;
    }

    // ------------------------------------------------------------------ D2 账单

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> generateBills(Long tenantId, AuthUser actor, Map<String, Object> body) {
        Long ruleId = Vals.lngObj(body, "ruleId");
        if (ruleId == null) {
            throw BizException.badRequest("ruleId 不能为空");
        }
        CostAllocRule rule = requireRule(tenantId, ruleId);
        String period = Vals.str(body, "period", Vals.nowPeriod());
        BigDecimal unitPrice = resolveUnitPrice(tenantId, period, body);
        Map<Long, Long> usage = usageOf(tenantId, period);
        long totalUsage = usage.values().stream().mapToLong(Long::longValue).sum();
        long override = Vals.lng(body, "totalTokens", 0L);
        if (override > 0) {
            totalUsage = override;
        }
        Map<Long, Double> ratios = ratiosOf(rule);
        List<OrgInstitution> insts = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .orderByAsc(OrgInstitution::getId));

        List<Map<String, Object>> generated = new ArrayList<>();
        int created = 0;
        int unchanged = 0;
        for (OrgInstitution it : insts) {
            CostAllocBill existing = billMapper.selectOne(new LambdaQueryWrapper<CostAllocBill>()
                    .eq(CostAllocBill::getTenantId, tenantId)
                    .eq(CostAllocBill::getInstitutionId, it.getId())
                    .eq(CostAllocBill::getPeriod, period)
                    .eq(CostAllocBill::getRuleVersion, rule.getVersion())
                    .last("limit 1"));
            if (existing != null) {
                unchanged++;
                generated.add(billView(existing, it.getName()));
                continue;
            }
            long instUsage = usage.getOrDefault(it.getId(), 0L);
            double ratio;
            long allocUsage;
            if (CostAllocRule.TYPE_USAGE.equals(rule.getRuleType())) {
                ratio = totalUsage == 0 ? 0d : instUsage * 100.0 / totalUsage;
                allocUsage = instUsage;
            } else {
                Double r = ratios.get(it.getId());
                ratio = r == null ? 0d : r;
                allocUsage = Math.round(totalUsage * ratio / 100.0);
            }
            BigDecimal amount = unitPrice.multiply(BigDecimal.valueOf(allocUsage))
                    .setScale(2, RoundingMode.HALF_UP);

            // 与平台账本逐笔核对：机构账本用量与账单用量一致 → ledger_checked = 1
            long ledgerUsage = statMapper.sumLedgerTokensOfInstitution(tenantId, it.getId(), period);
            boolean checked = ledgerUsage == allocUsage;

            CostAllocBill bill = new CostAllocBill();
            bill.setTenantId(tenantId);
            bill.setRuleId(rule.getId());
            bill.setRuleVersion(nzv(rule.getVersion()));
            bill.setInstitutionId(it.getId());
            bill.setPeriod(period);
            bill.setUsageTokens(allocUsage);
            bill.setUnitPrice(unitPrice);
            bill.setAmount(amount);
            bill.setSerialNo(serialNo(period, tenantId, it.getId(), nzv(rule.getVersion())));
            bill.setLedgerChecked(checked);
            bill.setGeneratedAt(LocalDateTime.now());
            bill.setCreatedBy(actor == null ? 0L : actor.getUserId());
            billMapper.insert(bill);
            created++;
            generated.add(billView(bill, it.getName()));
        }

        audit.record(tenantId, 0L, actor, "COST_BILL_GENERATE", "COST_ALLOC_BILL", rule.getId(),
                "生成 " + period + " 分摊账单：新建 " + created + " 张，已存在 " + unchanged + " 张"
                        + "（规则 v" + nzv(rule.getVersion()) + "）",
                null, Map.of("created", created, "unchanged", unchanged));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", period);
        out.put("ruleId", rule.getId());
        out.put("ruleVersion", rule.getVersion());
        out.put("created", created);
        out.put("unchanged", unchanged);
        out.put("bills", generated);
        return out;
    }

    public List<Map<String, Object>> listBills(Long tenantId, String period) {
        LambdaQueryWrapper<CostAllocBill> w = new LambdaQueryWrapper<CostAllocBill>()
                .eq(CostAllocBill::getTenantId, tenantId);
        if (period != null && !period.isBlank()) {
            w.eq(CostAllocBill::getPeriod, period);
        }
        List<CostAllocBill> rows = billMapper.selectList(w
                .orderByDesc(CostAllocBill::getPeriod).orderByAsc(CostAllocBill::getInstitutionId));
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (CostAllocBill b : rows) {
            OrgInstitution it = institutionMapper.selectById(b.getInstitutionId());
            out.add(billView(b, it == null ? null : it.getName()));
        }
        return out;
    }

    /** FR-D2 验收口径：账单与平台账本一致率。 */
    public Map<String, Object> reconcile(Long tenantId, String period) {
        String p = period == null ? Vals.nowPeriod() : period;
        List<CostAllocBill> bills = billMapper.selectList(new LambdaQueryWrapper<CostAllocBill>()
                .eq(CostAllocBill::getTenantId, tenantId)
                .eq(CostAllocBill::getPeriod, p));
        long billSum = bills.stream().mapToLong(b -> nzl(b.getUsageTokens())).sum();
        long ledgerSum = statMapper.sumLedgerTokens(tenantId, p);
        int mismatched = 0;
        List<Map<String, Object>> details = new ArrayList<>();
        for (CostAllocBill b : bills) {
            long ledger = statMapper.sumLedgerTokensOfInstitution(tenantId, b.getInstitutionId(), p);
            boolean ok = ledger == nzl(b.getUsageTokens());
            if (!ok) {
                mismatched++;
            }
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("institutionId", b.getInstitutionId());
            d.put("billUsageTokens", b.getUsageTokens());
            d.put("ledgerUsageTokens", ledger);
            d.put("matched", ok);
            d.put("serialNo", b.getSerialNo());
            details.add(d);
        }
        // 账本无数据时（演示库默认）认为一致 —— 双方均为 0
        double rate = bills.isEmpty() ? 100.0
                : Math.round((bills.size() - mismatched) * 10000.0 / bills.size()) / 100.0;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", p);
        out.put("billCount", bills.size());
        out.put("billSumTokens", billSum);
        out.put("ledgerSumTokens", ledgerSum);
        out.put("ledgerCheckedCount", bills.stream().filter(b -> Boolean.TRUE.equals(b.getLedgerChecked())).count());
        out.put("mismatched", mismatched);
        out.put("consistentRate", rate);
        out.put("details", details);
        return out;
    }

    // ------------------------------------------------------------------ 内部工具

    private Map<Long, Long> usageOf(Long tenantId, String period) {
        Map<Long, Long> usage = new LinkedHashMap<>();
        List<OrgInstitution> insts = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId));
        for (OrgInstitution it : insts) {
            usage.put(it.getId(), statMapper.sumLedgerTokensOfInstitution(tenantId, it.getId(), period));
        }
        return usage;
    }

    private BigDecimal resolveUnitPrice(Long tenantId, String period, Map<String, Object> body) {
        BigDecimal fromBody = Vals.dec(body, "unitPrice", null);
        if (fromBody != null) {
            return fromBody;
        }
        TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                .eq(TenantResourcePool::getTenantId, tenantId)
                .eq(TenantResourcePool::getPeriod, period)
                .last("limit 1"));
        if (pool != null && pool.getUnitPrice() != null && pool.getUnitPrice().signum() > 0) {
            return pool.getUnitPrice();
        }
        return new BigDecimal("0.000120");
    }

    private Map<Long, Double> ratiosOf(CostAllocRule rule) {
        Map<Long, Double> map = new LinkedHashMap<>();
        if (rule.getConfigJson() == null || rule.getConfigJson().isBlank()) {
            return map;
        }
        JsonNode node = readTree(rule.getConfigJson());
        JsonNode ratios = node.get("ratios") != null ? node.get("ratios") : node.get("centers");
        if (ratios == null || !ratios.isArray()) {
            return map;
        }
        for (JsonNode r : ratios) {
            if (r.get("institutionId") != null && r.get("ratio") != null) {
                map.put(r.get("institutionId").asLong(), r.get("ratio").asDouble());
            }
        }
        return map;
    }

    private Map<String, Object> billView(CostAllocBill b, String institutionName) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", b.getId());
        m.put("tenantId", b.getTenantId());
        m.put("ruleId", b.getRuleId());
        m.put("ruleVersion", b.getRuleVersion());
        m.put("institutionId", b.getInstitutionId());
        m.put("institutionName", institutionName);
        m.put("period", b.getPeriod());
        m.put("usageTokens", b.getUsageTokens());
        m.put("unitPrice", b.getUnitPrice());
        m.put("amount", b.getAmount());
        m.put("serialNo", b.getSerialNo());
        m.put("ledgerChecked", b.getLedgerChecked());
        m.put("generatedAt", b.getGeneratedAt() == null ? null : b.getGeneratedAt().toString());
        return m;
    }

    private static String serialNo(String period, Long tenantId, Long institutionId, int version) {
        return "BILL-" + period.replace("-", "") + "-T" + tenantId + "-I" + institutionId + "-V" + version;
    }

    private JsonNode readTree(String json) {
        try {
            return objectMapper.readTree(json);
        } catch (Exception e) {
            throw BizException.badRequest("规则配置不是合法 JSON：" + e.getMessage());
        }
    }

    private String writeJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            throw BizException.badRequest("规则配置序列化失败：" + e.getMessage());
        }
    }

    static int nzv(Integer v) {
        return v == null ? 0 : v;
    }

    static long nzl(Long v) {
        return v == null ? 0L : v;
    }

    static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
