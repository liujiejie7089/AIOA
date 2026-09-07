package cn.aioa.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;
import java.util.Set;

/**
 * 服务间令牌（Java ⇄ Python agent）：claim svc = agent | server。
 * M1 使用 HS256，M2 起替换为 RS256。
 */
@Component
public class ServiceTokenProvider {

    public static final String CLAIM_SVC = "svc";
    public static final String SVC_AGENT = "agent";
    public static final String SVC_SERVER = "server";
    public static final Set<String> ALLOWED_SVC = Set.of(SVC_AGENT, SVC_SERVER);
    public static final String AUTHORITY_SERVICE = "SERVICE";

    private final ServiceJwtProperties properties;
    private final SecretKey key;

    public ServiceTokenProvider(ServiceJwtProperties properties) {
        this.properties = properties;
        this.key = Keys.hmacShaKeyFor(properties.getSecret().getBytes(StandardCharsets.UTF_8));
    }

    public String generate(String svc) {
        long now = System.currentTimeMillis();
        return Jwts.builder()
                .subject(svc)
                .claim(CLAIM_SVC, svc)
                .issuedAt(new Date(now))
                .expiration(new Date(now + properties.getTtlSeconds() * 1000L))
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    /**
     * 解析并校验服务令牌，返回 svc 名称；非法抛异常。
     */
    public String parseValid(String token) {
        Claims claims = Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
        String svc = claims.get(CLAIM_SVC, String.class);
        if (svc == null || !ALLOWED_SVC.contains(svc)) {
            throw new IllegalArgumentException("invalid svc claim: " + svc);
        }
        return svc;
    }

    public List<String> authoritiesFor(String svc) {
        return List.of(AUTHORITY_SERVICE, "SVC_" + svc.toUpperCase(java.util.Locale.ROOT));
    }
}
