package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 仓库联动<b>平台级</b>参数（管理端「系统配置 → 仓库配置」动态配置，表 {@code gitee_platform_config}，V77）。
 *
 * <p><b>与 {@link GiteeTenantConfig} 的分工</b>：本表是<b>平台一份</b>（按 provider 单行），
 * 装的是「全平台共用一套」的东西——OAuth 应用凭据、Webhook 公网基址、授权跳转域、scope、
 * 平台默认组织；租户表装的是「每个企业各自一份」的企业令牌与组织。判定顺序是
 * <b>租户行优先、本表次之、环境变量兜底</b>（组织一项见 {@code GiteeTenantConfigService}）。</p>
 *
 * <p><b>★ 覆盖语义（与前端的契约，逐字段）</b>：某列为 <b>NULL</b> ⇒ 该字段回落环境变量；
 * 某列<b>非 NULL</b> ⇒ 该字段以本表为准，<b>空串也是有效值</b>（表示「管理端显式清空」）。
 * 刻意逐字段而非整体覆盖：整体覆盖会让「首次保存时没填的密钥把环境变量的值静默遮蔽」——
 * 用户看不见这次丢失，只会在某天突然发现授权失败。</p>
 *
 * <p>刻意不纳入本表的参数（{@code token-enc-key} / {@code base-url} / {@code web-base-url} /
 * {@code webhook-secret} / 调优项）及其理由，见 {@code V77__gitee_platform_config.sql} 头部注释。</p>
 *
 * <p>审计字段 {@code createdAt}/{@code updatedAt} 由 {@code AuditMetaObjectHandler} 自动填充
 * （见 MybatisPlusConfig）；{@code updatedBy} 由业务层写入。本表<b>没有软删列</b>：
 * 「恢复为环境变量」= 删除该行。</p>
 */
@Data
@TableName("gitee_platform_config")
public class GiteePlatformConfig {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 托管方标识：gitee / gitea（与 {@code aioa.repo.provider} 同口径，小写）。 */
    private String provider;

    /** 平台总开关。 */
    private Boolean enabled;

    /** OAuth 应用 Client ID。 */
    private String clientId;

    /** OAuth 应用 Client Secret（AES-GCM 密文，{@code enc:} 前缀；与令牌同规格）。 */
    private String clientSecret;

    /** OAuth 回调地址（须与第三方应用登记页逐字符一致）。 */
    private String redirectUri;

    /** 用户浏览器授权页基址。 */
    private String oauthAuthorizeBaseUrl;

    /** 授权 scope（必须同时含 projects 与 hook）。 */
    private String scope;

    /** 平台默认组织 login（租户未自配时的回落值）。 */
    private String org;

    /** Webhook 回调公网基址（须为托管方可达地址）。 */
    private String webhookBaseUrl;

    /** 授权完成后的前端回跳地址。 */
    private String bindReturnUrl;

    private Long updatedBy;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
