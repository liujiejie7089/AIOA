package cn.aioa.org.support;

import cn.aioa.common.event.TenantProvisionedEvent;
import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.mapper.OrgDutyMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 租户职务字典播种（补齐 V41 遗留的初始化缺口）。
 *
 * <p><b>为什么必要</b>：{@code org_duty} 由 V41 一次性迁移播种，那句 SQL 只覆盖
 * 「V41 执行时已存在」的租户。此后新建的租户字典为空 —— 而四期的
 * {@code DEPT_DUTY} / {@code UNIT_DUTY} 正是按职务字典求值处理人的，
 * 字典为空会让「按职务审批」的流程静默退化成兜底改派。
 * V41 的注释里已承诺「新租户由入驻播种器补齐，见 DutyProvisioner」，
 * 但该组件当时并未落地 —— 本类把这句话补上。</p>
 *
 * <p><b>幂等</b>：按 {@code (tenant_id, code)} 判重，只补缺、不覆盖 ——
 * 租户管理员改过的职务名 / 排序不会被塞回去。</p>
 *
 * <p><b>失败不影响主流程</b>：入驻是主流程，播种只是增强，异常一律吞掉并记 warn
 * （与 {@code ApprovalFlowProvisioner} 同一纪律）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DutyProvisioner {

    /**
     * 基础职务字典四条（与 V41 的内联种子保持同一口径）。
     *
     * <p>{@code canApprove} 是本字典最关键的语义：{@code STAFF} 明确不可作为审批人，
     * 避免「把普通成员配成审批节点」这类配置把审批链变成走过场。</p>
     */
    private record Seed(String code, String name, int rank, boolean canApprove, String scope) {
    }

    private static final java.util.List<Seed> DUTIES = java.util.List.of(
            new Seed(OrgDuty.DEPT_PRINCIPAL, "部门正职", 1, true, "DEPT"),
            new Seed(OrgDuty.DEPT_DEPUTY, "部门副职", 2, true, "DEPT"),
            new Seed(OrgDuty.ORG_LEADER, "机构负责人", 0, true, "ORG"),
            new Seed(OrgDuty.STAFF, "普通成员", 9, false, "DEPT"));

    private final OrgDutyMapper dutyMapper;

    @EventListener
    public void onTenantProvisioned(TenantProvisionedEvent event) {
        try {
            int n = provisionIfAbsent(event.tenantId());
            if (n > 0) {
                log.info("租户 {} 新机构「{}」入驻，已播种职务字典 {} 条",
                        event.tenantId(), event.institutionName(), n);
            }
        } catch (Exception ex) {
            log.warn("租户 {} 播种职务字典失败（不影响机构入驻）：{}", event.tenantId(), ex.getMessage());
        }
    }

    /**
     * 补齐该租户缺失的基础职务。
     *
     * @return 实际新插入条数（0 = 已齐备）
     */
    public int provisionIfAbsent(Long tenantId) {
        if (tenantId == null || tenantId == 0L) {
            return 0; // 平台侧（tenant 0）不需要职务字典
        }
        int n = 0;
        for (Seed s : DUTIES) {
            long exists = dutyMapper.selectCount(new LambdaQueryWrapper<OrgDuty>()
                    .eq(OrgDuty::getTenantId, tenantId)
                    .eq(OrgDuty::getCode, s.code()));
            if (exists > 0) {
                continue;
            }
            OrgDuty d = new OrgDuty();
            d.setTenantId(tenantId);
            d.setCode(s.code());
            d.setName(s.name());
            d.setDutyRank(s.rank());
            d.setCanApprove(s.canApprove());
            d.setScope(s.scope());
            d.setStatus(OrgDuty.STATUS_ACTIVE);
            d.setRemark("入驻自动播种的基础职务字典");
            d.setCreatedAt(LocalDateTime.now());
            d.setCreatedBy(0L);
            dutyMapper.insert(d);
            n++;
        }
        return n;
    }
}
