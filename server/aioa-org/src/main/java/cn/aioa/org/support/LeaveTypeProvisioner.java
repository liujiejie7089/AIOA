package cn.aioa.org.support;

import cn.aioa.common.event.TenantProvisionedEvent;
import cn.aioa.org.entity.LeaveType;
import cn.aioa.org.mapper.LeaveTypeMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 租户假种字典播种（补齐 D-8「新租户初始化缺口」的假种一环）。
 *
 * <p><b>为什么必要</b>：{@code leave_type} 此前只由一次性迁移 V24 播种，而 V24 只覆盖
 * 「当时已存在」的租户。此后入驻的租户假种表为空，{@link cn.aioa.org.service.LeaveService}
 * 提交请假时按 {@code leaveTypeCode} 查假种 → 查不到 → 直接拒单；
 * 用户端的假种下拉也是空的。也就是说新租户的请假能力<b>开箱不可用</b>，
 * 而不是「配置不全」——这是功能缺失，不是体验问题。</p>
 *
 * <p><b>与既有播种器的关系</b>：入驻事件 {@link TenantProvisionedEvent} 现在有三个监听者：
 * {@code ApprovalFlowProvisioner}（默认审批流）、{@link DutyProvisioner}（职务字典）、
 * 本类（假种字典）。企业域与能力域通过 {@code aioa-common} 的事件解耦，
 * 各自只补自己那本字典。</p>
 *
 * <p><b>幂等</b>：按 {@code (tenant_id, code)} 判重，只补缺、不覆盖 ——
 * 租户管理员调过的额度 / 证明要求不会被塞回去。整个租户已有<b>任何</b>假种时不介入
 * （说明是显式配置过的租户，缺哪个是选择而非遗漏）。</p>
 *
 * <p><b>失败不影响主流程</b>：入驻是主流程，播种只是增强，异常一律吞掉并记 warn。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LeaveTypeProvisioner {

    /**
     * 标准假种六条（与 V24 内联种子、租户 2 的实际配置同一口径）。
     *
     * <p>额度取值不是随意填的：年假 10 天 / 病假 15 天 / 事假 0 天（不占额度，只走审批）
     * 与既有 E2E 套件对 {@code fagai_li} 的额度断言一致；改动此处会让配额类套件集体变红，
     * 所以新租户必须拿到同一套数字。</p>
     */
    private record Seed(String code, String name, String unit, String quota,
                        boolean needProof, int advanceDays, String maxConsecutive,
                        boolean paid, int sort) {
    }

    private static final List<Seed> TYPES = List.of(
            new Seed("ANNUAL", "年假", "WORKDAY", "10.0", false, 3, "15.0", true, 10),
            new Seed("SICK", "病假", "WORKDAY", "15.0", true, 0, "30.0", true, 20),
            new Seed("CASUAL", "事假", "WORKDAY", "0.0", false, 1, "10.0", false, 30),
            new Seed("MARRIAGE", "婚假", "DAY", "3.0", true, 7, "3.0", true, 40),
            new Seed("MATERNITY", "产假", "DAY", "98.0", true, 30, "98.0", true, 50),
            new Seed("COMP", "调休", "WORKDAY", "5.0", false, 0, "5.0", true, 60));

    private final LeaveTypeMapper typeMapper;

    @EventListener
    public void onTenantProvisioned(TenantProvisionedEvent event) {
        try {
            int n = provisionIfAbsent(event.tenantId());
            if (n > 0) {
                log.info("租户 {} 新机构「{}」入驻，已播种假种字典 {} 条",
                        event.tenantId(), event.institutionName(), n);
            }
        } catch (Exception ex) {
            log.warn("租户 {} 播种假种字典失败（不影响机构入驻）：{}", event.tenantId(), ex.getMessage());
        }
    }

    /**
     * 补齐该租户缺失的标准假种。
     *
     * <p>「只补缺」的判定分两层，第二层是关键：该租户若已有<b>任意</b>假种，
     * 说明管理员显式配过（哪怕只留了一条），此时不介入；只有整张表为空才按标准套补齐。
     * 这样既修好了「新租户开箱不可用」，又不会把管理员删掉不用的假种塞回来。</p>
     *
     * @return 实际新插入条数（0 = 已有假种配置或无需播种）
     */
    public int provisionIfAbsent(Long tenantId) {
        if (tenantId == null || tenantId == 0L) {
            return 0; // 平台侧（tenant 0）不需要假种
        }
        long any = typeMapper.selectCount(new LambdaQueryWrapper<LeaveType>()
                .eq(LeaveType::getTenantId, tenantId));
        if (any > 0) {
            return 0; // 显式配置过的租户，缺哪个是选择而非遗漏
        }
        int n = 0;
        for (Seed s : TYPES) {
            LeaveType t = new LeaveType();
            t.setTenantId(tenantId);
            t.setCode(s.code());
            t.setName(s.name());
            t.setUnit(s.unit());
            t.setQuotaDaysPerYear(new BigDecimal(s.quota()));
            t.setNeedProof(s.needProof());
            t.setAdvanceDays(s.advanceDays());
            t.setMaxConsecutiveDays(new BigDecimal(s.maxConsecutive()));
            t.setPaid(s.paid());
            t.setSort(s.sort());
            t.setStatus("ENABLED");
            t.setCreatedAt(LocalDateTime.now());
            t.setCreatedBy(0L);
            typeMapper.insert(t);
            n++;
        }
        return n;
    }
}
