package cn.aioa.bridge.entity;

import cn.aioa.common.mybatis.JsonbMapTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 工具调用日志（只保留 created_at 等少量列）。
 */
@Data
@TableName(value = "tool_invocation_log", autoResultMap = true)
public class ToolInvocationLog {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String traceId;
    private String runId;
    private Long stepId;
    private String toolCode;
    private String version;
    private Long userId;
    @TableField(typeHandler = JsonbMapTypeHandler.class)
    private Map<String, Object> argsMasked;
    private String resultDigest;
    private Long resultSize;
    private Integer httpStatus;
    private Long durationMs;
    private String approvalId;
    private String errorCode;
    private LocalDateTime createdAt;
}
