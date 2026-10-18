package cn.aios.security;

import cn.aios.common.security.DevSecretPlaceholders;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 用户侧 JWT 配置（aios.jwt.*）。
 */
@Data
@ConfigurationProperties(prefix = "aios.jwt")
public class JwtProperties {

    /** HS256 密钥，生产环境必须覆盖（>= 32 字节）。 */
    private String secret = DevSecretPlaceholders.JWT;

    /** access token 有效期（秒），默认 2h。 */
    private long accessTtlSeconds = 7200L;

    /** refresh token 有效期（秒），默认 7d。 */
    private long refreshTtlSeconds = 604800L;
}
