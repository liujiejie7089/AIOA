package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
/**
 * 两级审计日志 —— 复用 V1 audit_log（含防篡改哈希链）
 *
 * 表：audit_log（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("audit_log")
public class OrgAuditLog {
    public static final String SCOPE_TENANT = "TENANT";
    public static final String SCOPE_ORG = "ORG";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private String scope;

    private Long userId;

    private String actorName;

    private String actorRole;

    private String action;

    private String resourceType;

    private String resourceId;

    private String detail;

    /** 变更前快照（JSON 文本）。`before` 为 MySQL 保留字，必须加反引号。 */
    @TableField("`before`")
    private String beforeJson;

    /** 变更后快照（JSON 文本）。`after` 为 MySQL 保留字，必须加反引号。 */
    @TableField("`after`")
    private String afterJson;

    private String summary;

    private String ip;

    private String ua;

    private String result;

    private String traceId;

    /** 防篡改哈希链：本条 hash = SHA256(上一条 hash + 关键字段)，prev_hash 指向上一条。 */
    private String prevHash;

    private String hash;

    /**
     * 哈希算法版本（见 V25）。V1 = 历史遗留（时间戳纳秒精度，自哈希不可复算）；
     * V2 = 当前算法（写入前截断到微秒，与 DATETIME(6) 一致，可完整复算）。
     */
    private String hashAlgo;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
