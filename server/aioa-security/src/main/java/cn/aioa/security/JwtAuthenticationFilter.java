package cn.aioa.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * 用户侧 Bearer JWT 认证（/api/**）。
 * 注意：不声明为 Spring Bean，避免被 Spring Boot 重复注册到 Servlet 容器（会污染 SecurityContextHolder）。
 */
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtTokenProvider tokenProvider;
    /** 可选：实时角色解析（角色变更即时生效）；为 null 时退回 JWT 内快照角色。 */
    private final RoleResolver roleResolver;

    public JwtAuthenticationFilter(JwtTokenProvider tokenProvider) {
        this(tokenProvider, null);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith("/api/");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (StringUtils.hasText(header) && header.startsWith("Bearer ")) {
            String token = header.substring(7);
            try {
                Claims claims = tokenProvider.parse(token);
                String type = claims.get(JwtTokenProvider.CLAIM_TYPE, String.class);
                if (JwtTokenProvider.TYPE_ACCESS.equals(type)) {
                    AuthUser user = tokenProvider.toAuthUser(claims);
                    // 角色即时生效：优先取数据库实时角色，异常时退回 JWT 快照
                    if (roleResolver != null && user.getUserId() != null) {
                        try {
                            List<String> live = roleResolver.rolesOf(user.getUserId());
                            if (live == null) {
                                // 用户不存在/已停用：拒绝本次认证
                                SecurityContextHolder.clearContext();
                                chain.doFilter(request, response);
                                return;
                            }
                            user.setRoles(live);
                        } catch (Exception ignore) {
                            // 角色解析失败不影响认证（保持 JWT 快照角色）
                        }
                    }
                    List<GrantedAuthority> authorities = new ArrayList<>();
                    for (String role : user.getRoles()) {
                        authorities.add(new SimpleGrantedAuthority(role));
                    }
                    UsernamePasswordAuthenticationToken auth =
                            new UsernamePasswordAuthenticationToken(user, null, authorities);
                    auth.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
                    SecurityContextHolder.getContext().setAuthentication(auth);
                    AuthUserContext.set(user);
                }
            } catch (JwtException | IllegalArgumentException e) {
                SecurityContextHolder.clearContext();
            }
        }
        try {
            chain.doFilter(request, response);
        } finally {
            AuthUserContext.clear();
        }
    }
}
