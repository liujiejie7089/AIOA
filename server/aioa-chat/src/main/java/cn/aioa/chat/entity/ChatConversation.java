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

    /**
     * 绑定的数字员工 ID（V21）：非空表示该会话受该数字员工的职责边界约束，
     * Agent 侧会注入职责范围系统提示，只回答职责范围内的问题。
     */
    private Long workerId;

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
