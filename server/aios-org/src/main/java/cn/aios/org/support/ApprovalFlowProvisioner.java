package cn.aios.org.support;

import cn.aios.common.event.TenantProvisionedEvent;
import cn.aios.org.entity.ApprovalFlowDef;
import cn.aios.org.mapper.ApprovalFlowDefMapper;
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
 * 同一套机制 —— 企业域与能力域通过 {@code aios-common} 的事件解耦。</p>
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
                            + "{\"seq\": 2, \"approver_type\": \"TENANT_ADMIN\"}]"),
            // ---- 删除类（2026-09-28 需求：级联前置校验 + 上一级审核）----
            // 语义：APPLICANT_SUPERIOR + levels=1 = 只取「申请人的上一级」这一个梯级。
            //   部门删除：部门负责人 → 机构管理员；机构管理员 → 租户管理员；租户管理员 → 平台管理员
            //   机构删除：申请人=机构管理员 → 租户管理员
            //   租户删除：申请人=租户管理员 → 平台管理员
            // ⚠️ 这三条**必须存在**：ApprovalFlowService.expandNodes 在「该 bizType 没有 ACTIVE
            //    流程定义」时会退化成单节点默认审批人（DEFAULT_APPROVER_TYPE = ORG_ADMIN），
            //    对删除类单据会把审批人**静默指错**（删租户本应指到平台管理员）。
            //    部门那一层尤其要注意：申请人可能就是部门负责人，兜底会把它派给机构管理员
            //    而实际想派的是机构管理员…… 但若申请人是机构管理员本人，兜底就会变成「自己审自己」。
            new Seed("DEPT_DELETE",
                    "租户默认部门删除审批流（上一级审批）",
                    "[{\"seq\": 1, \"approver_type\": \"APPLICANT_SUPERIOR\", \"levels\": 1}]"),
            new Seed("INSTITUTION_DELETE",
                    "租户默认机构删除审批流（上一级审批）",
                    "[{\"seq\": 1, \"approver_type\": \"APPLICANT_SUPERIOR\", \"levels\": 1}]"),
            new Seed("TENANT_DELETE",
                    "租户默认租户删除审批流（上一级审批）",
                    "[{\"seq\": 1, \"approver_type\": \"APPLICANT_SUPERIOR\", \"levels\": 1}]"),

            // ---- 员工侧业务（2026-10-19 docs/57：四段断裂修复）----
            // 背景：43 个模块的 worker_capability 已指向这些 biz_type，但此前**没有对应流程定义**，
            //   ApprovalFlowService.expandNodes 会退化成单节点 ORG_ADMIN（审批人指错且无法分级）。
            //   老租户由 V89 回填补齐，新租户靠本播种器拿到同一口径。
            // 口径：涉钱/涉章/涉合同 = 两级（部门负责人 → 企业管理员）；
            //       一般申请 = 一级（部门负责人，抄送企业管理员可督办）。
            new Seed("EXPENSE",
                    "租户默认费用报销审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("SEAL",
                    "租户默认用印审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("CONTRACT",
                    "租户默认合同审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("PURCHASE",
                    "租户默认采购审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("FINANCE_APPLY",
                    "租户默认财务审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("ASSET",
                    "租户默认资产领用审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("PROJECT_CREATE",
                    "租户默认项目立项审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("HR_REGISTER",
                    "租户默认人事审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("RECRUIT_REQ",
                    "租户默认招聘需求审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("INTEGRATION_REQ",
                    "租户默认系统集成审批流（部门负责人 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}, "
                            + "{\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]"),
            new Seed("TRAVEL",
                    "租户默认出差审批流（部门负责人，抄送企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("VEHICLE",
                    "租户默认用车审批流（部门负责人，抄送企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("ARCHIVE_BORROW",
                    "租户默认档案借阅审批流（部门负责人，抄送企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("ATTENDANCE_APPEAL",
                    "租户默认考勤申诉审批流（部门负责人，抄送企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("TRAIN_SIGNUP",
                    "租户默认培训报名审批流（部门负责人，抄送企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("MEETING_BOOK",
                    "租户默认会议预定审批流（部门负责人）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("UNION_APPLY",
                    "租户默认工会审批流（部门负责人）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("PARTY_APPLY",
                    "租户默认党务审批流（部门负责人）",
                    "[{\"seq\": 1, \"approver_type\": \"DEPT_LEADER\", \"cc\": [\"ORG_ADMIN\"]}]"),
            new Seed("SECURITY_APPLY",
                    "租户默认安全与权限审批流（上一级 → 企业管理员）",
                    "[{\"seq\": 1, \"approver_type\": \"APPLICANT_SUPERIOR\", \"levels\": 1, "
                            + "\"cc\": [\"ORG_ADMIN\"]}, {\"seq\": 2, \"approver_type\": \"ORG_ADMIN\"}]")
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
