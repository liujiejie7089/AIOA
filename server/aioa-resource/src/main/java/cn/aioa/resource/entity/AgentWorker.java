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
}
