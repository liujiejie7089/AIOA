package cn.aioa.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;

/**
 * 用户侧 JWT（HS256）：access 2h / refresh 7d。
 */
@Component
public class JwtTokenProvider {

    public static final String CLAIM_UID = "uid";
    public static final String CLAIM_TENANT = "tid";
    public static final String CLAIM_ROLES = "roles";
    public static final String CLAIM_TYPE = "typ";
    public static final String TYPE_ACCESS = "access";
    public static final String TYPE_REFRESH = "refresh";

    private final JwtProperties properties;
    private final SecretKey key;

    public JwtTokenProvider(JwtProperties properties) {
        this.properties = properties;
        this.key = Keys.hmacShaKeyFor(properties.getSecret().getBytes(StandardCharsets.UTF_8));
    }

    public String generateAccessToken(AuthUser user) {
        return build(user, TYPE_ACCESS, properties.getAccessTtlSeconds());
    }

    public String generateRefreshToken(AuthUser user) {
        return build(user, TYPE_REFRESH, properties.getRefreshTtlSeconds());
    }

    public long accessTtlSeconds() {
        return properties.getAccessTtlSeconds();
    }

    private String build(AuthUser user, String type, long ttl) {
        long now = System.currentTimeMillis();
        return Jwts.builder()
                .subject(user.getUsername())
                .claim(CLAIM_UID, user.getUserId())
                .claim(CLAIM_TENANT, user.getTenantId() == null ? 0L : user.getTenantId())
                .claim(CLAIM_ROLES, user.getRoles() == null ? List.of() : user.getRoles())
                .claim(CLAIM_TYPE, type)
                .issuedAt(new Date(now))
                .expiration(new Date(now + ttl * 1000L))
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    public Claims parse(String token) {
        return Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    public AuthUser toAuthUser(Claims claims) {
        Long userId = claims.get(CLAIM_UID, Long.class);
        if (userId == null) {
            Object raw = claims.get(CLAIM_UID);
            userId = raw == null ? null : Long.valueOf(String.valueOf(raw));
        }
        Long tenantId = claims.get(CLAIM_TENANT, Long.class);
        Object rawRoles = claims.get(CLAIM_ROLES);
        List<String> roles = new ArrayList<>();
        if (rawRoles instanceof Iterable<?> iterable) {
            for (Object item : iterable) {
                roles.add(String.valueOf(item));
            }
        }
        return AuthUser.builder()
                .userId(userId)
                .tenantId(tenantId == null ? 0L : tenantId)
                .username(claims.getSubject())
                .roles(roles)
                .permissions(new ArrayList<>())
                .build();
    }

    public boolean isValid(String token) {
        if (token == null || token.isBlank()) {
            return false;
        }
        try {
            parse(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    public Map<String, Object> claimsAsMap(Claims claims) {
        return new java.util.LinkedHashMap<>(claims);
    }
}
