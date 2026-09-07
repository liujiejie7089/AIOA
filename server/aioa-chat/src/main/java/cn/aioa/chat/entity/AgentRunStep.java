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
@TableName(value = "agent_run_step", autoResultMap = true)
public class AgentRunStep {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String runId;
    private Integer stepSeq;
    private String stepType;
    private String agentCode;
    private String toolCode;
    @TableField(typeHandler = JsonbMapTypeHandler.class)
    private Map<String, Object> inputMasked;
    private String outputDigest;
    private String status;
    private Long durationMs;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
