package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteeProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.ProxySelector;
import java.net.SocketAddress;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Gitee V5 OpenAPI 客户端（唯一的出网站点）。
 *
 * <p><b>设计要点</b></p>
 * <ol>
 *   <li><b>显式禁用代理</b>：本部署环境里存在 HTTP 代理环境变量，若走代理会拿到
 *       代理自身的错误页（表现为「Gitee 返回 401」这类假象）。这里用 NO_PROXY 选择器
 *       把 HttpClient 钉死为直连，排障时不必再怀疑网络中间层。</li>
 *   <li><b>全局限速</b>：Gitee 对高频请求返回 {@code 403 Rate Limit Exceeded}（已实测）。
 *       客户端内做最小请求间隔节流，把「限流」从偶发故障变成可控延迟。</li>
 *   <li><b>令牌只出现在 Authorization 头</b>，绝不放进 URL query —— query 会进访问日志、
 *       浏览器历史与 Referer，是最常见的令牌泄露途径。</li>
 * </ol>
 *
 * <p><b>已验证的端点清单见 docs/30 §2</b>（含「组织级 Team API 不可用」这一实测结论）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class GiteeClient {

    private static final ProxySelector NO_PROXY = new ProxySelector() {
        @Override
        public List<Proxy> select(URI uri) {
            return List.of(Proxy.NO_PROXY);
        }

        @Override
        public void connectFailed(URI uri, SocketAddress sa, IOException ioe) {
            // 不使用代理，无需处理
        }
    };

    private final GiteeProperties props;
    private final ObjectMapper objectMapper;

    private final HttpClient http = HttpClient.newBuilder()
            .proxy(NO_PROXY)
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    /** 上一次请求的时间戳（毫秒），用于全局限速。 */
    private final Object throttleLock = new Object();
    private long lastRequestAt = 0L;

    // ======================================================================
    // OAuth2（注意：token 端点在网页域 /oauth/token，不在 /api/v5 下）
    // ======================================================================

    /**
     * 拼授权页地址（**用户浏览器**跳转，非服务端调用）。
     *
     * <p>用 {@code oauth-authorize-base-url}（默认 {@code https://gitee.com}）而<b>不是</b>
     * {@code web-base-url}：后者是服务端域（换令牌 {@code /oauth/token} 用）。
     * 把两者分开，才能避免「服务端指向本地桩 ⇒ 用户的浏览器也被送进桩、看到假授权页
     * 与假账号」这类静默假成功。</p>
     */
    public String authorizeUrl(String state) {
        return trimSlash(props.getOauthAuthorizeBaseUrl()) + "/oauth/authorize"
                + "?client_id=" + enc(props.getClientId())
                + "&redirect_uri=" + enc(props.getRedirectUri())
                + "&response_type=code"
                + "&state=" + enc(state)
                + "&scope=" + enc(props.getScope());
    }

    private static String trimSlash(String s) {
        if (s == null) {
            return "";
        }
        String t = s.trim();
        return t.endsWith("/") ? t.substring(0, t.length() - 1) : t;
    }

    /** 授权跳转的落地域名（用于界面提示与排障）。 */
    public String authorizeHost() {
        return hostOf(props.getOauthAuthorizeBaseUrl());
    }

    /**
     * 授权跳转是否指向**非生产**域（本地桩 / 自建代理）。
     *
     * <p>true 表示用户浏览器不会到达真实 Gitee，而是被桩或代理直接签发身份。
     * 调用方必须把它**显式暴露**给用户/运维，而不是让它表现成一次正常的授权成功 ——
     * 「假成功」比报错更难发现。</p>
     */
    public boolean authorizeHostIsSandbox() {
        String h = authorizeHost();
        return !h.isEmpty() && !"gitee.com".equalsIgnoreCase(h) && !"www.gitee.com".equalsIgnoreCase(h);
    }

    private static String hostOf(String url) {
        if (url == null || url.isBlank()) {
            return "";
        }
        try {
            String h = java.net.URI.create(url.trim()).getHost();
            return h == null ? "" : h;
        } catch (Exception e) {
            return "";
        }
    }

    /**
     * 授权码换令牌：{@code POST /oauth/token}（form-urlencoded）。
     *
     * @return 归一化后的令牌视图（access_token / refresh_token / expires_in / scope）
     */
    public Map<String, Object> exchangeCode(String code) {
        Map<String, String> form = new LinkedHashMap<>();
        form.put("grant_type", "authorization_code");
        form.put("code", code);
        form.put("client_id", props.getClientId());
        form.put("client_secret", props.getClientSecret());
        form.put("redirect_uri", props.getRedirectUri());
        return formPost(props.getWebBaseUrl() + "/oauth/token", form);
    }

    /** 刷新令牌：{@code POST /oauth/token} grant_type=refresh_token。 */
    public Map<String, Object> refreshToken(String refreshToken) {
        Map<String, String> form = new LinkedHashMap<>();
        form.put("grant_type", "refresh_token");
        form.put("refresh_token", refreshToken);
        form.put("client_id", props.getClientId());
        form.put("client_secret", props.getClientSecret());
        form.put("redirect_uri", props.getRedirectUri());
        return formPost(props.getWebBaseUrl() + "/oauth/token", form);
    }

    // ======================================================================
    // 用户与组织
    // ======================================================================

    /** 当前令牌对应的 Gitee 用户：{@code GET /user}。 */
    public Map<String, Object> getUser(String token) {
        return asMap(get(token, "/user", Map.of()));
    }

    /** 当前用户所属组织：{@code GET /user/orgs}。 */
    public List<Map<String, Object>> listUserOrgs(String token) {
        return asList(get(token, "/user/orgs", Map.of()));
    }

    /** 组织信息：{@code GET /orgs/{org}}（无令牌，仅取公开信息）。 */
    public Map<String, Object> getOrg(String org) {
        return asMap(get(null, "/orgs/" + encPath(org), Map.of()));
    }

    /**
     * 组织信息（带令牌）：{@code GET /orgs/{org}}。
     *
     * <p>用于校验<b>当前账号</b>对该组织的可见性（成员未必能看到组织）；
     * 无令牌时回落到公开信息。供 {@code GiteeTenantConfigService} 的 best-effort 可见性探测使用。</p>
     */
    public Map<String, Object> getOrg(String token, String org) {
        return asMap(get(StringUtils.hasText(token) ? token : null, "/orgs/" + encPath(org), Map.of()));
    }

    /** 组织成员：{@code GET /orgs/{org}/members}。 */
    public List<Map<String, Object>> listOrgMembers(String token, String org) {
        return asList(get(token, "/orgs/" + encPath(org) + "/members", Map.of("per_page", "100")));
    }

    // ======================================================================
    // 仓库
    // ======================================================================

    /** 在**组织**下建仓：{@code POST /orgs/{org}/repos}。已实测该端点存在（401 = 缺令牌）。 */
    public Map<String, Object> createOrgRepo(String token, String org, String name, String path,
                                             String description, boolean isPrivate, boolean autoInit) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", name);
        body.put("path", path);
        body.put("description", description == null ? "" : description);
        body.put("private", isPrivate);
        body.put("auto_init", autoInit);
        // 自动带上 README 时顺带给一个 gitignore 模板，避免空仓库首次 push 无处可依
        body.put("has_issues", true);
        body.put("has_wiki", false);
        return asMap(postJson(token, "/orgs/" + encPath(org) + "/repos", body));
    }

    /** 在**用户**命名空间下建仓：{@code POST /user/repos}（未配置组织时的降级路径）。 */
    public Map<String, Object> createUserRepo(String token, String name, String description,
                                              boolean isPrivate, boolean autoInit) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", name);
        body.put("description", description == null ? "" : description);
        body.put("private", isPrivate);
        body.put("auto_init", autoInit);
        body.put("has_issues", true);
        return asMap(postJson(token, "/user/repos", body));
    }

    /** 仓库详情：{@code GET /repos/{owner}/{repo}}。 */
    public Map<String, Object> getRepo(String token, String owner, String repo) {
        return asMap(get(token, "/repos/" + encPath(owner) + "/" + encPath(repo), Map.of()));
    }

    /** 删除仓库：{@code DELETE /repos/{owner}/{repo}}（不可逆，调用方须显式确认）。 */
    public void deleteRepo(String token, String owner, String repo) {
        send(token, "DELETE", "/repos/" + encPath(owner) + "/" + encPath(repo), Map.of(), null);
    }

    // ======================================================================
    // Webhook
    // ======================================================================

    /**
     * 创建 Webhook：{@code POST /repos/{owner}/{repo}/hooks}。
     *
     * <p>Gitee 的校验方式是**共享密钥明文比对**（响应头 {@code X-Gitee-Token} 等于此处 password），
     * 不是 GitHub 那样的 HMAC 签名 —— 这是两者最容易搞混的地方（见 docs/30 §3.3）。</p>
     */
    public Map<String, Object> createHook(String token, String owner, String repo,
                                          String url, String secret, boolean push, boolean pr,
                                          boolean issue, boolean note) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("url", url);
        body.put("password", secret);
        body.put("push_events", push);
        body.put("merge_requests_events", pr);
        body.put("issues_events", issue);
        body.put("note_events", note);
        body.put("encryption_type", 1);
        return asMap(postJson(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/hooks", body));
    }

    /** Webhook 列表：{@code GET /repos/{owner}/{repo}/hooks}。 */
    public List<Map<String, Object>> listHooks(String token, String owner, String repo) {
        return asList(get(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/hooks", Map.of()));
    }

    /** 删除 Webhook：{@code DELETE /repos/{owner}/{repo}/hooks/{id}}。 */
    public void deleteHook(String token, String owner, String repo, Long hookId) {
        send(token, "DELETE", "/repos/" + encPath(owner) + "/" + encPath(repo) + "/hooks/" + hookId,
                Map.of(), null);
    }

    // ======================================================================
    // 内容（网页上传提交走这里）
    // ======================================================================

    /**
     * 读取文件/目录：{@code GET /repos/{owner}/{repo}/contents/{path}}。
     *
     * <p><b>返回类型必须在这里归一化</b>：Gitee 对同一个接口按 path 返回**两种形状** ——
     * 目录是 JSON 数组、文件是 JSON 对象。如果直接返回 {@code JsonNode}，调用方
     * {@code instanceof List} 永远为 false，会把目录误判成文件，进而拿到一片 null 字段
     * （实测踩过：文件内容回读为空、目录列表拿不到子项）。</p>
     *
     * @return 目录 → {@code List<Map<String,Object>>}；文件 → {@code Map<String,Object>}
     */
    public Object getContents(String token, String owner, String repo, String path, String ref) {
        Map<String, Object> q = new LinkedHashMap<>();
        if (StringUtils.hasText(ref)) {
            q.put("ref", ref);
        }
        JsonNode n = get(token, "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/contents/" + encPath(path), q);
        return n != null && n.isArray() ? asList(n) : asMap(n);
    }

    /**
     * 新建文件：{@code POST /repos/{owner}/{repo}/contents/{path}}。
     *
     * <p><b>注意</b>：该接口只用于**新建**。对已存在的文件必须走
     * {@link #updateFile}（PUT + 带上旧 sha），否则 Gitee 返回 422。</p>
     *
     * @param contentBase64 文件内容的 Base64（Gitee 要求，不接受明文）
     */
    public Map<String, Object> putFile(String token, String owner, String repo, String path,
                                       String contentBase64, String message, String branch) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("content", contentBase64);
        body.put("message", message);
        if (StringUtils.hasText(branch)) {
            body.put("branch", branch);
        }
        return asMap(postJson(token, "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/contents/" + encPath(path), body));
    }

    /**
     * 更新已有文件：{@code PUT /repos/{owner}/{repo}/contents/{path}}。
     *
     * @param sha 该文件**当前**的 blob sha（Gitee 用它做并发冲突检测；
     *            不传会被拒绝，因为服务端无法判断这是覆盖还是冲突）
     */
    public Map<String, Object> updateFile(String token, String owner, String repo, String path,
                                          String contentBase64, String message, String branch, String sha) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("content", contentBase64);
        body.put("message", message);
        body.put("sha", sha);
        if (StringUtils.hasText(branch)) {
            body.put("branch", branch);
        }
        return asMap(send(token, "PUT", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/contents/" + encPath(path), Map.of(), body));
    }

    // ======================================================================
    // 分支 / 提交 / PR / Issue
    // ======================================================================

    /** 分支列表：{@code GET /repos/{owner}/{repo}/branches}。 */
    public List<Map<String, Object>> listBranches(String token, String owner, String repo) {
        return asList(get(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/branches", Map.of()));
    }

    /** 提交列表：{@code GET /repos/{owner}/{repo}/commits}。 */
    public List<Map<String, Object>> listCommits(String token, String owner, String repo, String sha, int perPage) {
        Map<String, Object> q = new LinkedHashMap<>();
        if (StringUtils.hasText(sha)) {
            q.put("sha", sha);
        }
        q.put("per_page", String.valueOf(perPage));
        return asList(get(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/commits", q));
    }

    // ======================================================================
    // 成员权限（协作者）
    // ======================================================================

    /** 协作者列表（**公开可读**）：{@code GET /repos/{owner}/{repo}/collaborators}。 */
    public List<Map<String, Object>> listCollaborators(String token, String owner, String repo) {
        return asList(get(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/collaborators",
                Map.of("per_page", "100")));
    }

    /**
     * 添加/更新协作者：{@code PUT /repos/{owner}/{repo}/collaborators/{username}}。
     *
     * @param permission read / write / admin（Gitee 大小写不敏感）
     */
    public void addCollaborator(String token, String owner, String repo, String username, String permission) {
        send(token, "PUT", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/collaborators/" + encPath(username), Map.of(), Map.of("permission", permission));
    }

    /** 移除协作者：{@code DELETE /repos/{owner}/{repo}/collaborators/{username}}。 */
    public void removeCollaborator(String token, String owner, String repo, String username) {
        send(token, "DELETE", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/collaborators/" + encPath(username), Map.of(), null);
    }

    // ======================================================================
    // 仓库级团队关联（组织级 Team 无 API，只能做 repo↔team 关联）
    // ======================================================================

    /** 仓库已关联的团队：{@code GET /repos/{owner}/{repo}/teams}（已实测存在）。 */
    public List<Map<String, Object>> listRepoTeams(String token, String owner, String repo) {
        return asList(get(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/teams", Map.of()));
    }

    /** 把仓库挂到团队下：{@code PUT /repos/{owner}/{repo}/teams/{team}。 */
    public void addRepoTeam(String token, String owner, String repo, Object team) {
        send(token, "PUT", "/repos/" + encPath(owner) + "/" + encPath(repo) + "/teams/" + team,
                Map.of(), Map.of("permission", "push"));
    }

    // ======================================================================
    // HTTP 基础设施
    // ======================================================================

    private Map<String, Object> formPost(String url, Map<String, String> form) {
        StringBuilder sb = new StringBuilder();
        form.forEach((k, v) -> {
            if (sb.length() > 0) {
                sb.append('&');
            }
            sb.append(enc(k)).append('=').append(enc(v == null ? "" : v));
        });
        throttle();
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(props.getHttpTimeoutSeconds()))
                .header("Content-Type", "application/x-www-form-urlencoded")
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(sb.toString(), StandardCharsets.UTF_8))
                .build();
        return asMap(execute(req));
    }

    private JsonNode get(String token, String path, Map<String, Object> query) {
        return send(token, "GET", path, query, null);
    }

    private JsonNode postJson(String token, String path, Object body) {
        return send(token, "POST", path, Map.of(), body);
    }

    /**
     * 统一请求出口：拼 query、加认证头、节流、解析、错误归一化。
     *
     * @return 响应 JSON 根节点
     */
    private JsonNode send(String token, String method, String path, Map<String, Object> query, Object body) {
        StringBuilder url = new StringBuilder(props.getBaseUrl()).append(path);
        if (query != null && !query.isEmpty()) {
            url.append('?');
            query.forEach((k, v) -> url.append(enc(k)).append('=').append(enc(String.valueOf(v))).append('&'));
            url.setLength(url.length() - 1);
        }

        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url.toString()))
                .timeout(Duration.ofSeconds(props.getHttpTimeoutSeconds()))
                .header("Accept", "application/json")
                .header("User-Agent", "AIOA-Gitee-Integration/1.0");

        // 令牌**只走请求头**（`Authorization: token xxx`），绝不放 query：
        // query 会进访问日志、浏览器历史与 Referer，是最常见的令牌泄露途径。
        // Gitee 两种形态都支持，实测 header 形态能被正确解析（无效令牌返回
        // {"message":"401 Unauthorized: Access token does not exist"}）。
        if (StringUtils.hasText(token)) {
            b.header("Authorization", "token " + token);
        }

        HttpRequest.BodyPublisher pub = body == null
                ? HttpRequest.BodyPublishers.noBody()
                : HttpRequest.BodyPublishers.ofString(writeJson(body), StandardCharsets.UTF_8);
        if (body != null) {
            b.header("Content-Type", "application/json");
        }
        switch (method) {
            case "GET" -> b.GET();
            case "POST" -> b.POST(pub);
            case "PUT" -> b.PUT(pub);
            case "PATCH" -> b.method("PATCH", pub);
            case "DELETE" -> b.DELETE();
            default -> throw new IllegalArgumentException("不支持的 HTTP 方法：" + method);
        }
        throttle();
        return execute(b.build());
    }

    /** 执行并归一化错误。 */
    private JsonNode execute(HttpRequest req) {
        HttpResponse<String> resp;
        try {
            resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw GiteeApiException.network("连接 Gitee 失败：" + e.getClass().getSimpleName()
                    + " " + e.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw GiteeApiException.network("调用 Gitee 被中断");
        }

        int status = resp.statusCode();
        String bodyText = resp.body() == null ? "" : resp.body();

        if (status >= 200 && status < 300) {
            if (bodyText.isBlank()) {
                return objectMapper.createObjectNode();
            }
            try {
                return objectMapper.readTree(bodyText);
            } catch (Exception e) {
                // 非 JSON 成功响应（极少）：包成 {raw:...} 交上层判断，不因解析失败丢掉成功语义
                return objectMapper.createObjectNode().put("raw", bodyText);
            }
        }

        String message = extractMessage(bodyText);
        int giteeCode = extractCode(bodyText);
        log.warn("Gitee API {} {} -> HTTP {} code={} msg={}",
                req.method(), req.uri().getPath(), status, giteeCode, message);
        throw GiteeApiException.of(status, giteeCode, message);
    }

    private String extractMessage(String body) {
        if (body == null || body.isBlank()) {
            return "Gitee 返回空响应";
        }
        if (body.stripLeading().startsWith("<")) {
            // Gitee 对**不存在的路由**会返回 HTML 404 页（实测），这里给出可读结论
            return "Gitee 返回 HTML 错误页（通常表示该接口在 V5 中不存在）";
        }
        try {
            JsonNode n = objectMapper.readTree(body);
            if (n.hasNonNull("message")) {
                return n.get("message").asText();
            }
            if (n.hasNonNull("error")) {
                return n.get("error").asText();
            }
        } catch (Exception ignored) {
            // 落到原文截断
        }
        return body.length() > 300 ? body.substring(0, 300) : body;
    }

    private int extractCode(String body) {
        try {
            JsonNode n = objectMapper.readTree(body);
            return n.hasNonNull("code") ? n.get("code").asInt() : 0;
        } catch (Exception e) {
            return 0;
        }
    }

    /** 全局限速：Gitee 对高频请求返回 403 Rate Limit Exceeded（已实测）。 */
    private void throttle() {
        long interval = Math.max(0, props.getMinRequestIntervalMs());
        if (interval == 0) {
            return;
        }
        synchronized (throttleLock) {
            long wait = lastRequestAt + interval - System.currentTimeMillis();
            if (wait > 0) {
                try {
                    Thread.sleep(wait);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            lastRequestAt = System.currentTimeMillis();
        }
    }

    private String writeJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            throw new IllegalStateException("序列化请求体失败", e);
        }
    }

    private Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) {
            return Map.of();
        }
        return objectMapper.convertValue(n, new TypeReference<LinkedHashMap<String, Object>>() {
        });
    }

    private List<Map<String, Object>> asList(JsonNode n) {
        if (n == null || !n.isArray()) {
            return new ArrayList<>();
        }
        return objectMapper.convertValue(n, new TypeReference<ArrayList<Map<String, Object>>>() {
        });
    }

    private static String enc(String v) {
        return URLEncoder.encode(v == null ? "" : v, StandardCharsets.UTF_8);
    }

    /** 路径段编码：仅编码会破坏路径的字符，保留 `/` 以便传多级路径（如 contents/a/b.txt）。 */
    private static String encPath(String v) {
        if (v == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (String seg : v.split("/", -1)) {
            if (sb.length() > 0) {
                sb.append('/');
            }
            sb.append(URLEncoder.encode(seg, StandardCharsets.UTF_8).replace("+", "%20"));
        }
        return sb.toString();
    }
}
