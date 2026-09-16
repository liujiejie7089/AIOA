package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 细粒度权限授权单（V36 需求①：权限申请与审批）。
 *
 * <p>一张单据贯穿「申请 → 本地存档 → 部门审批 → 租户管理员发放 → 生效」全链路：</p>
 * <pre>
 *   PENDING ──通过──> ACTIVE ──回收──> REVOKED
 *      └────驳回────> REJECTED
 * </pre>
 *
 * <p><b>为什么状态是单表而不是看 approval_order</b>：授权是「业务事实」，
 * 审批单是「流程载体」。流程单据可能被归档 / 清理，而授权必须长期可查
 * （谁在什么时候被授予了什么，是审计要求）。故终态通过回调写回本表。</p>
 *
 * <p><b>为什么 {@code ACTIVE} 不能直接改库</b>：授权是敏感操作，
 * 只能由 {@code ApprovalCallback} 在终审通过时写入 —— 否则「必须过审」就是一句空话。</p>
 *
 * <p>{@code institutionId} 承载需求①的「数据存档至所在单位」：申请的授权单落在申请人所属机构，
 * 机构管理员可按本单位维度查阅本单位的权限申请情况。</p>
 */
@Data
@TableName("permission_grant")
public class PermissionGrant {

    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_ACTIVE = "ACTIVE";
    public static final String STATUS_REJECTED = "REJECTED";
    public static final String STATUS_REVOKED = "REVOKED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 存档单位（org_institution.id；0 = 未归属机构）。 */
    private Long institutionId;

    /** 申请时所属部门（审批链路锚点）。 */
    private Long departmentId;

    /** 被授权人。 */
    private Long userId;

    /** 申请人姓名快照（用户改名不影响历史单据）。 */
    private String applicantName;

    /**
     * 申请主体：{@code USER}（个人，默认）或 {@code DEPARTMENT}（部门）。
     *
     * <p>V43 新增，DB 默认 {@code 'USER'}。二期 E-08 要求「部门申请」与「个人申请」在库层
     * 可区分 —— 否则当提交人即部门负责人、且申请的是本人所属部门时，两者的
     * {@code user_id}/{@code department_id} 完全相同，无法分账判重。</p>
     */
    private String applicantType;

    /** 权限码（PermissionCatalog 中的常量）。 */
    private String permissionCode;

    /** 目的数字员工类型（展示用，如 LEAVE_APPROVER）。 */
    private String targetWorkerType;

    private String reason;

    private String status;

    /** 关联的多级审批单。 */
    private Long orderId;

    /** 审批意见快照（驳回必填）。 */
    private String auditNote;

    /**
     * 终态<b>处理人</b>：通过 = 发放人（终审）；
     * 驳回 = 驳回人（该次驳回节点上的审批人）。
     *
     * <p>需求④要求审核记录能回答「谁在什么时候处理的」，驳回同样是一次处理，
     * 因此这里不区分「发放」与「驳回」—— 语义统一为「终态处理人」，
     * 具体是发放还是驳回由 {@link #status} 决定。</p>
     */
    private Long grantedBy;

    /** 终态处理时间（通过 = 发放时间；驳回 = 驳回时间）。 */
    private LocalDateTime grantedAt;

    /** 到期时间（空 = 永久有效）。 */
    private LocalDateTime expireAt;

    private LocalDateTime revokedAt;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    /** 非 @TableLogic，查询必须自行过滤。 */
    private LocalDateTime deletedAt;

    /** 是否处于「可用」状态（已生效、未回收、未过期）。 */
    public boolean usable() {
        if (!STATUS_ACTIVE.equals(status)) {
            return false;
        }
        return expireAt == null || expireAt.isAfter(LocalDateTime.now());
    }

    /** 是否占用「同一权限只能有一条在途/生效单据」的名额。 */
    public boolean occupying() {
        return STATUS_PENDING.equals(status) || usable();
    }
}
