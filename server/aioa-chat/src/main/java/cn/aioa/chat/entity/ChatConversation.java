package cn.aioa.chat.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_conversation")
public class ChatConversation {

    public static final String STATUS_ACTIVE = "ACTIVE";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long userId;
    private String title;
    private String agentCode;
    private String appCode;
    private String modelRef;
    private String summary;
    private Integer contextTurns;
    private Long msgCount;
    private String status;
    private LocalDateTime lastMsgAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
