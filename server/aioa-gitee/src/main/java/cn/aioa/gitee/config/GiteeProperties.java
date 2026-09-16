package cn.aioa.gitee.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Gitee V5 联动配置（{@code aioa.gitee.*}）。
 *
 * <p><b>为什么 base-url 可配</b>：Gitee 的写操作（建仓 / 配 Webhook / 提交 / 成员）必须持有效凭证，
 * 而凭证由使用者提供。把地址做成配置项，就可以在**没有线上凭证**时指向本地 Gitee V5 桩服务，
 * 用同一条代码路径完成端到端验收 —— 切换真实环境只改配置，不改代码。</p>
 *
 * <p><b>安全纪律</b>：{@code clientSecret} / {@code webhookSecret} / {@code tokenEncKey}
 * 一律从环境变量注入，**不写进仓库**（{@code .env} 已 gitignore）。</p>
 */
@Data
@ConfigurationProperties(prefix = "aioa.gitee")
public class GiteeProperties {

    /** 总开关：关闭时所有 Gitee 接口返回 400 明确提示，不会半死不活地报 NPE。 */
    private boolean enabled = false;

    /** Gitee V5 API 基址（生产 https://gitee.com/api/v5；验收可指向本地桩）。 */
    private String baseUrl = "https://gitee.com/api/v5";

    /** Gitee 网页基址，用于拼授权页与「跳转原仓库」。 */
    private String webBaseUrl = "https://gitee.com";

    /** OAuth2 应用 client_id。 */
    private String clientId = "";

    /** OAuth2 应用 client_secret。 */
    private String clientSecret = "";

    /** OAuth2 回调地址（必须与 Gitee 应用登记的一致，且与发起授权时使用的完全相同）。 */
    private String redirectUri = "";

    /** 授权 scope：必须含 repo（读写仓库与 Webhook）。 */
    private String scope = "user_info projects pull_requests issues notes";

    /**
     * 「Gitee 总组织」login —— 部门团队与项目仓库都建在它下面。
     *
     * <p>为空时退化为建在**绑定用户自己的命名空间**下（便于个人试用）；
     * 生产应配置为组织名，否则部门隔离只能靠命名前缀，仓库会散落在各用户名下。</p>
     */
    private String org = "";

    /**
     * Webhook 回调的公网基址（如 {@code https://aioa.example.com}）。
     *
     * <p>Gitee 只能回调**它自己可访问**的地址，本机 127.0.0.1 无效。留空时按
     * {@code aioa.gitee.base-url} 推导不出的场景给出明确报错，而不是塞一个假地址。</p>
     */
    private String webhookBaseUrl = "";

    /**
     * Webhook 默认密钥：创建 Webhook 时写入 Gitee 的 password，回调时比对。
     *
     * <p>为空时按「每仓库随机生成」处理（更安全，且单仓库泄露不影响其他项目）。</p>
     */
    private String webhookSecret = "";

    /** 令牌加密密钥（AES-256 需要 32 字节；不足则用 SHA-256 派生）。生产必须覆盖。 */
    private String tokenEncKey = "aioa-dev-gitee-token-key-please-change";

    /**
     * 授权完成后的前端回跳地址（管理端 SPA）。
     *
     * <p>回调接口是**后端地址**（必须与 Gitee 应用登记一致），处理完只能返回 HTML。
     * 该值决定这段 HTML 把用户送回哪里 —— 留空则只显示「绑定成功，可关闭本页」。</p>
     */
    private String bindReturnUrl = "";


    /** 仓库名长度上限（Gitee path 上限 191，留出命名前缀空间）。 */
    private int repoNameMaxLength = 100;

    /** HTTP 超时（秒）。 */
    private int httpTimeoutSeconds = 30;

    /** 单次任务重试上限。 */
    private int maxAttempts = 5;

    /** 异步任务每次拉取条数。 */
    private int taskBatchSize = 5;

    /** 定时校准 cron（默认每小时 17 分，避开整点）。 */
    private String syncCron = "0 17 * * * *";

    /** 定时校准开关。 */
    private boolean syncEnabled = true;

    /** 是否在项目软删时默认删除 Gitee 仓库（默认否 —— 误删代码不可逆）。 */
    private boolean purgeRepoOnDelete = false;

    /** 对 Gitee 的请求间隔（毫秒）：避免触发 403 Rate Limit Exceeded（实测存在）。 */
    private long minRequestIntervalMs = 120;
}
