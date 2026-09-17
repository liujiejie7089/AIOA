package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 每租户各自的 Gitee 组织配置（覆盖全局 {@code aioa.gitee.org}）。
 *
 * <p>表 {@code gitee_tenant_config}（V50）。隔离边界为租户（tenant_id），
 * 同一租户内不同部门仍通过仓库命名前缀（dept&lt;id&gt;-）做部门隔离。</p>
 *
 * <p>这是<b>每租户单行</b>表（singleton-per-tenant）：没有软删列，
 * 清配置 = 删除该行并回落到平台全局默认 {@code aioa.gitee.org}。</p>
 *
 * <p>审计字段 {@code createdAt}/{@code updatedAt} 由 {@code AuditMetaObjectHandler}
 * 自动填充（见 MybatisPlusConfig）；{@code createdBy}/{@code updatedBy} 由业务层写入。</p>
 */
@Data
@TableName("gitee_tenant_config")
public class GiteeTenantConfig {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 所属租户（隔离边界）。 */
    private Long tenantId;

    /** 该租户各自的 Gitee 组织 login（覆盖全局默认）。 */
    private String orgName;

    /** 1 = 该租户 Gitee 仓库联动启用（覆盖平台开关）；0 = 关闭。 */
    private Boolean enabled;

    /** 备注。 */
    private String note;

    /** 企业访问令牌（AES-GCM 密文，enc: 前缀；与 gitee_account.access_token 同规格）。 */
    private String accessToken;

    /** 令牌所属 Gitee 登录名（校验时回填）。 */
    private String tokenOwner;

    /** 企业令牌授权 scope。 */
    private String tokenScope;

    /** 初始化状态：PENDING（未初始化）/ ACTIVE / FAILED。 */
    private String initStatus;

    /** 最近一次成功初始化时间。 */
    private LocalDateTime initAt;

    /** 最近一次初始化操作人（sys_user.id）。 */
    private Long initBy;

    /** 最近一次初始化/校验失败原因（供界面提示）。 */
    private String lastError;

    /** 组织可见性校验结果（1=已验证可用）。 */
    private Boolean orgVerified;

    /** 最近一次校验（含可见性探测）时间。 */
    private LocalDateTime lastCheckAt;

    private Long createdBy;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    private Long updatedBy;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
