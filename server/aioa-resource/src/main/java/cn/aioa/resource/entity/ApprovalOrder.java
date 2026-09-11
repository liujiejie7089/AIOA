package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 审批单（FR-D6 审批卡点）：用户端发起的对外发布类审批。
 * status: PENDING 待审 / APPROVED 通过 / REJECTED 驳回
 */
@Data
@TableName("approval_order")
public class ApprovalOrder {

    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_APPROVED = "APPROVED";
    public static final String STATUS_REJECTED = "REJECTED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 发起人 */
    private Long userId;

    /** 发起人姓名（提交时快照，管理端审批中心展示） */
    private String applicantName;

    private String runId;

    private Long conversationId;

    /** 关联成果ID（bizType=RESULT 时审批结果回写成果状态） */
    private Long resultId;

    private String bizType;

    private String title;

    private String content;

    /** 结构化表单 JSON（如请假 {leaveType,start,end,reason}）；无则为 null */
    private String formData;

    /** 附件 JSON 数组 [{name,url}]；无则为 null */
    private String attachment;

    private String status;

    private String approver;

    private String decisionNote;

    private LocalDateTime decidedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
