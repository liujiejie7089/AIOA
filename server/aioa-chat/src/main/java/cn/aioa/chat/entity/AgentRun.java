package cn.aioa.chat.entity;

import cn.aioa.common.mybatis.JsonbMapTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

@Data
@TableName(value = "agent_run", autoResultMap = true)
public class AgentRun {

    public static final String STATUS_RUNNING = "RUNNING";
    public static final String STATUS_SUCCEEDED = "SUCCEEDED";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_CANCELLED = "CANCELLED";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String runId;
    private Long conversationId;
    private Long userId;
    private String status;
    @TableField(typeHandler = JsonbMapTypeHandler.class)
    private Map<String, Object> plan;
    private Integer currentStep;
    private String error;
    private Integer tokensIn;
    private Integer tokensOut;
    private LocalDateTime startedAt;
    private LocalDateTime endedAt;
    private Long durationMs;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
