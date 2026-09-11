package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
/**
 * 资源按机构授权 —— 专家/技能/模型/KB（FR-E1/E2）
 *
 * 表：resource_grant（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("resource_grant")
public class ResourceGrant {
    public static final String TYPE_EXPERT = "EXPERT";
    public static final String TYPE_SKILL = "SKILL";
    public static final String TYPE_MODEL = "MODEL";
    public static final String TYPE_KB = "KB";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private String resType;

    private Long resId;

    private String resKey;

    private String resName;

    private String extra;

    private Boolean enabled;

    private Long grantedBy;

    private LocalDateTime grantedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    // 注意：resource_grant 表**无** created_by 列（授权人由 granted_by 承载），此处不得映射，否则查询报 Unknown column。

    @TableLogic
    private LocalDateTime deletedAt;
}
