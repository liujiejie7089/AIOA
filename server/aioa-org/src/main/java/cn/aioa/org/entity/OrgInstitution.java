package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
/**
 * 机构（企业）—— 租户内具有法人资格的组织实体（FR-B）
 *
 * 表：org_institution（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("org_institution")
public class OrgInstitution {
    public static final String STATUS_ACTIVE = "ACTIVE";
    public static final String STATUS_SUSPENDED = "SUSPENDED";
    public static final String STATUS_CLOSED = "CLOSED";
    /** 主营类型 */
    public static final String TYPE_GOVERNMENT = "GOVERNMENT";
    public static final String TYPE_ENTERPRISE = "ENTERPRISE";
    public static final String TYPE_ASSOCIATION = "ASSOCIATION";
    /** 入驻第 8 步完成即闭环 */
    public static final int ONBOARD_DONE = 8;


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String name;

    private String code;

    private String orgType;

    private String creditCode;

    private String legalPerson;

    private String contactMobile;

    private String contactEmail;

    private Long adminUserId;

    private String adminName;

    private String status;

    private LocalDate establishedAt;

    private Integer onboardStep;

    private String remark;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
