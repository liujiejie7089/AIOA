package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
/**
 * 审批任务 —— 多级流转节点（与 approval_order 并行）
 *
 * 表：approval_task（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("approval_task")
public class ApprovalTask {
    public static final String PENDING = "PENDING";
    public static final String APPROVED = "APPROVED";
    public static final String REJECTED = "REJECTED";
    public static final String SKIPPED = "SKIPPED";
    /** 审批节点类型 */
    public static final String TYPE_DEPT_LEADER = "DEPT_LEADER";
    public static final String TYPE_ORG_ADMIN = "ORG_ADMIN";
    public static final String TYPE_TENANT_ADMIN = "TENANT_ADMIN";
    public static final String TYPE_SPECIFIC = "SPECIFIC";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private Long orderId;

    private Integer seq;

    private String approverType;

    private Long approverId;

    private String approverName;

    private String status;

    private String note;

    private String skipReason;

    private LocalDateTime decidedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
