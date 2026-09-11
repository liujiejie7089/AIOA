package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 数字员工（V1.2 新增）：自动运行 · 定时产出 · 结果进入待办与消息。
 * icon 存图标键（bot / bell / pen 等），由前端映射为矢量图标，不存 emoji。
 * enabled=0 时 status 展示为「已停用」，历史产出保留。
 */
@Data
@TableName("agent_worker")
public class AgentWorker {

    public static final String STATUS_RUNNING = "运行中";
    public static final String STATUS_IDLE = "待命中";
    /** 已启用但未配置执行时刻/任务内容——不会真正执行，需引导用户补全 */
    public static final String STATUS_PENDING_CONFIG = "待配置";
    /** 已停用：enabled=0，历史产出保留 */
    public static final String STATUS_DISABLED = "已停用";

    /** 运行模式·定时型：必须配置执行时刻，缺时刻才判「待配置」 */
    public static final String RUN_MODE_SCHEDULED = "SCHEDULED";
    /** 运行模式·事件驱动：由业务事件触发（如请假申请到达），不需要执行时刻 */
    public static final String RUN_MODE_EVENT = "EVENT";
    /** 运行模式·按需唤起：用户随时发起，不需要执行时刻 */
    public static final String RUN_MODE_ON_DEMAND = "ON_DEMAND";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String name;

    private String icon;

    private String description;

    private String status;

    /** 最近产出摘要 */
    private String lastOutput;

    /**
     * 角色类型（V21）：决定职责边界与所需权限，取值见
     * {@link cn.aioa.resource.support.WorkerRole}。默认 GENERAL。
     */
    private String workerType;

    /**
     * 运行模式（V22）：SCHEDULED 定时 / EVENT 事件驱动 / ON_DEMAND 按需唤起。
     * 决定「待配置」判定——只有定时型才要求执行时刻，避免事件驱动型被误标未配置。
     */
    private String runMode;

    /** 运行计划说明 */
    private String scheduleText;

    /** 每日执行时刻 HH:mm（如 08:00），空=不定时。到点由 WorkerScheduler 真实执行 */
    private String scheduleTime;

    /** 到点执行的任务内容（交给模型真实执行） */
    private String taskPrompt;

    /** 最近一次定时执行时间（用于防止同一天重复执行） */
    private LocalDateTime lastRunAt;

    /** 1=启用 0=停用 */
    private Integer enabled;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;

    /**
     * 是否需要「执行时刻」才算配置完成。纯函数，无副作用，便于单测。
     *
     * <p>只有定时型需要执行时刻；事件驱动（EVENT）与按需唤起（ON_DEMAND）本就不应有执行时刻。
     * {@code runMode} 为空按历史数据（V22 之前）处理为定时型，保持原语义不突变。</p>
     */
    public static boolean requiresScheduleTime(String runMode) {
        return runMode == null || runMode.isBlank() || RUN_MODE_SCHEDULED.equals(runMode);
    }

    /**
     * 展示状态判定。纯函数，无副作用，便于单测。
     *
     * <p>规则：停用 → 「已停用」；定时型缺执行时刻 → 「待配置」；其余用库内状态。
     * 修复 D-2：事件驱动/按需唤起的员工不再被误标为「待配置」。</p>
     */
    public static String resolveStatus(String runMode, String scheduleTime, String storedStatus, boolean enabled) {
        if (!enabled) {
            return STATUS_DISABLED;
        }
        if (requiresScheduleTime(runMode) && (scheduleTime == null || scheduleTime.isBlank())) {
            return STATUS_PENDING_CONFIG;
        }
        return (storedStatus == null || storedStatus.isBlank()) ? STATUS_RUNNING : storedStatus;
    }
}
