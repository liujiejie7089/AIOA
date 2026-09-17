package cn.aioa.gitee.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.gitee.service.GiteeAccountService;
import cn.aioa.org.support.OrgGuard;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * Gitee 账号绑定（OAuth2 授权码模式）。
 *
 * <p><b>回调为什么必须公开</b>：授权是**用户在 Gitee 站点上完成**后由 Gitee 服务端
 * 重定向回来的，这一跳不可能带平台的 JWT。身份只能靠发起时写入的 {@code state}
 * 反查（见 {@code GiteeAccountService.bindUrl}），因此 state 必须不可猜、一次性、有期限。</p>
 *
 * <p><b>回调为什么返回 HTML 而不是 JSON</b>：这是浏览器地址栏跳转，用户需要看到
 * 「绑定成功，正在返回」而不是一坨 JSON。页面本身不携带任何敏感信息 ——
 * 令牌留在服务端，回跳只带一个结果标记。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/gitee/bind")
@RequiredArgsConstructor
public class GiteeOauthController {

    private final OrgGuard guard;
    private final GiteeAccountService accountService;
    private final GiteeProperties props;

    /** 我的绑定状态。 */
    @GetMapping
    public ApiResponse<Map<String, Object>> myBinding() {
        return ApiResponse.ok(accountService.myBinding(guard.requireOrgUser()));
    }

    /** 生成授权跳转地址（前端拿到 url 后整页跳转）。 */
    @PostMapping("/authorize")
    public ApiResponse<Map<String, Object>> authorize() {
        return ApiResponse.ok(accountService.bindUrl(guard.requireOrgUser()));
    }

    /** 解绑（删除本地令牌）。 */
    @DeleteMapping
    public ApiResponse<Map<String, Object>> unbind() {
        accountService.unbind(guard.requireOrgUser());
        return ApiResponse.ok(Map.of("bound", false));
    }

    /**
     * Gitee 授权回调（**公开端点**）。
     *
     * <p>成功与失败都返回可读 HTML：失败时给出具体原因与「返回平台」链接，
     * 而不是让用户看到裸 400 页面。</p>
     */
    @GetMapping(value = "/callback", produces = MediaType.TEXT_HTML_VALUE)
    public String callback(@RequestParam(required = false) String code,
                           @RequestParam(required = false) String state,
                           @RequestParam(required = false) String error,
                           @RequestParam(name = "error_description", required = false) String errorDescription,
                           HttpServletResponse response) {
        if (error != null && !error.isBlank()) {
            return failPage(response, "Gitee 拒绝了本次授权", error, errorDescription);
        }
        try {
            Map<String, Object> r = accountService.callback(code, state);
            return okPage(response, String.valueOf(r.get("giteeUsername")));
        } catch (Exception e) {
            log.warn("Gitee 绑定回调失败：{}", e.getMessage());
            return failPage(response, "绑定失败", e.getClass().getSimpleName(), e.getMessage());
        }
    }

    // ======================================================================
    // 结果页
    // ======================================================================

    private String okPage(HttpServletResponse response, String giteeUsername) {
        String back = props.getBindReturnUrl();
        StringBuilder sb = new StringBuilder();
        sb.append("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
                .append("<title>Gitee 绑定成功</title></head><body style=\"font-family:system-ui;padding:40px\">")
                .append("<h2>Gitee 绑定成功</h2>")
                .append("<p>已绑定账号：<b>").append(esc(giteeUsername)).append("</b></p>");
        // fail-loud：授权域非 gitee.com 时，这一页必须说清楚「未经过真实 Gitee 授权」，
        // 否则用户会把桩/代理签发的假身份当成真实绑定（截图里的迷惑点正在于此）。
        String host = nonProdAuthorizeHost();
        if (host != null) {
            sb.append("<p style=\"background:#fff7e6;border:1px solid #ffd591;border-radius:6px;")
                    .append("padding:12px;color:#874d00;max-width:640px\">")
                    .append("<b>⚠ 本次授权未经过真实 Gitee</b><br>")
                    .append("授权跳转落地在 <code>").append(esc(host)).append("</code>（非 gitee.com），")
                    .append("账号由本地桩/代理签发。如需真实 Gitee 授权，请将 ")
                    .append("<code>aioa.gitee.oauth-authorize-base-url</code>")
                    .append("（环境变量 <code>AIOA_GITEE_OAUTH_AUTHORIZE_URL</code>）")
                    .append("配置为 <code>https://gitee.com</code> 后重新发起绑定。</p>");
        }
        if (back != null && !back.isBlank()) {
            sb.append("<p>正在返回平台…</p>")
                    .append("<script>setTimeout(function(){location.replace(")
                    .append(jsStr(back)).append(");},400)</script>")
                    .append("<p><a href=\"").append(esc(back)).append("\">若未自动跳转，请点击这里</a></p>");
        } else {
            sb.append("<p>可以关闭本页并返回平台。</p>");
        }
        sb.append("</body></html>");
        return sb.toString();
    }

    private String failPage(HttpServletResponse response, String title, String code, String desc) {
        // 业务失败不是 HTTP 错误：用 200 + 可读页面，避免浏览器把用户甩到通用错误页
        response.setStatus(HttpServletResponse.SC_OK);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        String back = props.getBindReturnUrl();
        StringBuilder sb = new StringBuilder();
        sb.append("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
                .append("<title>Gitee 绑定失败</title></head><body style=\"font-family:system-ui;padding:40px\">")
                .append("<h2>").append(esc(title)).append("</h2>")
                .append("<p>原因：").append(esc(desc == null ? code : desc)).append("</p>");
        if (back != null && !back.isBlank()) {
            sb.append("<p><a href=\"").append(esc(back)).append("\">返回平台重新发起绑定</a></p>");
        } else {
            sb.append("<p>请返回平台重新发起绑定。</p>");
        }
        sb.append("</body></html>");
        return sb.toString();
    }

    /**
     * 授权域若不是 gitee.com，返回该域名（用于结果页的 fail-loud 提示）；
     * 是生产域或无法解析时返回 {@code null}。
     */
    private String nonProdAuthorizeHost() {
        String base = props.getOauthAuthorizeBaseUrl();
        try {
            String h = java.net.URI.create(base == null ? "" : base.trim()).getHost();
            if (h == null || h.isBlank()) {
                return null;
            }
            return ("gitee.com".equalsIgnoreCase(h) || "www.gitee.com".equalsIgnoreCase(h)) ? null : h;
        } catch (Exception e) {
            return null;
        }
    }

    /** HTML 文本转义：Gitee 登录名来自外部输入，不能直接拼进页面。 */
    static String esc(String s) {
        if (s == null) {
            return "";
        }
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;").replace("'", "&#39;");
    }

    /** 用于 JS 字符串字面量：只允许 http(s) 开头的地址，其余丢弃。 */
    static String jsStr(String url) {
        if (url == null || !(url.startsWith("http://") || url.startsWith("https://"))) {
            return "\"/\"";
        }
        return "\"" + url.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }
}
