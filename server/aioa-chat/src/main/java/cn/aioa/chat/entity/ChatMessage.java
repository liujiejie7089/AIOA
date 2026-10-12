package cn.aioa.chat.entity;

import cn.aioa.common.mybatis.JsonListTypeHandler;
import cn.aioa.common.mybatis.JsonMapTypeHandler;
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
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> contextSnapshot;
    @TableField(typeHandler = JsonListTypeHandler.class)
    private List<Object> citations;
    @TableField(typeHandler = JsonListTypeHandler.class)
    private List<Object> toolCalls;
    /**
     * 对话内上传文档（不进知识库）解析结果快照：[{file_id,name,text,truncated,(error)}]。
     * 与本轮 user 消息同一次 insert 落库，供 AI 参考与历史回填（重新打开会话后 AI 仍看得到文档）。
     * 与 citations / toolCalls 同族：JSON 经 JsonListTypeHandler 持久化与回读。
     */
    @TableField(typeHandler = JsonListTypeHandler.class)
    private List<Object> attachments;
    private String status;
    private Long seq;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
