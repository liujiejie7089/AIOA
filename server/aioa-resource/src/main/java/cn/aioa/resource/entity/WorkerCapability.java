package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 数字人能力声明（docs/52 P1/P3）：任务 → 表单 → 工具 → 审批。
 *
 * <p>语义：「这个数字人会办 {@code task_code} 这件事；办的时候用 {@code form_code} 这张表收字段；
 * 需要 {@code tool_names} 这些工具；提交后走 {@code approval_biz_type} 审批（可空=不审批）」。</p>
 */
@Data
@TableName("worker_capability")
public class WorkerCapability {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 租户；0 = 平台模板。 */
    private Long tenantId;

    /** agent_worker.id。 */
    private Long workerId;

    /** 任务稳定码，如 leave_request / expense_claim。 */
    private String taskCode;

    /** 任务中文名。 */
    private String taskName;

    /** 办理时使用的表单码。 */
    private String formCode;

    /** 办这件事需要的工具名数组（JSON）。 */
    private String toolNamesJson;

    /** 提交后走的审批 bizType；空=不审批。 */
    private String approvalBizType;

    /** 展示排序。 */
    private Integer sort;

    /** 是否启用（1=启用 0=停用）。 */
    private Integer enabled;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
