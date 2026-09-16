package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 职务字典（对标开源 OA O2OA 的 <b>Duty</b>）—— 租户级，可多人同职务。
 *
 * <p><b>它解决的问题</b>：O2OA 把「人」与「规则（流程 / 权限）」之间的解耦交给职务这一层 ——
 * 流程按「职务 + 所属组织」动态求值处理人，于是人员调整只需改职务的人员映射，
 * <b>流程定义无需改动</b>。本系统此前用 {@code org_member.job_title} 这个自由文本顶替，
 * 引擎根本不读它，导致「谁是部门负责人」在业务 / 引擎 / 权限三处各说各话
 * （27 人 / 8 个部门 / 3 人，见 docs/23）。</p>
 *
 * <p><b>派生的两个解析类型</b>（见 {@code ApprovalFlowService}）：</p>
 * <ul>
 *   <li>{@code DEPT_DUTY}：申请人<b>所在部门</b>的某职务（如部门正职）—— 同一流程模板
 *       自动适配全公司各部门，无需为每个部门单独配流程；</li>
 *   <li>{@code UNIT_DUTY}：<b>指定组织</b>的某职务（O2OA 的「职务 + 组织参数」）。</li>
 * </ul>
 *
 * <p>表：{@code org_duty}（V41 迁移）。注：{@code alive} 为生成列，**不映射**。</p>
 */
@Data
@TableName("org_duty")
public class OrgDuty {

    public static final String STATUS_ACTIVE = "ACTIVE";

    /** 部门正职（部门负责人）—— 审批链「部门负责人」一级的权威口径。 */
    public static final String DEPT_PRINCIPAL = "DEPT_PRINCIPAL";
    /** 部门副职。 */
    public static final String DEPT_DEPUTY = "DEPT_DEPUTY";
    /** 机构负责人。 */
    public static final String ORG_LEADER = "ORG_LEADER";
    /** 普通成员（不可作为审批人）。 */
    public static final String STAFF = "STAFF";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 职务码：DEPT_PRINCIPAL / DEPT_DEPUTY / ORG_LEADER / STAFF。 */
    private String code;

    /** 职务名（中文展示）。 */
    private String name;

    /** 同部门多人持同一职务时的排序：越小越优先（正职 1 < 副职 2）。 */
    private Integer dutyRank;

    /** 该职务是否可作为审批人。 */
    private Boolean canApprove;

    /** 职务作用的组织层级：ORG / DEPT。 */
    private String scope;

    private String status;

    private String remark;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;

    public static String nameOf(String code) {
        if (code == null) {
            return null;
        }
        return switch (code) {
            case DEPT_PRINCIPAL -> "部门正职";
            case DEPT_DEPUTY -> "部门副职";
            case ORG_LEADER -> "机构负责人";
            case STAFF -> "普通成员";
            default -> code;
        };
    }
}
