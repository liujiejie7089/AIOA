package cn.aioa.security;

import cn.aioa.common.resp.ApiResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.stream.Collectors;

/**
 * 服务令牌校验：仅作用于 /internal/**，claim svc 必须为 agent 或 server。
 * 注意：不声明为 Spring Bean，避免被 Spring Boot 重复注册到 Servlet 容器。
 */
@RequiredArgsConstructor
public class ServiceTokenFilter extends OncePerRequestFilter {

    private static final String PREFIX = "/internal/";

    private final ServiceTokenProvider serviceTokenProvider;
    private final ObjectMapper objectMapper;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith(PREFIX);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (!StringUtils.hasText(header) || !header.startsWith("Bearer ")) {
            writeUnauthorized(response, "缺少服务令牌");
            return;
        }
        String svc;
        try {
            svc = serviceTokenProvider.parseValid(header.substring(7));
        } catch (Exception e) {
            writeUnauthorized(response, "服务令牌无效");
            return;
        }
        Collection<? extends GrantedAuthority> authorities = serviceTokenProvider.authoritiesFor(svc).stream()
                .map(SimpleGrantedAuthority::new)
                .collect(Collectors.toList());
        UsernamePasswordAuthenticationToken auth =
                new UsernamePasswordAuthenticationToken("svc:" + svc, null, authorities);
        SecurityContextHolder.getContext().setAuthentication(auth);
        try {
            chain.doFilter(request, response);
        } finally {
            SecurityContextHolder.clearContext();
        }
    }

    private void writeUnauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(), ApiResponse.fail(401, message));
    }
}
