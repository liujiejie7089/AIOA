package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
/**
 * 机构员工成员关系 —— 个人与机构/部门的归属（FR-G2）
 *
 * 表：org_member（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("org_member")
public class OrgMember {
    public static final String STATUS_ACTIVE = "ACTIVE";
    public static final String STATUS_DISABLED = "DISABLED";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private Long departmentId;

    private Long userId;

    private String name;

    private String mobile;

    private String email;

    private String employeeNo;

    /** 展示文案职务（自由文本，如「算法部负责人」）。 */
    private String jobTitle;

    /**
     * 机器可读职务码（对应 {@code org_duty.code}）—— 对标 O2OA 的 Duty。
     *
     * <p>与 {@link #jobTitle} <b>并存</b>：本字段是引擎与权限求值的唯一口径，
     * jobTitle 仅作展示。此前二者混用，导致「谁是部门负责人」有三套互不一致的口径
     * （job_title 27 人 / leader_user_id 8 个部门 / ROLE_DEPT_LEADER 3 人）。</p>
     */
    private String dutyCode;

    /**
     * 主身份标记（对标 O2OA 的 Identity）。
     *
     * <p>本表一行 = 「人 × 机构」的关系行，因此一人可在多机构各持一个身份（兼职 / 借调）；
     * 其中唯一的那个主身份 isPrimary=1，跨机构求值（如「他到底属于谁」）以它为准。</p>
     */
    private Boolean isPrimary;

    private Boolean isOrgAdmin;

    private String status;

    private LocalDate joinedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
