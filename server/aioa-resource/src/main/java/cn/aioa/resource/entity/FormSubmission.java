package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 表单填写数据（docs/52 P4，唯一真源）。
 *
 * <p>审批单的 {@code form_data} 只存「引用 + 提交时快照」，不重复造业务表。
 * 状态机：DRAFT → SUBMITTED →（APPROVING → APPROVED/REJECTED）| DONE | CANCELED。</p>
 */
@Data
@TableName("form_submission")
public class FormSubmission {

    /** 草稿（未提交）。 */
    public static final String STATUS_DRAFT = "DRAFT";
    /** 已提交（待分流）。 */
    public static final String STATUS_SUBMITTED = "SUBMITTED";
    /** 审批中（APPROVAL 分流后）。 */
    public static final String STATUS_APPROVING = "APPROVING";
    /** 审批通过。 */
    public static final String STATUS_APPROVED = "APPROVED";
    /** 审批驳回（终态失败回写）。 */
    public static final String STATUS_REJECTED = "REJECTED";
    /** 已完成（LEDGER 分流或审批通过后）。 */
    public static final String STATUS_DONE = "DONE";
    /** 已取消。 */
    public static final String STATUS_CANCELED = "CANCELED";
    /** 终态失败（如 APPROVAL 调用异常）。 */
    public static final String STATUS_FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** form_template.id。 */
    private Long templateId;

    /** 提交时使用的版本号（口径追溯）。 */
    private Integer templateVersion;

    /** 表单码（冗余，便于按码查询）。 */
    private String code;

    /** 审批 bizType（走审批时）。 */
    private String bizType;

    /** 业务对象 id（审批单/业务表）。 */
    private Long bizId;

    /** 提交人。 */
    private Long applicantId;

    /** 填写数据（唯一真源，原样存 JSON）。 */
    private String dataJson;

    private String status;

    /** 审批单 id（APPROVAL 分流后回写）。 */
    private Long approvalOrderId;

    /** 来源会话（对话内提交）。 */
    private Long conversationId;

    /** 来源 run（对话内提交）。 */
    private String runId;

    private LocalDateTime submittedAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
