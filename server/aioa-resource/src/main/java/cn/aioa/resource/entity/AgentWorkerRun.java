package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 数字员工执行记录（V15）：每次真实运行一条留痕，管理端/用户端可追溯。
 * triggerType: SCHEDULE 定时到点 / MANUAL 手动触发。
 * status: SUCCESS / FAILED。
 */
@Data
@TableName("agent_worker_run")
public class AgentWorkerRun {

    public static final String TRIGGER_SCHEDULE = "SCHEDULE";
    public static final String TRIGGER_MANUAL = "MANUAL";

    public static final String STATUS_SUCCESS = "SUCCESS";
    public static final String STATUS_FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long workerId;

    private String workerName;

    private String triggerType;

    private String status;

    /** 执行产出（模型真实生成） */
    private String output;

    private String errorMsg;

    /** 执行所用模型 */
    private String model;

    private Long durationMs;

    private LocalDateTime startedAt;

    private LocalDateTime finishedAt;

    private LocalDateTime createdAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
