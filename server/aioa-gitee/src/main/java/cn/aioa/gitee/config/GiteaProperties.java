package cn.aioa.gitee.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Gitea 联动配置（{@code aioa.gitea.*}）。
 *
 * <p><b>为什么与 {@link GiteeProperties} 完全分开而不是复用一套键</b>：两家的
 * 差异不只是「地址不同」—— OAuth 端点路径、scope 词表、Webhook 校验算法、
 * 分页参数名全都不同（见 {@code RepoProviderClient} 类注释的硬分歧点清单）。
 * 共用一套键会诱导「改个 URL 就算换完了」的错误预期，而真正咬人的是那五处差异。</p>
 *
 * <p><b>安全纪律</b>：{@code clientSecret} / {@code webhookSecret} / {@code tokenEncKey}
 * 一律从环境变量注入，<b>不写进仓库</b>（{@code .env} 已 gitignore）。</p>
 */
@Data
@ConfigurationProperties(prefix = "aioa.gitea")
public class GiteaProperties {

    /** 总开关：关闭时所有 Gitea 接口返回明确错误，不会半死不活地报 NPE。 */
    private boolean enabled = false;

    /**
     * Gitea API 基址，<b>必须带 {@code /api/v1}</b>。
     *
     * <p>例：{@code http://172.16.8.249:3000/api/v1}。注意 Gitea 的 OAuth 端点
     * <b>不在</b> {@code /api/v1} 下（见 {@link #oauthTokenUrl()} 的说明）。</p>
     */
    private String baseUrl = "";

    /** Gitea 网页基址（拼「跳转原仓库」链接、以及 OAuth 端点用）。例：{@code http://172.16.8.249:3000}。 */
    private String webBaseUrl = "";

    /**
     * 用户浏览器授权页基址（授权跳转 = {@code {此值}/login/oauth/authorize}）。
     *
     * <p>与 {@link GiteeProperties#getOauthAuthorizeBaseUrl()} 同理，必须与服务端
     * API 基址分开：服务端可以被指向桩做回归，但用户的浏览器必须到达真实的
     * Gitea —— 否则用户会被桩直接签发假身份并显示「绑定成功」。</p>
     */
    private String oauthAuthorizeBaseUrl = "";

    /** OAuth2 应用 client_id（在 Gitea「设置 → 应用」创建）。 */
    private String clientId = "";

    /** OAuth2 应用 client_secret。 */
    private String clientSecret = "";

    /** OAuth2 回调地址（须与 Gitea 应用登记的一致，且与发起授权时完全相同）。 */
    private String redirectUri = "";

    /**
     * 授权 scope（空格分隔）。
     *
     * <p><b>与 Gitee 的词表没有交集</b>：Gitea 用 {@code repo}（仓库读写）、
     * {@code read:organization}、{@code notification}、{@code issue} 等；
     * Gitee 用 {@code projects} / {@code hook}。照抄 Gitee 的 scope 不会报错，
     * 只会导致「授权成功但权限不足」——建仓被拒、Webhook 建不上。</p>
     *
     * <p>另：Gitea 返回的是<b>应用登记时勾选的全部权限</b>，并不严格按 URL 上的
     * {@code scope} 收窄（实测：申请 6 项、返回 11 项）。因此<b>应用登记页勾选的权限
     * 同样是有效范围</b>，两处都要对。</p>
     */
    private String scope = "repo read:organization notification issue";

    /** 「Gitea 总组织」名：部门项目仓库都建在它下面；留空则建在绑定用户自己的命名空间下。 */
    private String org = "";

    /**
     * Webhook 回调的公网基址（如 {@code https://aioa.example.com}）。
     *
     * <p>Gitea 只能回调<b>它自己能访问到</b>的地址 —— 本机 {@code 127.0.0.1}、
     * 内网 {@code 172.16.x.x} 从 Gitea 视角都不可达。留空时给出明确报错，
     * 而不是塞一个假地址让 Webhook 静默地永不触发。</p>
     */
    private String webhookBaseUrl = "";

    /**
     * Webhook 签名密钥（写入 {@code config.secret}，回调时用于 HMAC-SHA256 校验）。
     *
     * <p>为空时按「每仓库随机生成」处理。</p>
     */
    private String webhookSecret = "";

    /** 令牌加密密钥（AES-256 需要 32 字节；不足则用 SHA-256 派生）。生产必须覆盖。 */
    private String tokenEncKey = "aioa-dev-gitea-token-key-please-change";

    /**
     * 仓库标识的取值来源（Gitea 只有一个 {@code name} 兼作 URL 片段，
     * 而 Gitee 的 {@code name}/{@code path} 是两个字段）。
     *
     * <ul>
     *   <li>{@code AUTO}（默认）：优先用 {@code path}（保证 URL 是 ASCII），
     *       {@code path} 为空则回落 {@code name}；</li>
     *   <li>{@code NAME}：总是用 {@code name}（中文会进 URL）；</li>
     *   <li>{@code PATH}：总是用 {@code path}（{@code path} 为空时报错，不静默回落）。</li>
     * </ul>
     *
     * <p>这是 Gitee→Gitea 迁移中<b>唯一带破坏性的口径</b>，因此做成显式配置项而不是
     * 埋在选择逻辑里 —— 让「中文展示名要不要保留」这件事在配置里可见。</p>
     */
    private RepoNameSource repoNameSource = RepoNameSource.AUTO;

    /** 仓库标识取值来源枚举。 */
    public enum RepoNameSource {
        /** 优先 path，为空回落 name（默认）。 */
        AUTO,
        /** 总是用 name。 */
        NAME,
        /** 总是用 path，为空则报错。 */
        PATH
    }

    /** 仓库名长度上限。 */
    private int repoNameMaxLength = 100;

    /** HTTP 超时（秒）。 */
    private int httpTimeoutSeconds = 30;

    /** 对 Gitea 的请求间隔（毫秒），避免把自建实例打爆。 */
    private long minRequestIntervalMs = 120;

    /** 列表分页：单页条数（Gitea 服务端上限 {@code max_response_items} 默认 50，请求更大也只回 50）。 */
    private int listPageSize = 100;

    /** 列表分页：最大翻页数（安全上限，防止超大仓库把请求数放大到不可控）。 */
    private int listMaxPages = 20;

    // ======================================================================
    // TLS（私有化部署几乎必然遇到）
    // ======================================================================

    /**
     * 是否跳过 TLS 证书校验（自签证书场景的最后手段）。
     *
     * <p><b>默认 false</b>。开启后本客户端<b>不再验证服务端身份</b>，任何能连上该
     * 地址的中间人都可冒充 —— 因此启动时会打 WARN，且该值会出现在自检日志里，
     * 便于审计时发现「生产环境为什么关了校验」。</p>
     *
     * <p>优先用 {@link #trustStore} 把自签 CA 导入信任库；本开关只用于确实无法
     * 取得 CA 的场景。</p>
     */
    private boolean insecureSkipVerify = false;

    /** 自定义信任库路径（JKS/PKCS12）。为空则用 JVM 默认信任库。 */
    private String trustStore = "";

    /** 信任库口令。 */
    private String trustStorePassword = "";

    /** 信任库类型（{@code JKS} / {@code PKCS12}）。 */
    private String trustStoreType = "PKCS12";

    // ======================================================================
    // 派生地址（避免调用方各自拼字符串拼错）
    // ======================================================================

    /** 换令牌端点：{@code POST {web}/login/oauth/access_token}（**不在 /api/v1 下**）。 */
    public String oauthTokenUrl() {
        return trimSlash(webBaseUrl) + "/login/oauth/access_token";
    }

    /** 授权页端点：{@code {authorizeBase}/login/oauth/authorize}。 */
    public String oauthAuthorizeUrl() {
        return trimSlash(oauthAuthorizeBaseUrl) + "/login/oauth/authorize";
    }

    private static String trimSlash(String s) {
        if (s == null) {
            return "";
        }
        String t = s.trim();
        return t.endsWith("/") ? t.substring(0, t.length() - 1) : t;
    }
}
