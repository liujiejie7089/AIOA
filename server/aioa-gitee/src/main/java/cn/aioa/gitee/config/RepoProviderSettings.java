package cn.aioa.gitee.config;

/**
 * 代码托管平台的**设置端口**（provider-neutral settings port）。
 *
 * <p><b>为什么还需要它，而不只是 {@code RepoProviderClient}</b>：客户端契约解决的是
 * 「怎么调平台接口」，但业务侧还有另一类依赖 ——「平台侧的配置长什么样」：能力开关、
 * 组织归属、Webhook 回调基址与签名密钥、OAuth 回调地址、令牌加密密钥。这些原先散落在
 * 8 个业务类里直接读 {@code GiteeProperties}。一旦把 {@code aioa.repo.provider}
 * 切成 gitea，这些点会**读到 Gitee 段的空值/错值**（例如组织为空、Webhook 基址为空），
 * 而编译期毫无提示 —— 典型的「换完 provider 才发现仓库建到了用户名下」。</p>
 *
 * <p><b>方法名刻意与 {@code GiteeProperties} 的 getter 保持一致</b>：这样各处调用点
 * （{@code props.getOrg()}、{@code props.isEnabled()} …）**一行都不用改**，只需把字段
 * 声明从 {@code GiteeProperties} 换成 {@code RepoProviderSettings}，改动面小、可审计。</p>
 *
 * <p><b>三类设置的来源并不相同</b>，见 {@link RepoProviderSettingsAdapter}：
 * ① 平台协议相关（org/webhook/redirect/oauth/token-enc-key）随 provider 切换；
 * ② 平台运行参数（重试次数/批量/软删是否连带删仓库/同步开关）与托管平台无关，
 * 仍取 {@code aioa.gitee.*} 段；③ OAuth 自检提示文案随 provider 变，但**必须指名
 * 当前 provider 的属性键**，否则用户会去改一个根本不生效的配置项。</p>
 */
public interface RepoProviderSettings {

    // ======================================================================
    // ① 随 provider 切换
    // ======================================================================

    /** 该 provider 的集成总开关。 */
    boolean isEnabled();

    /** 默认组织名（仓库建在它下面）。留空 = 建在绑定用户名下。 */
    String getOrg();

    /** Webhook 回调基址（必须是托管平台**能访问到**的地址）。 */
    String getWebhookBaseUrl();

    /** Webhook 签名密钥。留空 = 每仓库随机生成。 */
    String getWebhookSecret();

    /** OAuth2 回调地址（须与平台侧应用登记完全一致）。 */
    String getRedirectUri();

    /** 用户浏览器的授权页基址。 */
    String getOauthAuthorizeBaseUrl();

    /** 令牌加密密钥（AES）。**切换 provider 会导致既有令牌不可解密，需重新绑定**。 */
    String getTokenEncKey();

    /** 仓库标识的最大长度（Gitea 与 Gitee 的上限不同）。 */
    int getRepoNameMaxLength();

    /**
     * 当前托管方的标识名：{@code gitee} / {@code gitea}（小写）。
     *
     * <p><b>为什么设置端口需要暴露「名字」</b>：绑定记录（{@code gitee_account}）是
     * <b>按托管方归属</b>的身份数据，查询必须按托管方过滤，否则切到 Gitea 后会把
     * Gitee 的 uid / 登录名 / 异平台密文令牌当成自己的用（实测：建项目 500、
     * 成员同步 404）。名字同时是写库时的取值来源，必须由端口统一给出，
     * 不能让各服务各自去读 {@code aioa.repo.provider}。</p>
     */
    String providerName();

    /**
     * 当前托管方的**展示名**（{@code Gitee} / {@code Gitea}），给前端界面文案用。
     *
     * <p>与 {@link #providerName()} 分开是因为两者用途不同：前者是写库/比对用的机器标识
     * （小写、稳定、不可改），后者是给人看的。前端整页文案原先硬编码「Gitee」，
     * 切到 Gitea 后页面写着「我的 Gitee 账号」而实际驱动的是 Gitea，
     * 连「未启用」提示都指向 {@code aioa.gitee.*} —— 用户会去改一个不生效的配置项。</p>
     */
    String providerLabel();

    /**
     * 令牌加密密钥所在的**属性键名**（如 {@code aioa.gitea.token-enc-key}）。
     *
     * <p>用于错误文案：密钥不对时必须告诉用户去改**当前生效**的那个键。
     * 只说 {@code aioa.gitee.token-enc-key} 会让人去改一个在 gitea 下根本不读的配置项。</p>
     */
    String tokenEncKeyProperty();

    /**
     * 该托管方的**配置前缀**（{@code aioa.gitee} / {@code aioa.gitea}）。
     *
     * <p>用于错误文案与前端提示里指名「去哪一段配置」：切到 gitea 后还让人去改
     * {@code aioa.gitee.*} 是误导。与 {@link #providerName()} 同源，不另立常量表。</p>
     */
    String configKeyPrefix();

    // ======================================================================
    // ② 平台运行参数（与托管平台无关，仍取 aioa.gitee.* 段）
    // ======================================================================

    /** 后台同步任务总开关。 */
    boolean isSyncEnabled();

    /** 删除项目时是否连带删除远端仓库。 */
    boolean isPurgeRepoOnDelete();

    /** 任务最大重试次数。 */
    int getMaxAttempts();

    /** 单批领取任务条数。 */
    int getTaskBatchSize();

    /** 绑定成功后回跳的前端页面（平台侧页面，与托管平台无关）。 */
    String getBindReturnUrl();

    // ======================================================================
    // ③ OAuth 自检与提示（文案随 provider，且必须指名正确的属性键）
    // ======================================================================

    /** OAuth 应用是否已配置好（client-id + client-secret 都非空）。 */
    boolean oauthConfigured();

    /** 「集成未启用」的可执行报错文案。 */
    String hintDisabled();

    /** 「OAuth 应用未配置」的可执行报错文案（指名当前 provider 的属性键）。 */
    String hintOauthMissing();

    /** 「OAuth 回调地址未配置」的可执行报错文案。 */
    String hintRedirectMissing();

    /**
     * 授权域不是官方站点时的警示文案。
     *
     * <p>fail-loud 用：把服务端接口指向桩做回归时，用户浏览器也会被带到桩，
     * 于是「绑定成功」实际是桩签发的假身份。必须让调用方看得见。</p>
     *
     * @param authorizeHost 实际授权域主机名
     */
    String sandboxAuthorizeWarning(String authorizeHost);

    /**
     * 配置的授权域是否**不是**该托管方的正式站点（即被指向了桩/代理）。
     *
     * <p><b>判据随托管方而变，调用方不得自己写参照物</b>：
     * Gitee 是公有云 ⇒ 参照物是 {@code gitee.com}；
     * Gitea 是自建实例 ⇒ 参照物是配置里的**本实例网页域**（{@code web-base-url}）。</p>
     *
     * <p><b>为什么必须收在这里</b>：曾经由调用方各自判断，其中一处写死了 {@code gitee.com}，
     * 结果真实自建 Gitea（{@code 172.16.8.249:3000}）被判成桩，
     * **绑定成功页反而警告「本次授权未经过真实 Gitea」**（2026-09-18 真机实测）。
     * 与 {@link #sandboxAuthorizeWarning(String)} 配套：这个方法判定「要不要提示」，
     * 那个方法给出「提示什么」。</p>
     */
    boolean authorizeHostIsSandbox();

    /**
     * 企业初始化时对**访问令牌权限**的要求文案（一整句，含句号）。
     *
     * <p><b>为什么必须随 provider 变</b>：两个平台的令牌权限模型不同 ——
     * Gitee 的 PAT 讲 {@code projects} 这类 scope，Gitea 的个人令牌是「仓库 / 组织 /
     * 用户 / 其他」四个勾选项。把 Gitee 的 scope 名丢给 Gitea 用户，
     * 他会在令牌页上找不到那个选项。</p>
     */
    String tokenRequirementHint();
}
