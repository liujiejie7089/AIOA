package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 机构作用域系统参数覆盖值（V80，docs/44 §2.5 B 案）。
 *
 * <p>与 {@link SysConfig} 完全隔离：机构管理员只能为本机构覆盖值，读取按
 * 「机构覆盖值 → 租户值 → 平台默认」逐级 merge，删除覆盖值即恢复继承。</p>
 *
 * <p>唯一键 {@code (tenant_id, institution_id, config_key)} 是 upsert 幂等的依据；
 * {@code tenant_id} / {@code institution_id} 一律取登录态，不接受前端入参（防改包提权）。</p>
 */
@Data
@TableName("sys_org_config")
public class SysOrgConfig {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 租户 ID（一律取登录态，不接受前端入参） */
    private Long tenantId;

    /** 机构 ID（机构管理员被钉死为本机构；平台/租户管理员须属本租户） */
    private Long institutionId;

    /** 参数键（与该租户 sys_config 的键集同源） */
    private String configKey;

    /** 参数名称（中文，复制自 sys_config，便于本表自描述） */
    private String configName;

    /** CONVERSATION / QUOTA / KNOWLEDGE / SECURITY / COMMON / AUDIT */
    private String groupCode;

    /** INT / DECIMAL / BOOL / STRING / JSON */
    private String valueType;

    /** 机构覆盖值（统一以字符串存储） */
    private String configValue;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
