package cn.aioa.security;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 服务间调用 JWT 配置（aioa.service-jwt.*）。
 */
@Data
@ConfigurationProperties(prefix = "aioa.service-jwt")
public class ServiceJwtProperties {

    /** HS256 密钥（M2 起替换为 RS256）。 */
    private String secret = "aioa-dev-service-jwt-secret-please-change";

    /** 服务令牌有效期（秒），默认 5 分钟。 */
    private long ttlSeconds = 300L;
}
