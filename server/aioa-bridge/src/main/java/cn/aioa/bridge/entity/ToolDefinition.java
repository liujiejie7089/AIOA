package cn.aioa.bridge.entity;

import cn.aioa.common.mybatis.JsonMapTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 工具定义（M1 只有实体，M2 实现调用）。
 */
@Data
@TableName(value = "tool_definition", autoResultMap = true)
public class ToolDefinition {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String toolCode;
    private String version;
    private String name;
    private String description;
    private String domain;
    private String systemCode;
    private String endpoint;
    private String httpMethod;
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> inputSchema;
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> outputSchema;
    private String riskLevel;
    private Boolean requiresApproval;
    private Boolean idempotencyRequired;
    private Integer timeoutMs;
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> retryPolicy;
    private String rateLimit;
    private String authType;
    private String authRef;
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> paramMapping;
    private String responseJmespath;
    private Long maxBytes;
    private String status;
    private String owner;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
