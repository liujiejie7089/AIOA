package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 专家配置与覆盖规则（FR：租户级专家配置维度）。
 *
 * <p>一条记录 = 「某个作用域 + 某个专家」的一份配置片段。解析时按
 * {@code GLOBAL < TENANT < INSTITUTION < DEPT < USER} 逐级 merge，
 * 高优先级覆盖低优先级；{@code expert_key = '*'} 为全局默认片段，
 * 对同一作用域下所有专家生效（优先级低于具体 expert_key）。</p>
 *
 * <p>config_json 以字符串存储，解析在 {@code ExpertConfigService} 内用 Jackson 完成，
 * 避免 MyBatis JSON typeHandler 与不同 MySQL 驱动的行为差异。</p>
 */
@Data
@TableName("expert_config")
public class ExpertConfig {

    /** 作用域层级：数值越大优先级越高。 */
    public static final String GLOBAL = "GLOBAL";
    public static final String TENANT = "TENANT";
    public static final String INSTITUTION = "INSTITUTION";
    public static final String DEPT = "DEPT";
    public static final String USER = "USER";

    /** 全局默认片段的专家标识。 */
    public static final String WILDCARD = "*";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String scopeType;

    private Long scopeId;

    private String expertKey;

    private String configJson;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    /**
     * 审核态（V36）：{@code PENDING} / {@code APPROVED} / {@code REJECTED}。
     *
     * <p>需求⑤「专家配置应支持租户自行配置，但必须经过审核」：租户管理员写团队层
     * （TENANT/INSTITUTION/DEPT/GLOBAL）配置时落 {@code PENDING}，需平台管理员放行；
     * {@code USER} 层只影响本人，直接 {@code APPROVED}。</p>
     *
     * <p>历史行（V27/V28 及本次迁移前）默认 {@code APPROVED}，行为不变。</p>
     */
    private String auditStatus;

    /** 审核意见（驳回必填）。 */
    private String auditNote;

    /** 审核人（平台管理员）。 */
    private Long reviewedBy;

    /** 审核时间。 */
    private LocalDateTime reviewedAt;

    /**
     * 配置片段采用「物理删除」语义（覆盖规则的删除 = 恢复继承低层级），
     * 不保留软删历史，避免唯一键 (tenant_id,scope_type,scope_id,expert_key) 被软删残留占用。
     */
    private LocalDateTime deletedAt;

    /** 审核态常量（与 {@code ContentReviewService} 同源字符串）。 */
    public static final String AUDIT_PENDING = "PENDING";
    public static final String AUDIT_APPROVED = "APPROVED";
    public static final String AUDIT_REJECTED = "REJECTED";

    /** 是否为「已生效」态：NULL 视为 APPROVED，兼容历史行。 */
    public static boolean effective(String auditStatus) {
        return auditStatus == null || auditStatus.isBlank() || AUDIT_APPROVED.equalsIgnoreCase(auditStatus);
    }
}
