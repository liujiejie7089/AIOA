package cn.aios.security;

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
 * 服务间令牌（Java ⇄ Python agent / mcp-hub）：claim svc = agent | server | hub。
 *
 * <p><b>为什么要有 hub</b>（2026-10-30）：mcp-hub 在企微 OAuth 回调那一步手里没有用户 token
 * （那是浏览器 302，只有 code/state），却必须把「某用户已完成授权」写回 Java ——
 * 因为 manifest 闸门读的是 Java 的 {@code connector_connection}。它只能用服务身份调
 * {@code /internal/v1/connectors/**}。此前只有 agent/server 两个取值，hub 无从证明自己，
 * 于是连接态被留在 hub 自己的 SQLite 里，AI 那边看不到工具（docs/63 §9.2）。</p>
 *
 * <p>M1 使用 HS256，M2 起替换为 RS256。</p>
 */
@Component
public class ServiceTokenProvider {

    public static final String CLAIM_SVC = "svc";
    public static final String SVC_AGENT = "agent";
    public static final String SVC_SERVER = "server";
    /** MCP 网关：把连接器授权结果回写平台（唯一入口见 InternalConnectorController）。 */
    public static final String SVC_HUB = "hub";
    public static final Set<String> ALLOWED_SVC = Set.of(SVC_AGENT, SVC_SERVER, SVC_HUB);
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
