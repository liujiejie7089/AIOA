package cn.aios.security;

import cn.aios.common.resp.ApiResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

import java.nio.charset.StandardCharsets;

/**
 * Spring Security 配置：
 * 放行 /api/v1/auth/**、/actuator/health、/v3/api-docs/**、/swagger-ui/**；
 * /internal/** 走服务令牌；其余 /api/** 需登录态。
 */
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@EnableConfigurationProperties({JwtProperties.class, ServiceJwtProperties.class})
public class SecurityConfig {

    private static final String[] PUBLIC_ENDPOINTS = {
            "/api/v1/auth/**",
            // Gitee Webhook 由 Gitee 服务端调用，不可能带平台 JWT；
            // 其自身安全由「项目级共享密钥 X-Gitee-Token + event_key 幂等」保证
            "/api/v1/gitee/webhook/**",
            // OAuth2 回调是浏览器从 Gitee 跳回，同样无 JWT；
            // 身份由发起时下发的一次性 state 承载（防 CSRF + 防重放）
            "/api/v1/gitee/bind/callback",
            // 连接器 OAuth2 回调（企业微信）同理：浏览器从企业微信跳回，不带平台 JWT。
            // 身份由发起时写库的一次性 state 承载（10 分钟过期 + 用后即废），
            // 且 state 校验失败时绝不写任何 connection（见 WeComOAuthService#callback）。
            // ⚠️ 只放行 callback 这一个子路径，目录/详情/连接/断开仍须登录态。
            "/api/v1/connectors/*/callback",
            // 单端口部署（docs/33）下由 aios-server 自己发的两块静态前端：
            // 用户端 /aios/h5/** 与 管理端 /aios/web/**。登录页就在里面，必须匿名可读。
            // ⚠️ 这里的放行是「可读静态资源」而非「可读业务数据」：接口仍在 /api/** 之下受鉴权保护
            //    （前缀剥离发生在安全链之前，见 AiosPathPrefixFilter）。
            "/aios/h5/**",
            "/aios/web/**",
            "/aios/h5",
            "/aios/web",
            // 容器级错误派发（ERROR dispatch）：ResourceHttpRequestHandler 对不存在的静态资源
            // 走 response.sendError(404)，会再派发到 /error。若不放行，.anyRequest().authenticated()
            // 会把匿名请求的 404 改写成 401 —— 现象是「少一个 js 文件，浏览器拿到的是未授权」。
            // /error 只输出 Boot 默认错误体（默认不含异常消息与堆栈，见 application.yml 无 include-* 覆盖）。
            "/error",
            "/actuator/health",
            "/actuator/health/**",
            "/v3/api-docs/**",
            "/swagger-ui/**",
            "/swagger-ui.html"
    };

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http,
                                           JwtTokenProvider jwtTokenProvider,
                                           ServiceTokenProvider serviceTokenProvider,
                                           ObjectMapper objectMapper,
                                           AuthenticationEntryPoint authenticationEntryPoint,
                                           AccessDeniedHandler accessDeniedHandler,
                                           org.springframework.beans.factory.ObjectProvider<RoleResolver> roleResolver,
                                           org.springframework.beans.factory.ObjectProvider<PermissionResolver> permissionResolver,
                                           org.springframework.beans.factory.ObjectProvider<TokenRevocationChecker> revocationChecker) throws Exception {
        JwtAuthenticationFilter jwtFilter = new JwtAuthenticationFilter(jwtTokenProvider,
                roleResolver.getIfAvailable(), permissionResolver.getIfAvailable(),
                revocationChecker.getIfAvailable());
        ServiceTokenFilter serviceTokenFilter = new ServiceTokenFilter(serviceTokenProvider, objectMapper);

        return http
                .csrf(AbstractHttpConfigurer::disable)
                .cors(Customizer.withDefaults())
                .httpBasic(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .exceptionHandling(handler -> handler
                        .authenticationEntryPoint(authenticationEntryPoint)
                        .accessDeniedHandler(accessDeniedHandler))
                .authorizeHttpRequests(auth -> auth
                        // 只在「进来的那一次 HTTP 请求」（REQUEST 派发）上鉴权，容器内部的续跑派发
                        // （ASYNC / ERROR）不再重复鉴权。
                        //
                        // 为什么必须关：JwtAuthenticationFilter 继承 OncePerRequestFilter，默认
                        // shouldNotFilterAsyncDispatch()=true ⇒ 它不参与 ASYNC 派发；而
                        // AuthorizationFilter 默认参与。于是 SSE（/api/v1/runs/{id}/events）流结束时，
                        // 容器做的那次 ASYNC 派发没有 SecurityContext ⇒ 判 AccessDenied；但此时
                        // SSE 响应早已写出（committed）⇒ 403 写不进去，日志每次都刷三段 ERROR：
                        //   1) AccessDeniedException: Access Denied
                        //   2) Unable to handle the Spring Security Exception because the response
                        //      is already committed.
                        //   3) Cannot render error page for request [null] ...
                        // 关掉它只影响「内部派发」；首次 REQUEST 派发照常鉴权，鉴权语义不变
                        // （同一个请求先过 REQUEST 派发才可能异步，不存在绕过）。
                        .shouldFilterAllDispatcherTypes(false)
                        .requestMatchers(PUBLIC_ENDPOINTS).permitAll()
                        .requestMatchers("/internal/**").hasAuthority(ServiceTokenProvider.AUTHORITY_SERVICE)
                        .requestMatchers("/api/**").authenticated()
                        .anyRequest().authenticated())
                .addFilterBefore(serviceTokenFilter, UsernamePasswordAuthenticationFilter.class)
                .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class)
                .build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public AuthenticationEntryPoint authenticationEntryPoint(ObjectMapper objectMapper) {
        return (request, response, ex) -> writeJson(response, objectMapper, HttpStatus.UNAUTHORIZED,
                ApiResponse.fail(401, "未认证或令牌无效"));
    }

    @Bean
    public AccessDeniedHandler accessDeniedHandler(ObjectMapper objectMapper) {
        return (request, response, ex) -> writeJson(response, objectMapper, HttpStatus.FORBIDDEN,
                ApiResponse.fail(403, "无权限访问该资源"));
    }

    private static void writeJson(jakarta.servlet.http.HttpServletResponse response,
                                  ObjectMapper objectMapper,
                                  HttpStatus status,
                                  ApiResponse<?> body) throws java.io.IOException {
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(), body);
    }
}
