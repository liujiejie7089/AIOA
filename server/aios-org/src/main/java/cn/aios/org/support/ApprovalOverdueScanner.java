package cn.aios.org.support;

import cn.aios.org.service.ApprovalFlowService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 审批超时扫描（2026-10-19 docs/57：时效治理补位）。
 *
 * <p>此前审批单据提交后只通知一次，挂住之后没有任何自动提醒手段 —— 用户感知到的
 * 「流程不完善」有很大一部分来自这里。本扫描器按固定间隔找出「当前节点」且等待超过
 * 阈值的审批任务，自动催办一次（同一节点 24 小时内最多一次，见
 * {@link ApprovalFlowService#REMIND_THROTTLE_HOURS}）。</p>
 *
 * <p><b>不做自动通过 / 自动驳回</b>：超时就替审批人做决定会改变业务结果，风险远大于收益；
 * 这里只做「提醒 + 留痕」，把决定权留给人。</p>
 *
 * <p>开关：{@code aios.approval.overdue-scan-enabled=false} 可整体关闭；
 * 阈值与间隔分别由 {@code aios.approval.overdue-hours}（默认 24）
 * 与 {@code aios.approval.overdue-scan-ms}（默认 30 分钟）控制。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApprovalOverdueScanner {

    private final ApprovalFlowService flowService;

    @Value("${aios.approval.overdue-hours:24}")
    private int overdueHours;

    @Value("${aios.approval.overdue-scan-enabled:true}")
    private boolean enabled;

    /** 首次执行延迟 2 分钟（避开启动期的 Bean 初始化与 Flyway 迁移），之后按固定间隔。 */
    @Scheduled(initialDelayString = "${aios.approval.overdue-scan-initial-delay-ms:120000}",
            fixedDelayString = "${aios.approval.overdue-scan-ms:1800000}")
    public void scan() {
        if (!enabled) {
            return;
        }
        try {
            flowService.scanOverdueAndRemind(overdueHours);
        } catch (Exception ex) {
            // 扫描失败绝不能影响主流程，也不能让调度线程死掉
            log.warn("审批超时扫描失败（下轮继续）：{}", ex.getMessage());
        }
    }
}
