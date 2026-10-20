package cn.aios.resource.connector.mail.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 邮件草稿（落库，不直接发信）。status ∈ {DRAFT, SENT, FAILED}。
 * request_id 为幂等键，可空（历史草稿不带幂等键）；同 (tenant,user,request_id) 唯一。
 */
@Data
@TableName("connector_mail_draft")
public class ConnectorMailDraft {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long userId;
    private String toAddr;
    private String ccAddr;
    private String subject;
    private String body;
    private String requestId;
    private String status;
    private LocalDateTime sentAt;
    private String messageId;
    private String lastError;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
