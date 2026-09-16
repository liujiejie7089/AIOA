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
    /**
     * 知会（抄送）节点的状态 —— 对标 O2OA 的「待阅」。
     *
     * <p>不是 PENDING，故<b>不阻塞</b>流转：{@code isCurrentNode} 只看 PENDING，
     * 「待我处理」也只查 PENDING，知会条目只出现在「抄送我的」并按通知提醒。</p>
     */
    public static final String STATUS_CC = "CC";

    /** 节点角色：审批（阻塞推进）。 */
    public static final String ROLE_APPROVE = "APPROVE";
    /**
     * 节点角色：知会 / 抄送（**不阻塞**推进）。
     *
     * <p>一级审批把成员申请止于部门负责人后，机构管理员不再出现在链上。
     * 按 O2OA 的做法把「要审批」与「要知晓」拆开：审批要快，知情要全。</p>
     */
    public static final String ROLE_CC = "CC";

    /** 审批节点类型 */
    public static final String TYPE_DEPT_LEADER = "DEPT_LEADER";
    public static final String TYPE_ORG_ADMIN = "ORG_ADMIN";
    public static final String TYPE_TENANT_ADMIN = "TENANT_ADMIN";
    public static final String TYPE_SPECIFIC = "SPECIFIC";
    /**
     * 平台管理员（终极上级）。
     *
     * <p>租户管理员之上再无本租户的上级，其申请只能由平台侧终审；
     * 若缺这一级，租户管理员发起的申请会「无上级可指派」而被拒。</p>
     */
    public static final String TYPE_PLATFORM_ADMIN = "PLATFORM_ADMIN";
    /**
     * 「申请人的上一级」—— 一个 step 展开为<b>整条上级链</b>。
     *
     * <p>与其它类型（固定指向某一类角色）不同，本类型按<b>申请人自身的组织层级</b>递推：
     * 部门负责人 → 机构管理员 → 租户管理员 → 平台管理员，并从「申请人的上一级」起算，
     * 且跳过「审批人 == 申请人」的节点（自审防护）。</p>
     */
    public static final String TYPE_APPLICANT_SUPERIOR = "APPLICANT_SUPERIOR";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private Long orderId;

    private Integer seq;

    private String approverType;

    private Long approverId;

    private String approverName;

    /**
     * 节点角色：{@link #ROLE_APPROVE}（默认）或 {@link #ROLE_CC}。
     *
     * <p>知会节点不参与流转，只用于「抄送我的」。默认值 APPROVE 使历史行与改造前等价。</p>
     */
    private String taskRole;

    /**
     * 知会（抄送）已读时间 —— 三期 C-03。
     *
     * <p>{@code NULL} = 未读；仅 {@code task_role='CC'} 行有意义，{@code APPROVE} 行恒 {@code NULL}。
     * 旧 CC 行迁移后天然为 {@code NULL}（未读），与一期前端「未读知会」表现一致。</p>
     */
    private LocalDateTime ccReadAt;

    private String status;

    private String note;

    private String skipReason;

    private LocalDateTime decidedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
