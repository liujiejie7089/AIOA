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

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String name;

    private String icon;

    private String description;

    private String status;

    /** 最近产出摘要 */
    private String lastOutput;

    /** 运行计划说明 */
    private String scheduleText;

    /** 1=启用 0=停用 */
    private Integer enabled;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
