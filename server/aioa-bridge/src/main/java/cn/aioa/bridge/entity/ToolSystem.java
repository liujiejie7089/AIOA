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
 * 对接的业务系统（M1 只有实体，M2 实现调用）。
 */
@Data
@TableName(value = "tool_system", autoResultMap = true)
public class ToolSystem {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String systemCode;
    private String name;
    private String baseUrl;
    private String healthUrl;
    private String authType;
    private String authRef;
    private Integer timeoutMs;
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> circuitBreaker;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
