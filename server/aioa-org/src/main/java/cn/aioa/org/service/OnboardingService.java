package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.CostAllocBill;
import cn.aioa.org.entity.CostAllocRule;
import cn.aioa.org.entity.LeaveRequest;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.entity.OrgQuota;
import cn.aioa.org.entity.ResourceGrant;
import cn.aioa.org.entity.TenantResourcePool;
import cn.aioa.org.mapper.CostAllocBillMapper;
import cn.aioa.org.mapper.CostAllocRuleMapper;
import cn.aioa.org.mapper.DeptQuotaMapper;
import cn.aioa.org.mapper.LeaveRequestMapper;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.mapper.OrgQuotaMapper;
import cn.aioa.org.mapper.ResourceGrantMapper;
import cn.aioa.org.mapper.TenantResourcePoolMapper;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 企业入驻 8 步闭环编排（规格书第三章主链路，本交付的核心）。
 *
 * <pre>
 * 1 租户开通   平台运营端  资源池 token_total > 0
 * 2 建立机构   租户管理员  机构存在且已指定企业管理员
 * 3 资源授权   租户管理员  ≥1 机构配额且 Σ ≤ 资源池；≥1 资源授权
 * 4 分摊规则   租户管理员  ≥1 条 ACTIVE 分摊规则且比例合计 100%
 * 5 组织搭建   企业管理员  ≥1 部门（≤5 层）且 ≥1 员工；Σ 部门额度 ≤ 机构配额
 * 6 能力启用   企业管理员  机构知识库 ≥1 或存在已授权资源
 * 7 成员使用   个人端      机构未冻结；存在请假 / 审批活动
 * 8 结算对账   租户管理员  ≥1 张分摊账单
 * </pre>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OnboardingService {

    public static final int TOTAL_STEPS = 8;

    private final OrgInstitutionMapper institutionMapper;
    private final TenantResourcePoolMapper poolMapper;
    private final OrgQuotaMapper orgQuotaMapper;
    private final DeptQuotaMapper deptQuotaMapper;
    private final ResourceGrantMapper grantMapper;
    private final CostAllocRuleMapper ruleMapper;
    private final CostAllocBillMapper billMapper;
    private final OrgDepartmentMapper deptMapper;
    private final OrgMemberMapper memberMapper;
    private final LeaveRequestMapper leaveMapper;
    private final cn.aioa.org.mapper.OrgStatMapper statMapper;
    private final AuditRecorder audit;

    private record StepDef(int step, String key, String name, String owner, String gate,
                           String route, String routeLabel) {
    }

    /**
     * 8 步定义 —— **步骤名、责任方、门禁、目标页面都只在这里出现一次**。
     *
     * <p>{@code route} 是「该步骤对应的设置页面」的路由（管理端 shell 的路径）。
     * 之前只把路由写在前端，等于「步骤定义」有两份；现在由后端下发，前端只管 push。
     * 前端不得复刻步骤名或路由字面量（否则改一处必漏另一处）。</p>
     *
     * <p>★ 跨端一致性由套件兜底：`e2e_onboarding_8steps.py` 会断言这里下发的每个 route
     * 都真实存在于前端路由表（否则「点了跳到一个不存在的页面」这种静默失败没人会发现）。</p>
     */
    private static final List<StepDef> STEPS = List.of(
            new StepDef(1, "TENANT_PROVISION", "租户开通", "PLATFORM_OPS", "资源池词元套餐总量 > 0",
                    "/quotas", "查看资源池交付"),
            new StepDef(2, "INSTITUTION_BUILD", "建立机构", "TENANT_ADMIN", "机构已建档并指定企业管理员（FR-B2）",
                    "/institutions", "去建立机构"),
            new StepDef(3, "RESOURCE_GRANT", "资源授权", "TENANT_ADMIN", "Σ机构配额 ≤ 资源池总量，且至少授权 1 个资源（FR-C2/FR-E1）",
                    "/resource-grants", "去资源授权"),
            new StepDef(4, "COST_RULE", "分摊规则", "TENANT_ADMIN", "存在 ACTIVE 分摊规则且比例合计 100%（FR-D1）",
                    "/cost-alloc", "去配置分摊规则"),
            new StepDef(5, "ORG_BUILD", "组织搭建", "ORG_ADMIN", "至少 1 个部门（≤5 层）与 1 名员工，Σ部门额度 ≤ 机构配额（FR-G/FR-H1）",
                    "/org-structure", "去搭建组织"),
            new StepDef(6, "CAPABILITY_ON", "能力启用", "ORG_ADMIN", "机构知识库 ≥1 条 或 已授权资源可用（FR-I1/FR-J1）",
                    "/kb", "去启用能力"),
            new StepDef(7, "MEMBER_RUN", "成员使用", "MEMBER", "机构未冻结，且存在请假 / 审批活动（请假流程升级）",
                    "/approvals", "查看审批活动"),
            new StepDef(8, "SETTLE_RECONCILE", "结算对账", "TENANT_ADMIN", "已生成分摊账单并完成账本核对（FR-D2）",
                    "/cost-alloc", "去生成并核对账单"));

    // ================================================================== 进度

    /**
     * 单机构 8 步入驻进度。
     *
     * <p>三种「步态」互不相同，必须分清楚，否则前端会把「没做」和「还不能做」画成一样：</p>
     * <ul>
     *   <li>{@code passed} —— 门禁**实时判定**通过（事实，不是游标）；</li>
     *   <li>{@code unlocked} —— **前序步骤都已「通过或已确认推进」**才为真；未解锁的步骤点了也没意义（顺序性）；</li>
     *   <li>{@code current} —— **第一个未通过的步骤**，即「你现在该做的那一步」；</li>
     *   <li>{@code recorded} —— 由持久化游标 {@code onboardStep} 推出（「已确认推进到」，历史口径，保留兼容）。</li>
     * </ul>
     *
     * <p><b>为什么 unlocked 用「通过或已确认」而不是「全部通过」</b>：第 3/5/7/8 步的门禁是按
     * {@code nowPeriod()} 取数的（配额、部门额度、账单都是「本期」）。跨月后这些门禁会自然变假，
     * 若 unlocked 只看实时门禁，一个已推进到第 6 步的机构会在新月份被**级联锁死** 4~8 步 ——
     * 用户看到的是「明明做过的步骤全变红且后面的都点不动」。故前序只要「通过**或**曾确认推进」即算解锁，
     * 顺序性仍然成立（没做过、也没确认过的步骤依旧拦住后面的），但不会把历史进度吞掉。</p>
     *
     * <p>同理 {@code completed} 保持「游标到位 **或** 8 步全通过」的单调口径，不改成纯实时判定：
     * 否则已入驻机构会在每月 1 号回退成「进行中」。实时门禁的作用是标注**本期**是否满足，
     * 而不是撤销已确认的入驻结论。</p>
     */
    public Map<String, Object> progress(Long tenantId, Long institutionId) {
        OrgInstitution inst = institutionMapper.selectById(institutionId);
        if (inst == null || !tenantId.equals(inst.getTenantId())) {
            throw BizException.notFound("机构不存在于本租户：" + institutionId);
        }
        int reached = inst.getOnboardStep() == null ? 0 : inst.getOnboardStep();

        // 第一遍：先把 8 步全部判定完，才能知道「第一个未通过的步骤」是谁
        // （current / unlocked 都依赖它 —— 顺序性必须由一个全局量推出，不能各步自查）。
        List<Map<String, Object>> evals = new ArrayList<>(TOTAL_STEPS);
        int passed = 0;
        int firstNotPassed = 0;
        int firstUnconfirmed = 0;
        for (StepDef def : STEPS) {
            Map<String, Object> r = evaluate(tenantId, inst, def);
            boolean done = Boolean.TRUE.equals(r.get("passed"));
            boolean recorded = reached >= def.step();
            if (done) {
                passed++;
            } else if (firstNotPassed == 0) {
                firstNotPassed = def.step();
            }
            if (!done && !recorded && firstUnconfirmed == 0) {
                firstUnconfirmed = def.step();
            }
            evals.add(r);
        }

        // 第二遍：生成 8 个步骤项（**恒为 8 条**，未解锁的也返回，前端才能「完整展示 8 个步骤」）。
        List<Map<String, Object>> steps = new ArrayList<>(TOTAL_STEPS);
        boolean prevConfirmed = true;
        String nextAction = null;
        String nextStepName = null;
        String nextStepRoute = null;
        for (int i = 0; i < STEPS.size(); i++) {
            StepDef def = STEPS.get(i);
            Map<String, Object> r = evals.get(i);
            boolean done = Boolean.TRUE.equals(r.get("passed"));
            boolean recorded = reached >= def.step();
            boolean unlocked = prevConfirmed;
            boolean current = firstNotPassed != 0 && def.step() == firstNotPassed;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("step", def.step());
            m.put("key", def.key());
            m.put("name", def.name());
            m.put("owner", def.owner());
            m.put("gate", def.gate());
            m.put("passed", done);
            m.put("reason", r.get("reason"));
            m.put("evidence", r.get("evidence"));
            m.put("recorded", recorded);
            m.put("unlocked", unlocked);
            m.put("current", current);
            // 目标页面：动作路由可能随「当前卡在哪」而不同（见 routeOf），故取评估结果里的覆盖值。
            m.put("route", routeOf(def, r));
            m.put("routeLabel", routeLabelOf(def, r));
            // 未解锁时明确前置依赖，供前端显示「请先完成第 N 步」而不是给一个没反应的按钮。
            m.put("blockedByStep", unlocked ? null : firstUnconfirmed);
            steps.add(m);
            if (current) {
                nextAction = def.name() + "：" + r.get("reason");
                nextStepName = def.name();
                nextStepRoute = routeOf(def, r);
            }
            prevConfirmed = prevConfirmed && (done || recorded);
        }

        // 「当前所处步骤位置」：以实时门禁为准的第一个未通过步骤。
        // 若入驻已确认完成（游标到 8），则不再报「当前步」—— 入驻是一次性过程，完成后不该每月重现。
        Integer currentStep = null;
        if (reached < TOTAL_STEPS && firstNotPassed != 0) {
            currentStep = firstNotPassed;
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("institutionId", institutionId);
        out.put("institutionName", inst.getName());
        out.put("status", inst.getStatus());
        out.put("adminName", inst.getAdminName());
        out.put("onboardStep", reached);
        out.put("passedCount", passed);
        out.put("totalSteps", TOTAL_STEPS);
        out.put("percent", Math.round(passed * 10000.0 / TOTAL_STEPS) / 100.0);
        out.put("completed", reached >= TOTAL_STEPS || passed == TOTAL_STEPS);
        out.put("currentStep", currentStep);
        out.put("currentStepName", currentStep == null ? null : nextStepName);
        out.put("nextAction", nextAction);
        out.put("nextStepRoute", currentStep == null ? null : nextStepRoute);
        out.put("steps", steps);
        return out;
    }

    /**
     * 该步骤「去哪个页面才能过关」。
     *
     * <p>默认取步骤定义里的静态 route；但个别步骤的落点取决于**当前卡在哪个子门禁**——
     * 例如第 3 步「资源授权」可能是「还没分配机构配额」（→ 配额管理），也可能是
     * 「配额有了但没授权资源」（→ 资源授权）。把落点交给评估结果覆盖，
     * 用户点一次就到真正能解决问题的那一页，而不是到了页面还要自己找。</p>
     */
    private String routeOf(StepDef def, Map<String, Object> r) {
        Object override = r == null ? null : r.get("route");
        return override == null ? def.route() : String.valueOf(override);
    }

    private String routeLabelOf(StepDef def, Map<String, Object> r) {
        Object override = r == null ? null : r.get("routeLabel");
        return override == null ? def.routeLabel() : String.valueOf(override);
    }

    /**
     * 步骤定义清单（静态部分）：序号 / key / 名称 / 责任方 / 门禁 / 目标页面。
     *
     * <p>给前端做「向导文案与导航」的唯一来源 —— 避免步骤名与目标页面在前后端各写一份。
     * 与 {@link #progress} 的区别：这里不含任何机构数据，纯定义。</p>
     */
    public List<Map<String, Object>> stepDefinitions() {
        List<Map<String, Object>> out = new ArrayList<>(TOTAL_STEPS);
        for (StepDef def : STEPS) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("step", def.step());
            m.put("key", def.key());
            m.put("name", def.name());
            m.put("owner", def.owner());
            m.put("gate", def.gate());
            m.put("route", def.route());
            m.put("routeLabel", def.routeLabel());
            out.add(m);
        }
        return out;
    }

    private Map<String, Object> evaluate(Long tenantId, OrgInstitution inst, StepDef def) {
        Long iid = inst.getId();
        Map<String, Object> out = new LinkedHashMap<>();
        String period = Vals.nowPeriod();
        try {
            switch (def.step()) {
                case 1 -> {
                    TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                            .eq(TenantResourcePool::getTenantId, tenantId)
                            .orderByDesc(TenantResourcePool::getPeriod)
                            .last("limit 1"));
                    long total = pool == null ? 0L : QuotaService.nz(pool.getTokenTotal());
                    out.put("passed", total > 0);
                    out.put("evidence", Map.of("tokenTotal", total,
                            "period", pool == null ? "" : String.valueOf(pool.getPeriod())));
                    out.put("reason", total > 0 ? null : "资源池尚未交付词元套餐，请平台运营端交付（FR-C1）");
                }
                case 2 -> {
                    boolean hasAdmin = inst.getAdminUserId() != null;
                    out.put("passed", hasAdmin);
                    out.put("evidence", Map.of("code", String.valueOf(inst.getCode()),
                            "adminUserId", inst.getAdminUserId() == null ? 0L : inst.getAdminUserId(),
                            "adminName", inst.getAdminName() == null ? "" : inst.getAdminName()));
                    out.put("reason", hasAdmin ? null : "尚未指定企业管理员（FR-B2）");
                }
                case 3 -> {
                    long sum = orgQuotaMapper.selectList(new LambdaQueryWrapper<OrgQuota>()
                                    .eq(OrgQuota::getTenantId, tenantId)
                                    .eq(OrgQuota::getPeriod, period))
                            .stream().mapToLong(q -> QuotaService.nz(q.getQuotaTokens())).sum();
                    TenantResourcePool pool = poolMapper.selectOne(new LambdaQueryWrapper<TenantResourcePool>()
                            .eq(TenantResourcePool::getTenantId, tenantId)
                            .eq(TenantResourcePool::getPeriod, period).last("limit 1"));
                    long poolTotal = pool == null ? 0L : QuotaService.nz(pool.getTokenTotal());
                    long own = orgQuotaMapper.selectCount(new LambdaQueryWrapper<OrgQuota>()
                            .eq(OrgQuota::getTenantId, tenantId)
                            .eq(OrgQuota::getInstitutionId, iid)
                            .eq(OrgQuota::getPeriod, period));
                    long grants = grantMapper.selectCount(new LambdaQueryWrapper<ResourceGrant>()
                            .eq(ResourceGrant::getInstitutionId, iid)
                            .eq(ResourceGrant::getEnabled, true));
                    boolean ok = own > 0 && (poolTotal == 0 || sum <= poolTotal) && grants > 0;
                    out.put("passed", ok);
                    out.put("evidence", Map.of("orgQuotaAllocated", own > 0,
                            "allocatedSum", sum, "poolTotal", poolTotal, "grantCount", grants));
                    if (!ok) {
                        out.put("reason", own == 0 ? "尚未分配机构配额（FR-C2）"
                                : grants == 0 ? "尚未授权任何资源（FR-E1）"
                                : "Σ机构配额 " + sum + " 超过资源池总量 " + poolTotal);
                        // 卡在子门禁的哪一处，就带用户去能解决它的那一页（本步默认落点是资源授权）。
                        if (own == 0) {
                            out.put("route", "/quotas");
                            out.put("routeLabel", "去分配机构配额");
                        }
                    }
                }
                case 4 -> {
                    List<CostAllocRule> rules = ruleMapper.selectList(new LambdaQueryWrapper<CostAllocRule>()
                            .eq(CostAllocRule::getTenantId, tenantId)
                            .eq(CostAllocRule::getStatus, CostAllocRule.STATUS_ACTIVE));
                    out.put("passed", !rules.isEmpty());
                    out.put("evidence", Map.of("activeRuleCount", rules.size(),
                            "firstRule", rules.isEmpty() ? "" : String.valueOf(rules.get(0).getName()),
                            "version", rules.isEmpty() ? 0 : CostAllocService.nzv(rules.get(0).getVersion())));
                    out.put("reason", rules.isEmpty() ? "尚未配置生效中的分摊规则（FR-D1）" : null);
                }
                case 5 -> {
                    long depts = deptMapper.selectCount(new LambdaQueryWrapper<OrgDepartment>()
                            .eq(OrgDepartment::getInstitutionId, iid));
                    long maxLevel = deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                                    .eq(OrgDepartment::getInstitutionId, iid))
                            .stream().mapToInt(d -> d.getLevel() == null ? 1 : d.getLevel()).max().orElse(0);
                    long members = memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                            .eq(OrgMember::getInstitutionId, iid));
                    OrgQuota oq = orgQuotaMapper.selectOne(new LambdaQueryWrapper<OrgQuota>()
                            .eq(OrgQuota::getTenantId, tenantId)
                            .eq(OrgQuota::getInstitutionId, iid)
                            .eq(OrgQuota::getPeriod, period).last("limit 1"));
                    long deptSum = deptQuotaMapper.selectList(new LambdaQueryWrapper<cn.aioa.org.entity.DeptQuota>()
                                    .eq(cn.aioa.org.entity.DeptQuota::getInstitutionId, iid)
                                    .eq(cn.aioa.org.entity.DeptQuota::getPeriod, period))
                            .stream().mapToLong(d -> QuotaService.nz(d.getQuotaTokens())).sum();
                    long orgCap = oq == null ? 0L : QuotaService.nz(oq.getQuotaTokens());
                    boolean ok = depts > 0 && members > 0 && maxLevel <= OrgTreeService.MAX_DEPTH
                            && (orgCap == 0 || deptSum <= orgCap);
                    out.put("passed", ok);
                    out.put("evidence", Map.of("deptCount", depts, "maxLevel", maxLevel,
                            "memberCount", members, "deptQuotaSum", deptSum, "orgQuota", orgCap));
                    if (!ok) {
                        out.put("reason", depts == 0 ? "尚未创建部门（FR-G1）"
                                : members == 0 ? "尚未登记员工（FR-G2）"
                                : maxLevel > OrgTreeService.MAX_DEPTH ? "部门层级超过 " + OrgTreeService.MAX_DEPTH + " 层"
                                : "Σ部门额度 " + deptSum + " 超过机构配额 " + orgCap);
                    }
                }
                case 6 -> {
                    long kb = grantMapper.selectCount(new LambdaQueryWrapper<ResourceGrant>()
                            .eq(ResourceGrant::getInstitutionId, iid).eq(ResourceGrant::getEnabled, true));
                    long docs = statKb(iid);
                    boolean ok = docs > 0 || kb > 0;
                    out.put("passed", ok);
                    out.put("evidence", Map.of("kbDocs", docs, "enabledGrants", kb));
                    out.put("reason", ok ? null : "机构知识库为空且无已授权资源（FR-I1/FR-J1）");
                }
                case 7 -> {
                    OrgQuota oq = orgQuotaMapper.selectOne(new LambdaQueryWrapper<OrgQuota>()
                            .eq(OrgQuota::getTenantId, tenantId)
                            .eq(OrgQuota::getInstitutionId, iid)
                            .eq(OrgQuota::getPeriod, period).last("limit 1"));
                    boolean frozen = oq != null && Boolean.TRUE.equals(oq.getFrozen());
                    long leaves = leaveMapper.selectCount(new LambdaQueryWrapper<LeaveRequest>()
                            .eq(LeaveRequest::getInstitutionId, iid));
                    boolean ok = !frozen && leaves > 0;
                    out.put("passed", ok);
                    out.put("evidence", Map.of("frozen", frozen, "leaveCount", leaves,
                            "orgStatus", String.valueOf(inst.getStatus())));
                    out.put("reason", frozen ? "机构配额已冻结，成员无法消耗（FR-C3）"
                            : leaves == 0 ? "尚无成员发起请假 / 审批活动" : null);
                }
                case 8 -> {
                    long bills = billMapper.selectCount(new LambdaQueryWrapper<CostAllocBill>()
                            .eq(CostAllocBill::getTenantId, tenantId)
                            .eq(CostAllocBill::getInstitutionId, iid));
                    boolean checked = billMapper.selectCount(new LambdaQueryWrapper<CostAllocBill>()
                            .eq(CostAllocBill::getTenantId, tenantId)
                            .eq(CostAllocBill::getInstitutionId, iid)
                            .eq(CostAllocBill::getLedgerChecked, true)) > 0;
                    out.put("passed", bills > 0);
                    out.put("evidence", Map.of("billCount", bills, "ledgerChecked", checked));
                    out.put("reason", bills > 0 ? null : "尚未生成分摊账单（FR-D2）");
                }
                default -> out.put("passed", false);
            }
        } catch (Exception e) {
            log.warn("evaluate onboard step {} failed: {}", def.step(), e.getMessage());
            out.put("passed", false);
            out.put("reason", "校验异常：" + e.getMessage());
        }
        return out;
    }

    private long statKb(Long institutionId) {
        try {
            return statMapper.countKbOfInstitution(institutionId);
        } catch (Exception e) {
            log.warn("count kb failed for institution {}: {}", institutionId, e.getMessage());
            return 0L;
        }
    }

    // ================================================================== 推进

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> advance(Long tenantId, Long institutionId, Integer step, AuthUser actor) {
        OrgInstitution inst = institutionMapper.selectById(institutionId);
        if (inst == null || !tenantId.equals(inst.getTenantId())) {
            throw BizException.notFound("机构不存在于本租户：" + institutionId);
        }
        int target = step == null ? (inst.getOnboardStep() == null ? 0 : inst.getOnboardStep()) + 1 : step;
        if (target < 1 || target > TOTAL_STEPS) {
            throw BizException.badRequest("入驻步骤必须在 1 ~ " + TOTAL_STEPS + " 之间");
        }
        StepDef def = STEPS.get(target - 1);
        Map<String, Object> r = evaluate(tenantId, inst, def);
        if (!Boolean.TRUE.equals(r.get("passed"))) {
            throw BizException.badRequest("第 " + target + " 步「" + def.name() + "」未满足门禁："
                    + r.get("reason"));
        }
        int before = inst.getOnboardStep() == null ? 0 : inst.getOnboardStep();
        if (target <= before) {
            Map<String, Object> out = progress(tenantId, institutionId);
            out.put("advanced", false);
            out.put("message", "第 " + target + " 步此前已完成，进度保持 " + before);
            return out;
        }
        inst.setOnboardStep(target);
        inst.setUpdatedAt(java.time.LocalDateTime.now());
        institutionMapper.updateById(inst);
        audit.record(tenantId, institutionId, actor, "ONBOARD_ADVANCE", "ORG_INSTITUTION", institutionId,
                "推进入驻第 " + target + " 步「" + def.name() + "」通过门禁校验",
                Map.of("onboardStep", before), Map.of("onboardStep", target, "evidence", r.get("evidence")));
        Map<String, Object> out = progress(tenantId, institutionId);
        out.put("advanced", true);
        out.put("advancedTo", target);
        return out;
    }

    /** 一键推进入驻（逐级尝试，遇到未通过门禁即停止并返回原因）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> advanceAll(Long tenantId, Long institutionId, AuthUser actor) {
        OrgInstitution inst = institutionMapper.selectById(institutionId);
        if (inst == null || !tenantId.equals(inst.getTenantId())) {
            throw BizException.notFound("机构不存在于本租户：" + institutionId);
        }
        int before = inst.getOnboardStep() == null ? 0 : inst.getOnboardStep();
        int reached = before;
        String blockedAt = null;
        for (StepDef def : STEPS) {
            if (def.step() <= before) {
                continue;
            }
            Map<String, Object> r = evaluate(tenantId, inst, def);
            if (!Boolean.TRUE.equals(r.get("passed"))) {
                blockedAt = "第 " + def.step() + " 步「" + def.name() + "」：" + r.get("reason");
                break;
            }
            reached = def.step();
        }
        if (reached > before) {
            inst.setOnboardStep(reached);
            inst.setUpdatedAt(java.time.LocalDateTime.now());
            institutionMapper.updateById(inst);
            audit.record(tenantId, institutionId, actor, "ONBOARD_ADVANCE_ALL", "ORG_INSTITUTION",
                    institutionId, "一键推进入驻进度 " + before + " → " + reached,
                    Map.of("onboardStep", before), Map.of("onboardStep", reached));
        }
        Map<String, Object> out = progress(tenantId, institutionId);
        out.put("advancedFrom", before);
        out.put("advancedTo", reached);
        out.put("blockedAt", blockedAt);
        return out;
    }

    /**
     * 租户端入驻总览：本租户**在运营面**的机构入驻进度聚合。
     *
     * <p>已注销（CLOSED）机构不计入：注销是不可逆终态，不存在「还要推进入驻」的语义，
     * 把它留在总览里既撑大 {@code institutionCount} 又让「未完成步骤」的告警永远清不掉
     * （用户报障原话：「注销了机构，入驻进度还能看到」）。档案口径见
     * {@link cn.aioa.common.org.InstitutionStatus}。</p>
     */
    public Map<String, Object> overview(Long tenantId) {
        LambdaQueryWrapper<OrgInstitution> w = new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .orderByAsc(OrgInstitution::getId);
        OrgInstitution.excludeClosed(w);
        List<OrgInstitution> insts = institutionMapper.selectList(w);
        List<Map<String, Object>> rows = new ArrayList<>(insts.size());
        for (OrgInstitution it : insts) {
            Map<String, Object> p = progress(tenantId, it.getId());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("institutionId", it.getId());
            m.put("institutionName", it.getName());
            m.put("code", it.getCode());
            m.put("status", it.getStatus());
            m.put("adminName", it.getAdminName());
            m.put("onboardStep", p.get("onboardStep"));
            m.put("currentStep", p.get("currentStep"));
            m.put("currentStepName", p.get("currentStepName"));
            m.put("passedCount", p.get("passedCount"));
            m.put("percent", p.get("percent"));
            m.put("completed", p.get("completed"));
            m.put("nextAction", p.get("nextAction"));
            m.put("nextStepRoute", p.get("nextStepRoute"));
            rows.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", tenantId);
        out.put("totalSteps", TOTAL_STEPS);
        out.put("institutionCount", insts.size());
        out.put("completedCount", rows.stream().filter(r -> Boolean.TRUE.equals(r.get("completed"))).count());
        out.put("institutions", rows);
        return out;
    }
}
