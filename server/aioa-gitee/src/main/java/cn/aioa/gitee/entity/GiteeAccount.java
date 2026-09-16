package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 平台用户 ↔ Gitee 账号绑定（OAuth2 授权码模式）。
 *
 * <p>表 {@code gitee_account}（V48）。{@code alive} 为生成列，不映射。</p>
 *
 * <p><b>giteeUid 是身份映射的锚点</b>：Webhook 回传的只有 Gitee 侧信息，
 * 而 Gitee 登录名与昵称都可被用户随时修改 —— 只有数字 id 恒定。因此
 * 「这条事件是谁干的」必须以 giteeUid 反查，不能用登录名。</p>
 *
 * <p><b>令牌字段存的是密文</b>（{@link cn.aioa.gitee.support.GiteeCrypto}），
 * 且**任何对外接口都不得返回本类**，避免令牌随列表接口泄露。</p>
 */
@Data
@TableName("gitee_account")
public class GiteeAccount {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 平台用户 id（sys_user.id）。 */
    private Long userId;

    /** Gitee 数字 id —— Webhook 身份映射的锚点。 */
    private Long giteeUid;

    /** Gitee 登录名（可被用户修改，仅用于展示与协作者接口）。 */
    private String giteeUsername;

    /** Gitee 昵称。 */
    private String giteeName;

    private String avatarUrl;

    /** OAuth2 access_token（AES-GCM 密文）。 */
    private String accessToken;

    /** OAuth2 refresh_token（密文）。 */
    private String refreshToken;

    /** access_token 过期时间；为空表示不过期。 */
    private LocalDateTime tokenExpiresAt;

    /** 授权 scope。 */
    private String scope;

    private LocalDateTime boundAt;

    /** 最近一次刷新时间。 */
    private LocalDateTime refreshedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
