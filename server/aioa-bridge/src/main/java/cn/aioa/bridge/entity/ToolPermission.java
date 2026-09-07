package cn.aioa.bridge.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("tool_permission")
public class ToolPermission {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String toolCode;
    private String roleCode;
    private String effect;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
