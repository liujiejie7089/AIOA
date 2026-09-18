package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 平台项目 ↔ Gitee 仓库映射。
 *
 * <p>表 {@code gitee_project}（V48）。</p>
 *
 * <p><b>状态机</b>：{@code CREATING} →（建仓 + 配 Webhook 均成功）→ {@code ACTIVE}；
 * 任一步失败 → {@code FAILED}（{@code error_msg} 记原因，可重试）；
 * 软删后置 {@code DELETED}。前端据此显示「创建中 / 已就绪 / 创建失败」，
 * 而不是把「建仓还没跑完」当成「空项目」。</p>
 *
 * <p><b>为什么 webhook_secret 是明文</b>：它是回调校验的共享密钥，平台必须能原样比对
 * （Gitee 用明文 {@code X-Gitee-Token} 头，非 HMAC）。但同样**不得下发前端**。</p>
 */
@Data
@TableName("gitee_project")
public class GiteeProject {

    public static final String STATUS_CREATING = "CREATING";
    public static final String STATUS_ACTIVE = "ACTIVE";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_DELETED = "DELETED";

    public static final String VISIBILITY_PRIVATE = "private";
    public static final String VISIBILITY_PUBLIC = "public";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 归属部门（单一归属；跨部门协作需显式加成员）。 */
    private Long departmentId;

    /** 关联 gitee_team.id。 */
    private Long teamId;

    /** 项目名（展示用）。 */
    private String name;

    /** Gitee 仓库名（含部门命名前缀）。 */
    private String repoName;

    private String description;

    /** private / public。 */
    private String visibility;

    /** 仓库 owner（总组织 login 或用户 login）。 */
    private String giteeOwner;

    /** Gitee 仓库 path（API 路径段）。 */
    private String giteeRepo;

    private Long giteeRepoId;

    private String giteeHtmlUrl;

    private String giteeSshUrl;

    private String giteeHttpsUrl;

    private String defaultBranch;

    private Long webhookId;

    /** Webhook 校验密钥（明文存，但不下发前端）。 */
    private String webhookSecret;

    /** 已订阅事件，逗号分隔。 */
    private String webhookEvents;

    /** CREATING / ACTIVE / FAILED / DELETED。 */
    private String status;

    /**
     * 建仓失败原因（**直接渲染给用户**：项目详情页红色告警标题）。
     *
     * <p>{@code updateStrategy = ALWAYS} 不是可选项：MyBatis-Plus 默认策略是
     * {@code NOT_NULL}，会把值为 null 的字段整段排除在 SET 之外 —— 于是
     * 「建仓成功 → {@code setErrorMsg(null)}」这句代码**看起来执行成功、实际一个字节都没写**，
     * 失败原因会永久留在行上（真机实测：17 个已经 ACTIVE 的项目仍挂着
     * {@code Rate Limit Exceeded}）。显式声明 ALWAYS 让「清空」真的落库。</p>
     */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String errorMsg;

    /** 软删项目时是否同时删除 Gitee 仓库（默认否：误删代码不可逆）。 */
    private Boolean purgeRepo;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
