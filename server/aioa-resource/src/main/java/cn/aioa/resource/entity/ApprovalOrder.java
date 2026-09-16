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

    /** 申请主体：个人（默认，与历史行 / 一期接口逐字等价）。 */
    public static final String APPLICANT_USER = "USER";
    /** 申请主体：部门（二期 E-01，「以部门名义发起」）。 */
    public static final String APPLICANT_DEPARTMENT = "DEPARTMENT";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 发起人 */
    private Long userId;

    /** 发起人姓名（提交时快照，管理端审批中心展示） */
    private String applicantName;

    /**
     * 申请主体：{@link #APPLICANT_USER}（个人）或 {@link #APPLICANT_DEPARTMENT}（部门）。
     *
     * <p>V43 新增，DB 默认 {@code 'USER'} —— 历史行与一期接口读取行为不变。
     * 二期「以部门名义发起」只改主体与审批链起点，不改授权发放对象（授权仍发给提交人本人）。</p>
     */
    private String applicantType;

    /** 部门申请时的主体部门 id（仅 {@code applicantType=DEPARTMENT} 时非空）。 */
    private Long applicantDepartmentId;

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
