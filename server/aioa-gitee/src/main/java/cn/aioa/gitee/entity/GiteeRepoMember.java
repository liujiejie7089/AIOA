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
 * Gitee 仓库成员与权限同步状态。
 *
 * <p>表 {@code gitee_repo_member}（V48）。</p>
 *
 * <p><b>为什么用 giteeUsername 而不是 userId 做唯一键</b>：仓库协作者接口认的是
 * Gitee 登录名；而且**可能有人在 Gitee 网页上被直接加为协作者**，此时平台还没有
 * 对应绑定（{@code userId} 为空）。若按 userId 建唯一键，这类「外部加入」根本存不下来，
 * 定时校准也就无法把它呈现给管理员。</p>
 *
 * <p>{@code source} 区分来源：{@code PLATFORM}（平台同步）/ {@code GITEE}（校准发现的外部变更）。</p>
 */
@Data
@TableName("gitee_repo_member")
public class GiteeRepoMember {

    public static final String ROLE_READ = "READ";
    public static final String ROLE_WRITE = "WRITE";
    public static final String ROLE_ADMIN = "ADMIN";

    public static final String SOURCE_PLATFORM = "PLATFORM";
    public static final String SOURCE_GITEE = "GITEE";

    public static final String SYNC_SYNCED = "SYNCED";
    public static final String SYNC_PENDING = "PENDING";
    public static final String SYNC_FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** 平台用户 id；Gitee 侧直接加入且未绑定时为空。 */
    private Long userId;

    private Long giteeUid;

    /** Gitee 登录名（协作者接口的键）。 */
    private String giteeUsername;

    /** READ / WRITE / ADMIN。 */
    private String role;

    /** PLATFORM / GITEE。 */
    private String source;

    /** SYNCED / PENDING / FAILED。 */
    private String syncStatus;

    /**
     * 最近一次权限同步的失败原因（**直接渲染给用户**：成员表 FAILED 态的悬浮说明）。
     *
     * <p>{@code updateStrategy = ALWAYS} 与 {@code GiteeProject.errorMsg} 同因：
     * 默认 {@code NOT_NULL} 会把 null 字段排除在 SET 之外，「同步成功 → 清空失败原因」
     * 与「重新绑定后清空」这两处清理都会静默失效，旧原因会一直挂在行上。</p>
     */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String lastError;

    private LocalDateTime syncedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
