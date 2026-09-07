package cn.aioa.chat.entity;

import cn.aioa.common.mybatis.JsonbListTypeHandler;
import cn.aioa.common.mybatis.JsonbMapTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Data
@TableName(value = "chat_message", autoResultMap = true)
public class ChatMessage {

    public static final String ROLE_USER = "user";
    public static final String ROLE_ASSISTANT = "assistant";
    public static final String ROLE_SYSTEM = "system";
    public static final String STATUS_OK = "OK";
    public static final String STATUS_FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long conversationId;
    private String runId;
    private String role;
    private String content;
    private String contentType;
    private Integer tokens;
    @TableField(typeHandler = JsonbMapTypeHandler.class)
    private Map<String, Object> contextSnapshot;
    @TableField(typeHandler = JsonbListTypeHandler.class)
    private List<Object> citations;
    @TableField(typeHandler = JsonbListTypeHandler.class)
    private List<Object> toolCalls;
    private String status;
    private Long seq;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
