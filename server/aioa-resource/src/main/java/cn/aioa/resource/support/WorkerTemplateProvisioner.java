package cn.aioa.resource.support;

import cn.aioa.common.event.TenantProvisionedEvent;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 租户级数字员工预置（补齐 V1.2 遗留短板）。
 *
 * <p><b>解决的问题</b>：此前预置只靠一次性脚本 {@code scripts/seed_worker_templates.py}，
 * 新入驻的租户不在脚本名单里 → 数字员工列表为空、页面白板、用户无从下手。</p>
 *
 * <p><b>现在</b>：企业域新建机构（入驻）时发布 {@link TenantProvisionedEvent}，
 * 本组件监听后把平台全局模板（{@code tenant_id=0 且 is_template=1}）复制一套到该租户。
 * 企业域与能力域只通过 aioa-common 的事件解耦，不产生模块间横向依赖。</p>
 *
 * <p><b>幂等</b>：以「该租户历史上是否出现过任何数字员工」为判据（含已逻辑删除的行），
 * 一生只预置一次——租户把预置员工全部删除后不会被重复塞回来。</p>
 *
 * <p><b>失败不影响主流程</b>：入驻是主流程，预置只是增强，异常一律吞掉并记 warn。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WorkerTemplateProvisioner {

    /** 平台模板所在租户（全局模板库）。 */
    public static final long PLATFORM_TENANT_ID = 0L;

    private final AgentWorkerMapper workerMapper;

    @EventListener
    public void onTenantProvisioned(TenantProvisionedEvent event) {
        try {
            // 预置的是「租户公共数字员工」：归属留空（租户级），不绑定触发入驻的那一家机构。
            // 否则该机构一旦注销/停用，预置资产就会挂在一家失效机构名下。
            int n = provisionIfAbsent(event.tenantId(), null);
            if (n > 0) {
                log.info("租户 {} 新机构「{}」入驻，已预置数字员工 {} 个",
                        event.tenantId(), event.institutionName(), n);
            }
        } catch (Exception ex) {
            log.warn("租户 {} 预置数字员工失败（不影响机构入驻）：{}", event.tenantId(), ex.getMessage());
        }
    }

    /**
     * 幂等预置：该租户历史上从未有过数字员工时才复制模板。
     *
     * @param tenantId      目标租户
     * @param institutionId 归属机构；传 null 表示「租户级公共资产」（推荐，见
     *                      {@link #onTenantProvisioned}）
     * @return 实际新插入的条数
     */
    public int provisionIfAbsent(Long tenantId, Long institutionId) {
        if (tenantId == null || PLATFORM_TENANT_ID == tenantId) {
            return 0;
        }
        if (workerMapper.countAllByTenant(tenantId) > 0) {
            return 0;
        }
        List<AgentWorker> templates = workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                .eq(AgentWorker::getTenantId, PLATFORM_TENANT_ID)
                .eq(AgentWorker::getIsTemplate, 1)
                .orderByAsc(AgentWorker::getId));
        if (templates.isEmpty()) {
            log.warn("平台模板库为空（tenant_id=0 且 is_template=1 无数据），租户 {} 未预置", tenantId);
            return 0;
        }
        int n = 0;
        for (AgentWorker tpl : templates) {
            workerMapper.insert(copyOf(tpl, tenantId, institutionId));
            n++;
        }
        return n;
    }

    /** 模板 → 租户实例：只复制样板字段，不复制 tenant_id、状态与运行记录。 */
    private static AgentWorker copyOf(AgentWorker tpl, Long tenantId, Long institutionId) {
        AgentWorker w = new AgentWorker();
        w.setTenantId(tenantId);
        w.setInstitutionId(institutionId);
        w.setName(tpl.getName());
        w.setIcon(tpl.getIcon());
        w.setDescription(tpl.getDescription());
        w.setWorkerType(tpl.getWorkerType());
        w.setRunMode(tpl.getRunMode() == null ? AgentWorker.RUN_MODE_ON_DEMAND : tpl.getRunMode());
        w.setScheduleText(tpl.getScheduleText());
        w.setScheduleTime(tpl.getScheduleTime());
        w.setTaskPrompt(tpl.getTaskPrompt());
        w.setStatus(AgentWorker.STATUS_IDLE);
        w.setEnabled(1);
        w.setCreatedBy(0L);
        w.setVisibleScope("TENANT");
        w.setSourceTemplateId(tpl.getId());
        w.setIsTemplate(0);
        w.setCreatedAt(LocalDateTime.now());
        w.setUpdatedAt(LocalDateTime.now());
        return w;
    }
}
