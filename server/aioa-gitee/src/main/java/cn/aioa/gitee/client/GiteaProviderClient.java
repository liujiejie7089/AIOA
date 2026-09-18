package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;
import java.io.IOException;
import java.io.InputStream;
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
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Gitea 1.26.2 API 客户端 —— {@link RepoProviderClient} 的 Gitea 实现。
 *
 * <p>契约来源：<b>目标实例自述的 OpenAPI 规范</b>
 * （{@code GET {webBaseUrl}/swagger.v1.json}，Swagger 2.0 / 300 路径），
 * 已按实例实测锁定字段级差异，见 {@code .workbuddy/artifacts/gitea-api-contract-1.26.2.md}。
 * 之所以不照官网文档写：官网描述的是最新版，而我们要对接的是自建的具体版本，
 * 版本间的字段增删会把「版本差异」伪装成「我写错了」。</p>
 *
 * <p><b>装配</b>：仅当 {@code aioa.repo.provider=gitea} 时生效（见类注解）。
 * 默认仍是 Gitee，因此引入本类<b>不改变现有部署的行为</b>。</p>
 *
 * <p><b>与 {@link GiteeClient} 的 HTTP 基础设施是各自独立的</b>（代理禁用、节流、
 * 错误归一化大约 130 行重复）。这是<b>刻意</b>的取舍：Gitee 链路已在真站验证通过，
 * 为了消除重复去动它，风险大于收益。待两条链路都验证过，再把公共部分上提为一个
 * 共享执行器 —— 届时有两套经过验证的行为作对照，收敛才有依据。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "aioa.repo", name = "provider", havingValue = "gitea")
public class GiteaProviderClient implements RepoProviderClient {

    /** 通用 Webhook 的 {@code type} 取值（Gitea 的枚举名就叫 {@code gitea}）。 */
    static final String HOOK_TYPE_GENERIC = "gitea";

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

    private final GiteaProperties props;
    private final ObjectMapper objectMapper;
    private final HttpClient http;

    private final Object throttleLock = new Object();
    private long lastRequestAt = 0L;

    public GiteaProviderClient(GiteaProperties props, ObjectMapper objectMapper) {
        this.props = props;
        this.objectMapper = objectMapper;
        this.http = buildHttpClient(props);
    }

    /**
     * Gitea 新建仓库的默认分支。
     *
     * <p>取值来源：实例实测（1.26.2，`POST /orgs/{org}/repos` 带 {@code auto_init=true}）
     * 回来的 {@code default_branch} 为 <b>{@code main}</b>。Gitea 由服务端
     * {@code DEFAULT_BRANCH} 决定，本实例未改成 {@code master}。</p>
     *
     * <p><b>不能因为「Gitee 是 master」就照抄</b>：分支名写错不会报配置错，
     * 只会让读写文件与目录浏览静默 404。</p>
     */
    @Override
    public String defaultBranch() {
        return "main";
    }

    // ======================================================================
    // OAuth2
    // ======================================================================

    @Override
    public String authorizeUrl(String state) {
        return props.oauthAuthorizeUrl()
                + "?client_id=" + enc(props.getClientId())
                + "&redirect_uri=" + enc(props.getRedirectUri())
                + "&response_type=code"
                + "&state=" + enc(state)
                + "&scope=" + enc(props.getScope());
    }

    @Override
    public String authorizeHost() {
        return hostOf(props.getOauthAuthorizeBaseUrl());
    }

    /**
     * 授权跳转是否指向「非本实例」的域。
     *
     * <p><b>判据与 Gitee 实现不同</b>：Gitee 是公有云，参照物写死 {@code gitee.com}；
     * 而 Gitea 是自建实例，参照物只能是<b>配置里的本实例网页域</b>。
     * 因此这里比对「授权跳转域名」与「{@code web-base-url} 域名」是否一致 ——
     * 一致说明用户浏览器到达的是真实例，不一致说明被指向了别处（桩 / 代理）。</p>
     */
    @Override
    public boolean authorizeHostIsSandbox() {
        String auth = authorizeHost();
        String real = hostOf(props.getWebBaseUrl());
        if (auth.isEmpty() || real.isEmpty()) {
            return true;   // 说不清就当它是可疑的，让上层显式暴露，而不是默认安全
        }
        return !auth.equalsIgnoreCase(real);
    }

    @Override
    public Map<String, Object> exchangeCode(String code) {
        Map<String, String> form = new LinkedHashMap<>();
        form.put("grant_type", "authorization_code");
        form.put("code", code);
        form.put("client_id", props.getClientId());
        form.put("client_secret", props.getClientSecret());
        form.put("redirect_uri", props.getRedirectUri());
        return formPost(props.oauthTokenUrl(), form);
    }

    @Override
    public Map<String, Object> refreshToken(String refreshToken) {
        Map<String, String> form = new LinkedHashMap<>();
        form.put("grant_type", "refresh_token");
        form.put("refresh_token", refreshToken);
        form.put("client_id", props.getClientId());
        form.put("client_secret", props.getClientSecret());
        return formPost(props.oauthTokenUrl(), form);
    }

    // ======================================================================
    // 用户与组织
    // ======================================================================

    @Override
    public Map<String, Object> getUser(String token) {
        return asMap(send(token, "GET", "/user", Map.of(), null));
    }

    @Override
    public Map<String, Object> getOrg(String token, String org) {
        return asMap(send(StringUtils.hasText(token) ? token : null, "GET",
                "/orgs/" + encPath(org), Map.of(), null));
    }

    // ======================================================================
    // 仓库
    // ======================================================================

    @Override
    public Map<String, Object> createOrgRepo(String token, String org, String name, String path,
                                            String description, boolean isPrivate, boolean autoInit) {
        Map<String, Object> body = buildCreateRepoBody(name, path, description, isPrivate,
                autoInit, props.getRepoNameSource(), props.getRepoNameMaxLength());
        return asMap(send(token, "POST", "/orgs/" + encPath(org) + "/repos", Map.of(), body));
    }

    @Override
    public Map<String, Object> createUserRepo(String token, String name, String description,
                                              boolean isPrivate, boolean autoInit) {
        Map<String, Object> body = buildCreateRepoBody(name, null, description, isPrivate,
                autoInit, GiteaProperties.RepoNameSource.NAME, props.getRepoNameMaxLength());
        return asMap(send(token, "POST", "/user/repos", Map.of(), body));
    }

    @Override
    public Map<String, Object> getRepo(String token, String owner, String repo) {
        return asMap(send(token, "GET", "/repos/" + encPath(owner) + "/" + encPath(repo),
                Map.of(), null));
    }

    @Override
    public void deleteRepo(String token, String owner, String repo) {
        send(token, "DELETE", "/repos/" + encPath(owner) + "/" + encPath(repo), Map.of(), null);
    }

    // ======================================================================
    // Webhook
    // ======================================================================

    @Override
    public Map<String, Object> createHook(String token, String owner, String repo,
                                          String url, String secret, boolean push, boolean pr,
                                          boolean issue, boolean note) {
        Map<String, Object> body = buildCreateHookBody(url, secret, push, pr, issue, note);
        return asMap(send(token, "POST",
                "/repos/" + encPath(owner) + "/" + encPath(repo) + "/hooks", Map.of(), body));
    }

    @Override
    public List<Map<String, Object>> listHooks(String token, String owner, String repo) {
        return listAllPaged(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/hooks");
    }

    @Override
    public void deleteHook(String token, String owner, String repo, Long hookId) {
        send(token, "DELETE", "/repos/" + encPath(owner) + "/" + encPath(repo) + "/hooks/" + hookId,
                Map.of(), null);
    }

    // ======================================================================
    // 内容
    // ======================================================================

    @Override
    public Object getContents(String token, String owner, String repo, String path, String ref) {
        Map<String, Object> q = new LinkedHashMap<>();
        if (StringUtils.hasText(ref)) {
            q.put("ref", ref);
        }
        JsonNode n = send(token, "GET", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/contents/" + encPath(path), q, null);
        // 与 Gitee 同：目录返回数组、文件返回对象。不在这里归一化，
        // 调用方的 instanceof List 会永远为 false（目录被误判成文件）。
        return n != null && n.isArray() ? asList(n) : asMap(n);
    }

    @Override
    public Map<String, Object> putFile(String token, String owner, String repo, String path,
                                       String contentBase64, String message, String branch) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("content", contentBase64);
        body.put("message", StringUtils.hasText(message) ? message : "add " + path);
        if (StringUtils.hasText(branch)) {
            body.put("branch", branch);
        }
        return asMap(send(token, "POST", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/contents/" + encPath(path), Map.of(), body));
    }

    @Override
    public Map<String, Object> updateFile(String token, String owner, String repo, String path,
                                          String contentBase64, String message, String branch, String sha) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("content", contentBase64);
        body.put("message", StringUtils.hasText(message) ? message : "update " + path);
        body.put("sha", sha);
        if (StringUtils.hasText(branch)) {
            body.put("branch", branch);
        }
        return asMap(send(token, "PUT", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/contents/" + encPath(path), Map.of(), body));
    }

    @Override
    public List<Map<String, Object>> listBranches(String token, String owner, String repo) {
        return listAllPaged(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/branches");
    }

    // ======================================================================
    // 成员
    // ======================================================================

    @Override
    public List<Map<String, Object>> listCollaborators(String token, String owner, String repo) {
        return listAllPaged(token, "/repos/" + encPath(owner) + "/" + encPath(repo) + "/collaborators");
    }

    @Override
    public void addCollaborator(String token, String owner, String repo, String username, String permission) {
        // permission 枚举 read/write/admin 与 Gitee 完全一致（实例规范 AddCollaboratorOption 实测）
        send(token, "PUT", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/collaborators/" + encPath(username), Map.of(), Map.of("permission", permission));
    }

    @Override
    public void removeCollaborator(String token, String owner, String repo, String username) {
        send(token, "DELETE", "/repos/" + encPath(owner) + "/" + encPath(repo)
                + "/collaborators/" + encPath(username), Map.of(), null);
    }

    // ======================================================================
    // 纯函数：请求体构造（**与 HTTP 解耦，因此可以被单测直接覆盖**）
    //
    // 放在这里而不是内联进各方法，是因为下面每一处都对应一个「接口返回 200、
    // 功能却没生效」的静默失效陷阱 —— 只有把它们变成可断言的值，才能防止回归。
    // ======================================================================

    /**
     * 决定 Gitea 的仓库标识（{@code CreateRepoOption.name}，同时也是 URL 片段）。
     *
     * <p><b>为什么需要这个函数</b>：Gitee 的 {@code name}（展示名，可含中文）与
     * {@code path}（URL 片段）是<b>两个字段</b>，而 Gitea 只有一个 {@code name}。
     * 这是本次迁移中<b>唯一带破坏性的口径</b>，所以把它做成一个显式、可配置、
     * 可单测的决策，而不是埋在拼装逻辑里。</p>
     *
     * @throws RepoProviderException {@code source=PATH} 且 {@code path} 为空时抛错
     *                               —— 显式要求用 path 却拿不到，必须失败而不是
     *                               静默回落到 name（那会产出与预期不符的 URL）
     */
    static String resolveRepoName(String name, String path, GiteaProperties.RepoNameSource source,
                                  int maxLength) {
        GiteaProperties.RepoNameSource s = source == null
                ? GiteaProperties.RepoNameSource.AUTO : source;
        String chosen;
        switch (s) {
            case NAME -> chosen = name;
            case PATH -> {
                if (!StringUtils.hasText(path)) {
                    throw new RepoProviderException(0,
                            "仓库标识来源被配置为 PATH，但未提供 path（Gitea 的仓库标识不能为空）",
                            false, false);
                }
                chosen = path;
            }
            default -> chosen = StringUtils.hasText(path) ? path : name;
        }
        if (!StringUtils.hasText(chosen)) {
            throw new RepoProviderException(0, "仓库标识为空：name 与 path 均未提供", false, false);
        }
        String trimmed = chosen.trim();
        if (maxLength > 0 && trimmed.length() > maxLength) {
            trimmed = trimmed.substring(0, maxLength);
        }
        return trimmed;
    }

    /**
     * 构造建仓请求体（{@code CreateRepoOption}）。
     *
     * <p><b>刻意不写进去的两个键，以及一个必须写的键</b>：</p>
     * <ul>
     *   <li>{@code path} —— 该字段<b>在 Gitea 不存在</b>。带上不报错但无效果，
     *       会让人误以为「双字段都设好了」；</li>
     *   <li>{@code has_issues} / {@code has_wiki} —— <b>不在创建体里</b>
     *       （属 {@code EditRepoOption}）。带上同样不报错但无效果，属静默失效；</li>
     *   <li>{@code auto_init} —— 必须显式传：它决定仓库是否带 README 初始化，
     *       不传则建出<b>空仓库</b>，首次 push / 写文件会因无默认分支而失败。</li>
     * </ul>
     */
    static Map<String, Object> buildCreateRepoBody(String name, String path, String description,
                                                  boolean isPrivate, boolean autoInit,
                                                  GiteaProperties.RepoNameSource source,
                                                  int maxLength) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", resolveRepoName(name, path, source, maxLength));
        body.put("description", description == null ? "" : description);
        body.put("private", isPrivate);
        body.put("auto_init", autoInit);
        return body;
    }

    /**
     * 事件订阅开关 → Gitea 事件名列表。
     *
     * <p><b>事件名是下划线风格</b>（{@code pull_request} 而非 {@code "Pull Request"}），
     * 与 Gitee 的 {@code "Merge Request Hook"} 完全不同；写错不会报错，只会
     * <b>该事件永不投递</b>。</p>
     */
    static List<String> hookEvents(boolean push, boolean pr, boolean issue, boolean note) {
        List<String> events = new ArrayList<>();
        if (push) {
            events.add("push");
        }
        if (pr) {
            events.add("pull_request");
            events.add("pull_request_review");
        }
        if (issue) {
            events.add("issues");
        }
        if (note) {
            // Gitea 把 PR 上的评论也作为 issue_comment 投递；
            // pull_request_review_comment 是评审行内评论，单独订阅才收得到。
            events.add("issue_comment");
            events.add("pull_request_review_comment");
        }
        return events;
    }

    /**
     * {@inheritDoc}
     *
     * <p>直接复用 {@link #hookEvents} —— 展示用的词表与真正建钩子的词表<b>同源</b>，
     * 不可能再出现「界面说订了 merge_requests、仓库实际订的是 pull_request」。</p>
     */
    @Override
    public List<String> hookEventNames(boolean push, boolean pr, boolean issue, boolean note) {
        return hookEvents(push, pr, issue, note);
    }

    /**
     * 构造建 Webhook 请求体（{@code CreateHookOption}）。
     *
     * <p><b>本方法存在的意义就是挡住两个「200 成功但功能不生效」的陷阱</b>：</p>
     * <ol>
     *   <li>{@code type} 必须是 {@code "gitea"}（通用 Webhook）。不传或传错，
     *       建出来的不是能回调我们的那种 hook；</li>
     *   <li>{@code active} 在实例规范里<b>默认 false</b>。不显式置 true，
     *       Webhook 会以「已创建但已停用」的状态存在 —— 创建接口返回 200，
     *       回调却一条都不来。这是最难查的一类故障，所以这里写死 true
     *       并有单测守着。</li>
     * </ol>
     *
     * <p>{@code config.secret} 是 <b>HMAC-SHA256 的密钥</b>（回调头
     * {@code X-Gitea-Signature}），与 Gitee 把它当「明文共享密钥」的用法无关 ——
     * 两边都叫 secret，算法不通用。</p>
     */
    static Map<String, Object> buildCreateHookBody(String url, String secret,
                                                   boolean push, boolean pr,
                                                   boolean issue, boolean note) {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("url", url);
        config.put("content_type", "json");
        if (StringUtils.hasText(secret)) {
            config.put("secret", secret);
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("type", HOOK_TYPE_GENERIC);
        body.put("active", true);           // ← 不置 true 则 hook 建好即停用（静默失效）
        body.put("events", hookEvents(push, pr, issue, note));
        body.put("config", config);
        return body;
    }

    // ======================================================================
    // Webhook 接收侧：HMAC-SHA256（与 Gitee 的明文比对完全不同）
    // ======================================================================

    @Override
    public String webhookEventHeader() {
        return "X-Gitea-Event";
    }

    @Override
    public String webhookRequestIdHeader() {
        return "X-Gitea-Delivery";
    }

    /**
     * 校验投递：Gitea 用 <b>HMAC-SHA256</b> 签名，密钥是建 hook 时写入
     * {@code config.secret} 的那个值。
     *
     * <p><b>与 Gitee 的关键差别</b>：Gitee 把密钥明文回传（比对字符串即可），
     * Gitea 只回传签名。因此「换个头名」是不够的 —— 校验算法必须整段替换：
     * 拿明文比对去验 Gitea 会 100% 拒绝；反过来则等于把校验退化成
     * 「谁都能写」。</p>
     *
     * <p>签名头有两种形态，都要接受：</p>
     * <ul>
     *   <li>{@code X-Gitea-Signature}：十六进制，<b>无前缀</b>（Gitea 原生）；</li>
     *   <li>{@code X-Hub-Signature-256}：{@code sha256=<十六进制>}（GitHub 兼容）。</li>
     * </ul>
     */
    @Override
    public boolean verifyWebhook(byte[] rawBody, Map<String, String> headers, String secret) {
        if (!StringUtils.hasText(secret) || rawBody == null) {
            return false;
        }
        String provided = extractSignature(headers);
        if (provided.isEmpty()) {
            return false;
        }
        String expected = hmacSha256Hex(rawBody, secret);
        return constantTimeEqualsHex(expected, provided);
    }

    /**
     * 从请求头取出签名值（十六进制、无前缀）。
     *
     * <p>优先取 Gitea 原生头；若只有 GitHub 兼容头，则要求前缀是 {@code sha256=}
     * —— 遇到 {@code sha1=} 直接视为无效：HmacSHA1 与 HmacSHA256 的摘要长度不同，
     * 若把 sha1 的值当 sha256 口径去比，只会得到一个恒为 false 的比较，
     * 倒不如显式拒绝，让日志里的原因指向「客户端用了弱算法」。</p>
     */
    static String extractSignature(Map<String, String> headers) {
        String native_ = header(headers, "X-Gitea-Signature");
        if (StringUtils.hasText(native_)) {
            return stripPrefix(native_);
        }
        String hub = header(headers, "X-Hub-Signature-256");
        if (StringUtils.hasText(hub)) {
            String lower = hub.toLowerCase();
            if (lower.startsWith("sha1=")) {
                return "";   // 明确拒绝弱算法，而不是拿它去比 sha256
            }
            return stripPrefix(hub);
        }
        return "";
    }

    /** 去掉 {@code sha256=} 一类的前缀，只留十六进制部分。 */
    private static String stripPrefix(String v) {
        String t = v.trim();
        int eq = t.indexOf('=');
        return eq >= 0 ? t.substring(eq + 1).trim() : t;
    }

    /**
     * {@code HMAC-SHA256(原始报文字节, 密钥)} 的十六进制小写表示。
     *
     * <p>注意是对<b>字节</b>计算：先把报文体转成字符串再 {@code getBytes()} 会引入
     * 字符集往返，只要客户端与我们的解码方式有一丝不同，签名就永远不匹配，
     * 而排查方向会被误导到「密钥配错了」。</p>
     */
    public static String hmacSha256Hex(byte[] body, String secret) {
        try {
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(
                    secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] digest = mac.doFinal(body);
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            // HmacSHA256 是 JDK 必备算法，走到这里说明运行环境异常
            throw new IllegalStateException("计算 HmacSHA256 失败", e);
        }
    }

    /**
     * 十六进制摘要的常量时间比对（大小写不敏感）。
     *
     * <p>用常量时间比对而非 {@code String.equals}：后者在首个不同字符处提前返回，
     * 泄露「已匹配的前缀长度」，使攻击者可以逐字节爆破签名。</p>
     *
     * <p>长度不同直接返回 false —— 长度本身不是秘密（HMAC-SHA256 固定 64 个字符），
     * 但必须先比长度才能安全地进入定长循环。</p>
     */
    static boolean constantTimeEqualsHex(String expected, String provided) {
        if (expected == null || provided == null) {
            return false;
        }
        byte[] a = expected.toLowerCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8);
        byte[] b = provided.toLowerCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8);
        if (a.length != b.length) {
            return false;
        }
        return java.security.MessageDigest.isEqual(a, b);
    }

    /** 大小写不敏感取头；缺失返回空串（不返回 null，便于直接比对）。 */
    static String header(Map<String, String> headers, String name) {
        if (headers == null) {
            return "";
        }
        String v = headers.get(name);
        if (v == null) {
            v = headers.get(name.toLowerCase(Locale.ROOT));
        }
        return v == null ? "" : v.trim();
    }

    // ======================================================================
    // HTTP 基础设施（代理禁用 / 节流 / 错误归一化）
    // ======================================================================

    /**
     * 构造 HttpClient：禁用代理 + 不做自动重定向 + 按需装配 TLS。
     *
     * <p><b>为什么显式禁用代理</b>：部署环境里存在 HTTP 代理环境变量时，
     * 走代理会拿到代理自身的错误页，表现为「Gitea 返回 401」这类假象。</p>
     *
     * <p><b>TLS 为什么必须可配</b>：私有化部署的 Gitea 常用<b>自签证书</b>，
     * 而默认 {@code HttpClient} 只信任 JVM 信任库，遇到自签会直接
     * {@code SSLHandshakeException} —— 表现为「连不上」，与网络不通难以区分。
     * 这里支持「导入自签 CA」（推荐）与「显式跳过校验」（最后手段，会 WARN）。</p>
     */
    private static HttpClient buildHttpClient(GiteaProperties props) {
        HttpClient.Builder b = HttpClient.newBuilder()
                .proxy(NO_PROXY)
                .followRedirects(HttpClient.Redirect.NEVER)
                .connectTimeout(Duration.ofSeconds(Math.max(1, props.getHttpTimeoutSeconds())));

        if (props.isInsecureSkipVerify()) {
            // 行为锚定的告警：说清「关了什么」和「后果是什么」，便于审计发现
            System.err.println("[gitea] ⚠⚠ TLS 校验已被显式关闭"
                    + "（aioa.gitea.insecure-skip-verify=true）：本客户端将接受任何证书，"
                    + "无法防御中间人冒充。仅可用于自签证书且确实拿不到 CA 的环境；"
                    + "生产请改用 aioa.gitea.trust-store 导入自签 CA。");
            try {
                SSLContext ctx = SSLContext.getInstance("TLS");
                ctx.init(null, new TrustManager[]{TRUST_ALL}, new SecureRandom());
                SSLParameters p = new SSLParameters();
                p.setEndpointIdentificationAlgorithm(null);   // 同时关掉主机名校验
                b.sslContext(ctx).sslParameters(p);
            } catch (Exception e) {
                throw new IllegalStateException("构造跳过校验的 TLS 上下文失败", e);
            }
        } else if (StringUtils.hasText(props.getTrustStore())) {
            b.sslContext(trustStoreContext(props));
        }
        return b.build();
    }

    /** 从配置的信任库构造 SSLContext（自签 CA 场景的推荐做法）。 */
    private static SSLContext trustStoreContext(GiteaProperties props) {
        try (InputStream in = Files.newInputStream(Path.of(props.getTrustStore().trim()))) {
            KeyStore ks = KeyStore.getInstance(
                    StringUtils.hasText(props.getTrustStoreType()) ? props.getTrustStoreType() : "PKCS12");
            ks.load(in, props.getTrustStorePassword() == null
                    ? new char[0] : props.getTrustStorePassword().toCharArray());
            TrustManagerFactory tmf = TrustManagerFactory.getInstance(
                    TrustManagerFactory.getDefaultAlgorithm());
            tmf.init(ks);
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, tmf.getTrustManagers(), new SecureRandom());
            return ctx;
        } catch (Exception e) {
            throw new IllegalStateException("加载信任库失败：" + props.getTrustStore()
                    + "（检查路径 / 口令 / 类型）", e);
        }
    }

    /** 接受一切证书的 TrustManager —— 仅在显式跳过校验时使用。 */
    private static final X509TrustManager TRUST_ALL = new X509TrustManager() {
        @Override
        public void checkClientTrusted(X509Certificate[] chain, String authType) {
            // 显式跳过：见 insecureSkipVerify 的说明
        }

        @Override
        public void checkServerTrusted(X509Certificate[] chain, String authType) {
            // 显式跳过
        }

        @Override
        public X509Certificate[] getAcceptedIssuers() {
            return new X509Certificate[0];
        }
    };

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

    /**
     * 统一请求出口：拼 query、加认证头、节流、解析、错误归一化。
     */
    private JsonNode send(String token, String method, String path, Map<String, Object> query, Object body) {
        String base = trimSlash(props.getBaseUrl());
        StringBuilder url = new StringBuilder(base).append(path);
        if (query != null && !query.isEmpty()) {
            url.append('?');
            query.forEach((k, v) -> url.append(enc(k)).append('=').append(enc(String.valueOf(v))).append('&'));
            url.setLength(url.length() - 1);
        }

        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url.toString()))
                .timeout(Duration.ofSeconds(props.getHttpTimeoutSeconds()))
                .header("Accept", "application/json")
                .header("User-Agent", "AIOA-Gitea-Integration/1.0");

        // 令牌只走请求头（Gitea 同时接受 `token <t>` 与 `Bearer <t>`），绝不放 query：
        // query 会进访问日志、浏览器历史与 Referer，是最常见的令牌泄露途径。
        if (StringUtils.hasText(token)) {
            b.header("Authorization", "token " + token.trim());
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

    private JsonNode execute(HttpRequest req) {
        HttpResponse<String> resp;
        try {
            resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new RepoProviderException(0, "连接 Gitea 失败：" + e.getClass().getSimpleName()
                    + " " + e.getMessage() + "（TLS 自签证书需配置 aioa.gitea.trust-store）",
                    true, false);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RepoProviderException(0, "调用 Gitea 被中断", true, false);
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
                // 非 JSON 成功响应：包成 {raw:...} 交上层，不因解析失败丢掉成功语义
                return objectMapper.createObjectNode().put("raw", bodyText);
            }
        }

        String message = extractMessage(bodyText);
        log.warn("Gitea API {} {} -> HTTP {} msg={}", req.method(), req.uri().getPath(), status, message);
        throw RepoProviderException.of(status, message);
    }

    private String extractMessage(String body) {
        if (body == null || body.isBlank()) {
            return "Gitea 返回空响应";
        }
        if (body.stripLeading().startsWith("<")) {
            return "Gitea 返回 HTML 错误页（通常表示该路由不存在或未登录）";
        }
        try {
            JsonNode n = objectMapper.readTree(body);
            String message = n.hasNonNull("message") ? n.get("message").asText() : null;
            String detail = firstDetail(n);
            // Gitea 在部分路由上把 message 写成**内部操作名**：实测
            // PUT /repos/{o}/{r}/collaborators/{name} 找不到该用户时，
            // message="GetUserByName"，真正的人话在 errors[] 里
            // （"user does not exist [name: xxx]"）。只取 message = 在入口就把可用信息丢掉，
            // 而上层正是拿这个字符串去写「成员同步失败」的用户可见原因。
            if (hasText(message) && hasText(detail) && !detail.equals(message)) {
                return detail + "（" + message + "）";
            }
            if (hasText(message)) {
                return message;
            }
            if (hasText(detail)) {
                return detail;
            }
        } catch (Exception ignored) {
            // 落到原文截断
        }
        return body.length() > 300 ? body.substring(0, 300) : body;
    }

    /**
     * Gitea 错误体的细目：{@code errors[]} 是整段响应里唯一含人话的部分
     * （{@code message} 可能是内部操作名，如 {@code GetUserByName}）。
     */
    static String firstDetail(JsonNode n) {
        JsonNode errors = n.get("errors");
        if (errors != null && errors.isArray() && !errors.isEmpty()) {
            StringBuilder sb = new StringBuilder();
            for (JsonNode e : errors) {
                if (sb.length() > 0) {
                    sb.append("；");
                }
                sb.append(e.asText());
            }
            if (hasText(sb.toString())) {
                return sb.toString();
            }
        }
        // OAuth2 换令牌端点的错误体是 {error, error_description}，与其它路由不同：
        // 这里 error **只是通用错误码**（实测旧应用的密钥失配与授权码无效都回
        // unauthorized_client），真正可执行的判据在 error_description
        // （invalid client secret / client is not authorized）。
        // 只取 error 会把「平台侧密钥不对」和「授权码不对」显示成同一个字符串 ——
        // 实测用户看到的绑定失败页只剩 `原因：unauthorized_client`，无法据此定位。
        // 该形状 Gitee 的 /oauth/token 同样适用，故放在托管方无关的公共提取里。
        String desc = n.hasNonNull("error_description") ? n.get("error_description").asText() : null;
        String err = n.hasNonNull("error") ? n.get("error").asText() : null;
        if (hasText(desc) && hasText(err) && !desc.equals(err)) {
            return desc + "（" + err + "）";
        }
        if (hasText(desc)) {
            return desc;
        }
        return err;
    }

    private static boolean hasText(String s) {
        return s != null && !s.isBlank();
    }

    /**
     * 翻页拉全量（{@code page} + {@code limit}）。
     *
     * <p><b>结束条件必须是「本页为空」</b>：Gitea 服务端有硬上限
     * （实测 {@code max_response_items=50}），即便请求 {@code limit=100} 也只回 50。
     * 若用「本页条数 &lt; 请求条数」判断，会把「50 &lt; 100」误读成「已是最后一页」，
     * 于是第 2 页起全部丢失。空页才停则对这一差异免疫。</p>
     *
     * <p>第二道保险：整页与上一页完全相同即停 —— 兜住「服务端忽略分页参数」
     * 导致同一页被反复累加的实现缺陷。</p>
     */
    private List<Map<String, Object>> listAllPaged(String token, String path) {
        int size = Math.max(1, props.getListPageSize());
        int maxPages = Math.max(1, props.getListMaxPages());
        List<Map<String, Object>> all = new ArrayList<>();
        List<Map<String, Object>> prev = null;
        for (int page = 1; page <= maxPages; page++) {
            Map<String, Object> q = new LinkedHashMap<>();
            q.put("page", String.valueOf(page));
            q.put("limit", String.valueOf(size));
            List<Map<String, Object>> chunk = asList(send(token, "GET", path, q, null));
            if (chunk.isEmpty()) {
                return all;
            }
            if (chunk.equals(prev)) {
                log.warn("Gitea 列表翻页疑似无效：第 {} 页与前一页响应完全相同，已提前停止"
                        + "以避免重复累加。path={} size={}", page, path, chunk.size());
                return all;
            }
            all.addAll(chunk);
            prev = chunk;
        }
        log.warn("Gitea 列表翻页达到安全上限仍未取完：path={} maxPages={} size={} got={}；"
                + "结果可能被截断，如需全量请调大 aioa.gitea.list-max-pages",
                path, maxPages, size, all.size());
        return all;
    }

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

    private static String trimSlash(String s) {
        if (s == null) {
            return "";
        }
        String t = s.trim();
        return t.endsWith("/") ? t.substring(0, t.length() - 1) : t;
    }

    private static String hostOf(String url) {
        if (url == null || url.isBlank()) {
            return "";
        }
        try {
            String h = URI.create(url.trim()).getHost();
            return h == null ? "" : h;
        } catch (Exception e) {
            return "";
        }
    }

    private static String enc(String v) {
        return URLEncoder.encode(v == null ? "" : v, StandardCharsets.UTF_8);
    }

    /** 路径段编码：保留 {@code /} 以便传多级路径（如 contents/a/b.txt）。 */
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
