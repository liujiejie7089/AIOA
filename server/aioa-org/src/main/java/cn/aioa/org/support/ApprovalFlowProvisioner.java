package cn.aioa.org.support;

import cn.aioa.common.event.TenantProvisionedEvent;
import cn.aioa.org.entity.ApprovalFlowDef;
import cn.aioa.org.mapper.ApprovalFlowDefMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 租户级默认审批流播种（补齐 D-8「新租户初始化缺口」）。
 *
 * <p><b>解决的问题</b>：默认审批流此前只靠一次性迁移 V26 播种，而 V26 只覆盖
 * 「当时已存在」的租户 —— 之后新建的租户（如演示租户 9）一条默认流都没有，
 * 于是 {@code ApprovalFlowService} 只能退到「内置单级 ORG_ADMIN」兜底：
 * 企业管理员一人同意即生效，静默绕过了租户管理员这道关；请假链路更是直接不可用。</p>
 *
 * <p><b>现在</b>：企业域新建机构（入驻）时发布 {@link TenantProvisionedEvent}，
 * 本组件监听后为该租户补齐缺失的默认流程。与 {@code WorkerTemplateProvisioner}
 * 同一套机制 —— 企业域与能力域通过 {@code aioa-common} 的事件解耦。</p>
 *
 * <p><b>幂等</b>：按 {@code (tenant_id, institution_id=0, biz_type)} 逐条判重，
 * 只补缺、不覆盖 —— 租户管理员改过的流程不会被塞回去。</p>
 *
 * <p><b>失败不影响主流程</b>：入驻是主流程，播种只是增强，异常一律吞掉并记 warn。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApprovalFlowProvisioner {

    /** 租户级默认流（institution_id = 0），机构未单独配置时自动生效。 */
    private record Seed(String bizType, String name, String stepsJson) {
    }

    /**
     * 权限申请默认走「按申请人层级<b>向上 1 级</b>」+ 抄送企业管理员。
     *
     * <p>用户诉求：普通用户申请权限，「由部门负责人进行上一级审批即可」。引擎的
     * {@code levels} 参数即此语义 —— 从申请人自身的上一级取第一个有效梯级：</p>
     *
     * <pre>
     * 普通成员   levels=1 → 部门负责人
     * 部门负责人 levels=1 → 企业管理员
     * 企业管理员 levels=1 → 租户管理员
     * 租户管理员 levels=1 → 平台管理员
     * </pre>
     *
     * <p>{@code cc:[ORG_ADMIN]} 是必要的配套：一级审批让企业管理员不再位于链上
     * （V39 曾为此把链拉长成整链递推，代价是所有人都要等两级）。改用知会做到
     * <b>「不审批但可见、可督办」</b> —— 见 {@code ApprovalFlowService.expandCcNodes}。</p>
     *
     * <p>老租户已被 V42 统一迁移到同一口径；此处保证<b>新租户入驻时</b>自动拿到它。
     * 机构若单独配了流程，那是管理员的显式选择，不在本播种器职责内。</p>
     */
    private static final List<Seed> DEFAULTS = List.of(
            new Seed("PERMISSION_GRANT",
                    "租户默认权限申请审批流（部门负责人一级审批 + 抄送企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"APPLICANT_SUPERIOR\", \"levels\": 1, "
                            + "\"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("LEAVE",
                    "租户默认请假审批流（部门负责人 → 企业管理员，≤3 天跳级）",
                    // cc:[ORG_ADMIN]：跳级（≤3 天）时企业管理员仍应知情（V44 回填同口径）
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\", \"threshold_days\": 3}]"),
            new Seed("QUOTA_EXPAND",
                    "租户默认额度扩容审批流（企业管理员 → 租户管理员）",
                    // cc:[TENANT_ADMIN]：终审人（租户管理员）以知会方式可督办（V44 回填同口径）
                    "[{\"seq\": 1, \"approver_type\": \"ORG_ADMIN\", \"cc\": [\"TENANT_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"TENANT_ADMIN\"}]"),
            new Seed("RESOURCE_OPEN",
                    "租户默认资源开通审批流（企业管理员 → 租户管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"ORG_ADMIN\", \"cc\": [\"TENANT_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"TENANT_ADMIN\"}]")
    );

    private final ApprovalFlowDefMapper defMapper;

    @EventListener
    public void onTenantProvisioned(TenantProvisionedEvent event) {
        try {
            int n = provisionIfAbsent(event.tenantId());
            if (n > 0) {
                log.info("租户 {} 新机构「{}」入驻，已播种默认审批流 {} 条",
                        event.tenantId(), event.institutionName(), n);
            }
        } catch (Exception ex) {
            log.warn("租户 {} 播种默认审批流失败（不影响机构入驻）：{}",
                    event.tenantId(), ex.getMessage());
        }
    }

    /**
     * 补齐该租户缺失的租户级默认流程。
     *
     * @return 实际新插入的条数（0 表示已齐备）
     */
    public int provisionIfAbsent(Long tenantId) {
        if (tenantId == null || tenantId == 0L) {
            return 0; // 平台侧（tenant 0）不需要默认流
        }
        int n = 0;
        for (Seed s : DEFAULTS) {
            long exists = defMapper.selectCount(new LambdaQueryWrapper<ApprovalFlowDef>()
                    .eq(ApprovalFlowDef::getTenantId, tenantId)
                    .eq(ApprovalFlowDef::getInstitutionId, 0L)
                    .eq(ApprovalFlowDef::getBizType, s.bizType()));
            if (exists > 0) {
                continue;
            }
            ApprovalFlowDef def = new ApprovalFlowDef();
            def.setTenantId(tenantId);
            def.setInstitutionId(0L);
            def.setBizType(s.bizType());
            def.setName(s.name());
            def.setStepsJson(s.stepsJson());
            def.setStatus("ACTIVE");
            def.setRemark("租户级默认流程：机构未单独配置时自动生效（入驻自动播种）");
            def.setCreatedAt(LocalDateTime.now());
            def.setCreatedBy(0L);
            defMapper.insert(def);
            n++;
        }
        return n;
    }
}
