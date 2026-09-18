package cn.aioa.gitee.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * {@link RepoProviderSettings} 的适配器：按 {@code aioa.repo.provider} 把中性访问器
 * 落到 {@code aioa.gitee.*} 或 {@code aioa.gitea.*} 段。
 *
 * <p><b>为什么要有这一层，而不是让业务类自己判断 provider</b>：判断散落 8 处 = 8 个
 * 漏判风险；集中一处后，新增 provider 只需改这里。业务类只认端口，不知道 provider 是谁。</p>
 *
 * <p><b>三类设置的取数规则</b>：</p>
 * <ol>
 *   <li><b>平台协议相关</b>（org / webhook-base-url / webhook-secret / redirect-uri /
 *       oauth-authorize-base-url / token-enc-key / repo-name-max-length）——
 *       跟随当前 provider。这是本次改造的核心：这些值在两个平台之间**语义不同**，
 *       拿去用错的那一段不会报错，只会默默建错组织、挂错回调地址。</li>
 *   <li><b>平台运行参数</b>（sync-enabled / purge-repo-on-delete / max-attempts /
 *       task-batch-size / bind-return-url）——与托管平台无关，两个平台段里也只有
 *       Gitee 段有（Gitea 段未重复定义）。**仍取 {@code aioa.gitee.*}**，避免出现
 *       「切了 provider 后台任务批量突然变默认值」这种无谓的行为漂移；
 *       需要按 provider 分别调时再补 Gitea 段即可。</li>
 *   <li><b>OAuth 自检提示</b>——文案跟随 provider，且必须**指名当前 provider 的属性键**。
 *       让用户去改一个当前不生效的配置项，比不给提示更糟。</li>
 * </ol>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RepoProviderSettingsAdapter implements RepoProviderSettings {

    /** 与条件装配（{@code @ConditionalOnProperty}）用的同一属性，两侧口径必须一致。 */
    public static final String PROPERTY = "aioa.repo.provider";

    private final GiteeProperties gitee;
    private final GiteaProperties gitea;

    @Value("${" + PROPERTY + ":gitee}")
    private String provider;

    /** 当前是否选中 Gitea。大小写不敏感，容忍环境变量里的手误大小写。 */
    private boolean giteaActive() {
        return "gitea".equalsIgnoreCase(provider == null ? "" : provider.trim());
    }

    // ======================================================================
    // ① 随 provider 切换
    // ======================================================================

    @Override
    public boolean isEnabled() {
        return giteaActive() ? gitea.isEnabled() : gitee.isEnabled();
    }

    @Override
    public String getOrg() {
        return giteaActive() ? blankToEmpty(gitea.getOrg()) : blankToEmpty(gitee.getOrg());
    }

    @Override
    public String getWebhookBaseUrl() {
        return giteaActive() ? blankToEmpty(gitea.getWebhookBaseUrl()) : blankToEmpty(gitee.getWebhookBaseUrl());
    }

    @Override
    public String getWebhookSecret() {
        return giteaActive() ? blankToEmpty(gitea.getWebhookSecret()) : blankToEmpty(gitee.getWebhookSecret());
    }

    @Override
    public String getRedirectUri() {
        return giteaActive() ? blankToEmpty(gitea.getRedirectUri()) : blankToEmpty(gitee.getRedirectUri());
    }

    @Override
    public String getOauthAuthorizeBaseUrl() {
        return giteaActive()
                ? blankToEmpty(gitea.getOauthAuthorizeBaseUrl())
                : blankToEmpty(gitee.getOauthAuthorizeBaseUrl());
    }

    /**
     * 令牌加密密钥。
     *
     * <p><b>切换 provider 会让既有令牌不可解密</b>（两段各有一个不同的默认密钥）。
     * 这是有意的：令牌本就是按平台签发的，跨平台迁移没有意义；但必须让运维知道
     * 「切了 provider 后老绑定要重新授权」，所以这里在首次取用时打一条 INFO。</p>
     */
    @Override
    public String getTokenEncKey() {
        if (!giteaActive()) {
            return gitee.getTokenEncKey();
        }
        String k = gitea.getTokenEncKey();
        if (!StringUtils.hasText(k)) {
            // Gitea 段没配就回落，避免「provider 切了但密钥空」导致所有令牌都无法解密
            return gitee.getTokenEncKey();
        }
        return k;
    }

    @Override
    public int getRepoNameMaxLength() {
        return giteaActive() ? gitea.getRepoNameMaxLength() : gitee.getRepoNameMaxLength();
    }

    /** 当前托管方标识名（小写）。绑定记录按它归属，必须与条件装配口径一致。 */
    @Override
    public String providerName() {
        return giteaActive() ? "gitea" : "gitee";
    }

    /** 令牌密钥的属性键名，按当前 provider 给出（错误文案要用它）。 */
    @Override
    public String tokenEncKeyProperty() {
        return giteaActive() ? "aioa.gitea.token-enc-key" : "aioa.gitee.token-enc-key";
    }

    /**
     * 托管方展示名，给界面文案用。
     *
     * <p>之所以在后端给而不是让前端把 {@code providerName()} 首字母大写：展示名与
     * 写库标识的取值口径必须同源。前端自己拼一遍，将来加第三个托管方就会又多一处漏改。</p>
     */
    @Override
    public String providerLabel() {
        return giteaActive() ? "Gitea" : "Gitee";
    }

    /** 配置前缀由 provider 标识派生，保证「说哪一段配置」与「实际读哪一段」永远一致。 */
    @Override
    public String configKeyPrefix() {
        return "aioa." + providerName();
    }

    // ======================================================================
    // ② 平台运行参数（与托管平台无关，仍取 aioa.gitee.* 段）
    // ======================================================================

    @Override
    public boolean isSyncEnabled() {
        return gitee.isSyncEnabled();
    }

    @Override
    public boolean isPurgeRepoOnDelete() {
        return gitee.isPurgeRepoOnDelete();
    }

    @Override
    public int getMaxAttempts() {
        return gitee.getMaxAttempts();
    }

    @Override
    public int getTaskBatchSize() {
        return gitee.getTaskBatchSize();
    }

    @Override
    public String getBindReturnUrl() {
        return blankToEmpty(gitee.getBindReturnUrl());
    }

    // ======================================================================
    // ③ OAuth 自检与提示
    // ======================================================================

    @Override
    public boolean oauthConfigured() {
        return StringUtils.hasText(clientId()) && StringUtils.hasText(clientSecret());
    }

    @Override
    public String hintDisabled() {
        return giteaActive()
                ? "Gitea 集成未启用（aioa.gitea.enabled=false）"
                : "Gitee 集成未启用（aioa.gitee.enabled=false）";
    }

    @Override
    public String hintOauthMissing() {
        return giteaActive()
                ? "Gitea OAuth 应用未配置（缺 aioa.gitea.client-id / client-secret）"
                : "Gitee OAuth 应用未配置（缺 aioa.gitee.client-id / client-secret）";
    }

    @Override
    public String hintRedirectMissing() {
        return giteaActive()
                ? "Gitea OAuth 回调地址未配置（aioa.gitea.redirect-uri）"
                : "Gitee OAuth 回调地址未配置（aioa.gitee.redirect-uri）";
    }

    @Override
    public String sandboxAuthorizeWarning(String authorizeHost) {
        if (giteaActive()) {
            return "当前授权域为 " + authorizeHost
                    + "，本次授权不会跳转到你预期的 Gitea 站点。"
                    + "如需真实授权，请将 aioa.gitea.oauth-authorize-base-url"
                    + "（环境变量 AIOA_GITEA_OAUTH_AUTHORIZE_URL）配置为 Gitea 站点地址后重试。";
        }
        return "当前授权域为 " + authorizeHost
                + "（非 gitee.com），本次授权不会跳转到真实 Gitee。"
                + "如需真实授权，请将 aioa.gitee.oauth-authorize-base-url"
                + "（环境变量 AIOA_GITEE_OAUTH_AUTHORIZE_URL）配置为 https://gitee.com 后重试。";
    }

    /**
     * 令牌权限要求的整句文案（企业初始化对话框用）。
     *
     * <p>写成「整句」而不是「scope 名片段」：两个平台的权限模型不同，
     * 句子结构也就不同（Gitee 是 scope 名，Gitea 是勾选项），
     * 让前端拼句子会把语法责任摊到两边。</p>
     */
    @Override
    public String tokenRequirementHint() {
        return giteaActive()
                ? "令牌需具备「仓库」与「组织」的读写权限，且账号须为目标组织成员。"
                : "令牌需具备 projects 权限，且账号须为目标组织成员。";
    }

    // ======================================================================
    // 内部
    // ======================================================================

    private String clientId() {
        return giteaActive() ? gitea.getClientId() : gitee.getClientId();
    }

    private String clientSecret() {
        return giteaActive() ? gitea.getClientSecret() : gitee.getClientSecret();
    }

    /** 统一用空串而不是 null，避免调用方到处判 null。 */
    private static String blankToEmpty(String s) {
        return s == null ? "" : s;
    }

    /**
     * 配置的授权域是否**不是**该托管方的正式站点。
     *
     * <p><b>判据必须随托管方变，不能写死参照物</b>：Gitee 是公有云，参照物是写死的
     * {@code gitee.com}；而 Gitea 是**自建实例**，根本没有「官方域名」，
     * 参照物只能是配置里的**本实例网页域**（{@code web-base-url}）。</p>
     *
     * <p><b>写错参照物的后果（2026-09-18 真机实测）</b>：判定逻辑写死 {@code gitee.com}
     * 时，真实的 Gitea 站点（如 {@code 172.16.8.249:3000}）会被判成「桩」——
     * 于是**绑定成功页反过来警告「⚠ 本次授权未经过真实 Gitea」**，把正常结果说成可疑结果。
     * 这类「反向误报」比不报更伤：用户会以为绑定是假的。</p>
     */
    @Override
    public boolean authorizeHostIsSandbox() {
        String auth = hostOf(getOauthAuthorizeBaseUrl());
        if (auth.isEmpty()) {
            // 说不清就当可疑，让上层显式暴露，而不是默认安全（与 client 侧同口径）
            return true;
        }
        if (giteaActive()) {
            String real = hostOf(gitea.getWebBaseUrl());
            return real.isEmpty() || !auth.equalsIgnoreCase(real);
        }
        return !("gitee.com".equalsIgnoreCase(auth) || "www.gitee.com".equalsIgnoreCase(auth));
    }

    /** 取 URL 的主机名；解析不了返回空串（不抛，让调用方按「说不清」处理）。 */
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
}
