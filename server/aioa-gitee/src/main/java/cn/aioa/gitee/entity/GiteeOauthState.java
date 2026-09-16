package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * OAuth2 授权码模式的 state（一次性，防 CSRF 与重放）。
 *
 * <p>表 {@code gitee_oauth_state}（V48）。无软删 —— state 是短命一次性凭证，过期即清。</p>
 *
 * <p><b>为什么必须有 state</b>：回调地址是**无鉴权**的浏览器跳转。若不校验 state，
 * 攻击者可以把自己的授权 code 诱导受害者浏览器访问回调，让受害者的平台账号绑到
 * 攻击者的 Gitee 账号上（绑定劫持）。state 必须与发起授权的用户一一对应且只能用一次。</p>
 */
@Data
@TableName("gitee_oauth_state")
public class GiteeOauthState {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 随机 state（UUID，一次性）。 */
    private String state;

    private Long tenantId;

    /** 发起授权的平台用户。 */
    private Long userId;

    /** 发起时的回调地址：回调必须原样匹配，防止 redirect_uri 被替换。 */
    private String redirectUri;

    /** 1 = 已被消费（防重放）。 */
    private Boolean consumed;

    private LocalDateTime expiresAt;

    private LocalDateTime createdAt;
}
