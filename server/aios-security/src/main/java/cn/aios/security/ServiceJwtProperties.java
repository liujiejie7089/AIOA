package cn.aios.security;

import cn.aios.common.security.DevSecretPlaceholders;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 服务间调用 JWT 配置（aios.service-jwt.*）。
 */
@Data
@ConfigurationProperties(prefix = "aios.service-jwt")
public class ServiceJwtProperties {

    /** HS256 密钥（M2 起替换为 RS256）。 */
    private String secret = DevSecretPlaceholders.SERVICE_JWT;

    /** 服务令牌有效期（秒），默认 5 分钟。 */
    private long ttlSeconds = 300L;
}
