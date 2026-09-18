package cn.aioa.gitee.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 设置端口的分流测试。
 *
 * <p><b>为什么必须锁死到「具体取值」而不是「不为空」</b>：这类 bug 的表现恰恰是
 * 「不报错、值不对」——把 Gitee 段的值拿去给 Gitea 用，编译能过、启动能起，
 * 直到仓库建到了错误的组织下才被发现。所以断言必须钉住「哪个段的值」。</p>
 */
class RepoProviderSettingsTest {

    private RepoProviderSettingsAdapter adapter(String provider) {
        GiteeProperties gitee = new GiteeProperties();
        gitee.setEnabled(true);
        gitee.setOrg("gitee-org");
        gitee.setWebhookBaseUrl("https://gitee-hook.example.com");
        gitee.setWebhookSecret("gitee-secret");
        gitee.setRedirectUri("https://gitee.example.com/cb");
        gitee.setOauthAuthorizeBaseUrl("https://gitee.com");
        gitee.setClientId("gitee-id");
        gitee.setClientSecret("gitee-secret-value");
        gitee.setTokenEncKey("gitee-enc-key");
        gitee.setRepoNameMaxLength(100);
        // 平台运行参数（Gitea 段没有这些键，应始终取 Gitee 段）
        gitee.setSyncEnabled(false);
        gitee.setPurgeRepoOnDelete(true);
        gitee.setMaxAttempts(7);
        gitee.setTaskBatchSize(9);
        gitee.setBindReturnUrl("https://web.example.com/back");

        GiteaProperties gitea = new GiteaProperties();
        gitea.setEnabled(true);
        gitea.setOrg("gitea-org");
        gitea.setWebhookBaseUrl("https://gitea-hook.example.com");
        gitea.setWebhookSecret("gitea-secret");
        gitea.setRedirectUri("https://gitea.example.com/cb");
        gitea.setOauthAuthorizeBaseUrl("http://172.16.8.249:3000");
        gitea.setClientId("gitea-id");
        gitea.setClientSecret("gitea-secret-value");
        gitea.setTokenEncKey("gitea-enc-key");
        gitea.setRepoNameMaxLength(50);

        RepoProviderSettingsAdapter a = new RepoProviderSettingsAdapter(gitee, gitea);
        ReflectionTestUtils.setField(a, "provider", provider);
        return a;
    }

    @Test
    @DisplayName("provider=gitee：平台协议类设置全部取 aioa.gitee 段")
    void giteeTakesGiteeSegment() {
        RepoProviderSettings s = adapter("gitee");
        assertEquals("gitee-org", s.getOrg());
        assertEquals("https://gitee-hook.example.com", s.getWebhookBaseUrl());
        assertEquals("gitee-secret", s.getWebhookSecret());
        assertEquals("https://gitee.example.com/cb", s.getRedirectUri());
        assertEquals("https://gitee.com", s.getOauthAuthorizeBaseUrl());
        assertEquals("gitee-enc-key", s.getTokenEncKey());
        assertEquals(100, s.getRepoNameMaxLength());
        assertTrue(s.oauthConfigured());
    }

    @Test
    @DisplayName("provider=gitea：平台协议类设置全部取 aioa.gitea 段（这是本次改造的核心）")
    void giteaTakesGiteaSegment() {
        RepoProviderSettings s = adapter("gitea");
        assertEquals("gitea-org", s.getOrg());
        assertEquals("https://gitea-hook.example.com", s.getWebhookBaseUrl());
        assertEquals("gitea-secret", s.getWebhookSecret());
        assertEquals("https://gitea.example.com/cb", s.getRedirectUri());
        assertEquals("http://172.16.8.249:3000", s.getOauthAuthorizeBaseUrl());
        assertEquals("gitea-enc-key", s.getTokenEncKey());
        assertEquals(50, s.getRepoNameMaxLength());
        assertTrue(s.oauthConfigured());
    }

    @Test
    @DisplayName("provider 大小写/空白容错：GITEA 等同 gitea")
    void providerIsCaseInsensitive() {
        assertEquals("gitea-org", adapter("GITEA").getOrg());
        assertEquals("gitea-org", adapter("  Gitea  ").getOrg());
    }

    @Test
    @DisplayName("平台运行参数与托管平台无关：切到 gitea 也必须仍取 aioa.gitee 段")
    void operationalSettingsDoNotFlipWithProvider() {
        RepoProviderSettings gitea = adapter("gitea");
        assertFalse(gitea.isSyncEnabled(), "sync-enabled 应取 gitee 段（false）");
        assertTrue(gitea.isPurgeRepoOnDelete(), "purge-repo-on-delete 应取 gitee 段（true）");
        assertEquals(7, gitea.getMaxAttempts());
        assertEquals(9, gitea.getTaskBatchSize());
        assertEquals("https://web.example.com/back", gitea.getBindReturnUrl());
    }

    @Test
    @DisplayName("报错文案必须指名当前 provider 的属性键（否则用户去改一个不生效的配置）")
    void hintsNameTheActiveProviderKeys() {
        RepoProviderSettings gitee = adapter("gitee");
        assertTrue(gitee.hintDisabled().contains("aioa.gitee.enabled"), gitee.hintDisabled());
        assertTrue(gitee.hintOauthMissing().contains("aioa.gitee.client-id"), gitee.hintOauthMissing());
        assertTrue(gitee.hintRedirectMissing().contains("aioa.gitee.redirect-uri"), gitee.hintRedirectMissing());

        RepoProviderSettings gitea = adapter("gitea");
        assertTrue(gitea.hintDisabled().contains("aioa.gitea.enabled"), gitea.hintDisabled());
        assertTrue(gitea.hintOauthMissing().contains("aioa.gitea.client-id"), gitea.hintOauthMissing());
        assertTrue(gitea.hintRedirectMissing().contains("aioa.gitea.redirect-uri"), gitea.hintRedirectMissing());
        // 不能出现「gitea 报错却让用户去改 gitee 键」这种误指
        assertFalse(gitea.hintOauthMissing().contains("aioa.gitee."), gitea.hintOauthMissing());
    }

    @Test
    @DisplayName("授权域警示文案随 provider 变，且给出正确的环境变量名")
    void sandboxWarningNamesTheRightEnvVar() {
        assertTrue(adapter("gitee").sandboxAuthorizeWarning("127.0.0.1:8090")
                .contains("AIOA_GITEE_OAUTH_AUTHORIZE_URL"));
        assertTrue(adapter("gitea").sandboxAuthorizeWarning("127.0.0.1:8090")
                .contains("AIOA_GITEA_OAUTH_AUTHORIZE_URL"));
    }

    @Test
    @DisplayName("Gitea 段令牌密钥为空时回落 Gitee 段（避免全部令牌无法解密）")
    void tokenEncKeyFallsBackWhenBlank() {
        GiteeProperties gitee = new GiteeProperties();
        gitee.setTokenEncKey("gitee-enc-key");
        GiteaProperties gitea = new GiteaProperties();
        gitea.setTokenEncKey("   ");
        RepoProviderSettingsAdapter a = new RepoProviderSettingsAdapter(gitee, gitea);
        ReflectionTestUtils.setField(a, "provider", "gitea");
        assertEquals("gitee-enc-key", a.getTokenEncKey());
    }

    @Test
    @DisplayName("OAuth 未配置时 oauthConfigured=false（client-id 或 secret 任一为空）")
    void oauthConfiguredNeedsBothFields() {
        GiteeProperties gitee = new GiteeProperties();
        gitee.setClientId("id-only");
        RepoProviderSettingsAdapter a = new RepoProviderSettingsAdapter(gitee, new GiteaProperties());
        ReflectionTestUtils.setField(a, "provider", "gitee");
        assertFalse(a.oauthConfigured());
    }

    @Test
    @DisplayName("providerName 必须与条件装配同源：gitee/gitea，且大小写容错")
    void providerNameMatchesActiveProvider() {
        assertEquals("gitee", adapter("gitee").providerName());
        assertEquals("gitea", adapter("gitea").providerName());
        assertEquals("gitea", adapter("GITEA").providerName());
        assertEquals("gitee", adapter(null).providerName(), "未配置时默认 gitee");
    }

    @Test
    @DisplayName("tokenEncKeyProperty 指向当前生效的密钥键（说错会把排查引到错误配置）")
    void tokenEncKeyPropertyNamesTheActiveKey() {
        assertEquals("aioa.gitee.token-enc-key", adapter("gitee").tokenEncKeyProperty());
        assertEquals("aioa.gitea.token-enc-key", adapter("gitea").tokenEncKeyProperty());
    }

    @Test
    @DisplayName("providerLabel 是界面文案的唯一来源：切 gitea 后页面不能再自称 Gitee")
    void providerLabelIsDisplayReady() {
        assertEquals("Gitee", adapter("gitee").providerLabel());
        assertEquals("Gitea", adapter("gitea").providerLabel());
        assertEquals("Gitea", adapter("GITEA").providerLabel(), "大小写容错后展示名也必须正确");
        assertEquals("Gitee", adapter(null).providerLabel(), "未配置时默认 Gitee");
    }

    @Test
    @DisplayName("令牌权限要求随 provider 变：Gitee 讲 scope 名，Gitea 讲勾选项")
    void tokenRequirementHintMatchesTheProvider() {
        String gitee = adapter("gitee").tokenRequirementHint();
        assertTrue(gitee.contains("projects"), gitee);
        String gitea = adapter("gitea").tokenRequirementHint();
        // Gitea 的个人令牌没有 projects 这个 scope，照抄会让用户找不到该选项
        assertFalse(gitea.contains("projects"), gitea);
        assertTrue(gitea.contains("组织"), gitea);
    }

    @Test
    @DisplayName("configKeyPrefix 与 providerName 同源：错误文案指名的配置段必须就是实际读的那一段")
    void configKeyPrefixMatchesProvider() {
        RepoProviderSettings gitee = adapter("gitee");
        assertEquals("aioa.gitee", gitee.configKeyPrefix());
        assertTrue(gitee.tokenEncKeyProperty().startsWith(gitee.configKeyPrefix()));
        RepoProviderSettings gitea = adapter("gitea");
        assertEquals("aioa.gitea", gitea.configKeyPrefix());
        assertTrue(gitea.tokenEncKeyProperty().startsWith(gitea.configKeyPrefix()));
    }

    // ==================================================================
    // 授权域「是不是正式站点」的判定 —— 绑定成功页的 fail-loud 提示靠它
    // ==================================================================

    /** 把适配器里的两段属性都放出来改，便于构造「授权域 ≠ 本实例域」等组合。 */
    private RepoProviderSettings withUrls(String provider, String authUrl, String webUrl) {
        RepoProviderSettingsAdapter a = adapter(provider);
        GiteeProperties g = (GiteeProperties) ReflectionTestUtils.getField(a, "gitee");
        GiteaProperties t = (GiteaProperties) ReflectionTestUtils.getField(a, "gitea");
        g.setOauthAuthorizeBaseUrl(authUrl);
        t.setOauthAuthorizeBaseUrl(authUrl);
        g.setWebBaseUrl(webUrl);
        t.setWebBaseUrl(webUrl);
        return a;
    }

    @Test
    @DisplayName("**真机回归**：自建 Gitea 的真实站点不得被判成「桩」（判错会让成功页反向告警）")
    void realSelfHostedGiteaIsNotSandbox() {
        // 2026-09-18 实测：授权域与 web-base-url 同为 172.16.8.249:3000，
        // 而判定逻辑写死参照 gitee.com ⇒ 真实站点被判成桩，
        // 绑定**成功**页反而显示「⚠ 本次授权未经过真实 Gitea」。
        RepoProviderSettings s = withUrls("gitea", "http://172.16.8.249:3000",
                "http://172.16.8.249:3000");
        assertFalse(s.authorizeHostIsSandbox(),
                "自建 Gitea 的真实实例就是正式站点，不能判成桩");
    }

    @Test
    @DisplayName("Gitea 被指向桩（授权域与本实例域不一致）时必须判成可疑")
    void giteaStubIsSandbox() {
        RepoProviderSettings s = withUrls("gitea", "http://127.0.0.1:8090",
                "http://172.16.8.249:3000");
        assertTrue(s.authorizeHostIsSandbox());
    }

    @Test
    @DisplayName("Gitea 缺 web-base-url 时按「说不清就当可疑」处理，而不是默认安全")
    void giteaMissingWebBaseIsSandbox() {
        RepoProviderSettings s = withUrls("gitea", "http://172.16.8.249:3000", "");
        assertTrue(s.authorizeHostIsSandbox(), "参照物缺失时不能默认判成正式站点");
    }

    @Test
    @DisplayName("Gitee 侧语义不变：公有云域名不算桩，其余算桩")
    void giteeKeepsPublicCloudSemantics() {
        assertFalse(withUrls("gitee", "https://gitee.com", "https://gitee.com")
                .authorizeHostIsSandbox());
        assertFalse(withUrls("gitee", "https://www.gitee.com", "https://gitee.com")
                .authorizeHostIsSandbox(), "www 前缀同属正式站点");
        assertTrue(withUrls("gitee", "http://127.0.0.1:8090", "https://gitee.com")
                .authorizeHostIsSandbox());
    }
}
