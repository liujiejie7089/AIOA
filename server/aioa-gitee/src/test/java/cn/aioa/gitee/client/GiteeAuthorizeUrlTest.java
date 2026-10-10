package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.gitee.config.PlatformConfigOverlay;
import cn.aioa.gitee.config.PlatformConfigOverlay.Field;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.config.RepoProviderSettingsAdapter;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 授权 URL 必须带上**生效**的 client-id（回归）。
 *
 * <p><b>缺陷背景（2026-10-10 生产实测）</b>：管理端「仓库配置」页把 client-id 存进了
 * {@code gitee_platform_config}，页面显示 {@code configured=true}；但用户点「绑定 Gitee」
 * 后登录，Gitee 直接回 {@code {"error":"Application does not exist"}}。抓到的授权 URL 是
 * {@code https://gitee.com/oauth/authorize?client_id=&redirect_uri=...} —— {@code client_id} 为空。</p>
 *
 * <p><b>根因</b>：{@link GiteeClient} 当时直接读原始 {@code GiteeProperties} bean（只含环境变量值），
 * 绕过了「管理端覆盖层 → 回落环境变量」的 {@link RepoProviderSettings} 端口。于是
 * 「页面改的是这个值、真正发出去的是另一个值」。修复即把可覆盖字段一律改走端口。</p>
 *
 * <p><b>为什么正负对照都要有</b>：只断言「URL 含 client-id」无法区分「真的修好了」与
 * 「判据本身失效」。负向用例证明「不配就是空」，正向用例证明「配了就不空」——
 * 两者合起来才说明这条断言能红能绿。</p>
 */
class GiteeAuthorizeUrlTest {

    @Test
    @DisplayName("管理端配了 client-id ⇒ 授权 URL 带上它（修复前这里会拿到空 client_id）")
    void authorizeUrlCarriesAdminConfiguredClientId() {
        // 环境变量侧「没有」client-id，模拟生产：凭据只在管理端配置页维护
        GiteeProperties env = new GiteeProperties();
        PlatformConfigOverlay overlay = TestSettings.overlay("gitee", Map.of(
                Field.CLIENT_ID, "eb1dee15deadbeef",
                Field.REDIRECT_URI, "https://mall.egoaicloud.com/aioa/api/v1/gitee/bind/callback",
                Field.OAUTH_AUTHORIZE_BASE_URL, "https://gitee.com",
                Field.SCOPE, "projects hook"));

        GiteeClient client = new GiteeClient(env, TestSettings.giteeWithOverlay(env, overlay), new ObjectMapper());
        String url = client.authorizeUrl("STATE123");

        assertTrue(url.contains("client_id=eb1dee15deadbeef"),
                "授权 URL 必须带上管理端配置的 client-id（否则 Gitee 回 Application does not exist）：" + url);
        assertFalse(url.contains("client_id=&"),
                "client_id 不得为空 —— 这正是线上缺陷的症状：" + url);
        assertTrue(url.contains("redirect_uri=https%3A%2F%2Fmall.egoaicloud.com%2Faioa%2Fapi%2Fv1%2Fgitee%2Fbind%2Fcallback"),
                "回调地址也必须来自生效配置：" + url);
        assertEquals("gitee.com", client.authorizeHost(), "授权域同样走生效配置");
    }

    @Test
    @DisplayName("负向对照：不配 client-id ⇒ URL 里就是 client_id=& （证明上面的判据是有效的）")
    void emptyClientIdIsDetectable() {
        GiteeClient client = new GiteeClient(new GiteeProperties(),
                TestSettings.giteeWithOverlay(new GiteeProperties(), null), new ObjectMapper());
        assertTrue(client.authorizeUrl("S").contains("client_id=&"),
                "没有任何来源提供 client-id 时，URL 必须表现为空 —— 否则正向断言无从判红");
    }

    @Test
    @DisplayName("Gitea 侧同源：授权 URL 也走端口（授权域 = 配置值，client-id = 配置值）")
    void giteaAuthorizeUrlCarriesEffectiveClientId() {
        GiteaProperties env = new GiteaProperties();
        PlatformConfigOverlay overlay = TestSettings.overlay("gitea", Map.of(
                Field.CLIENT_ID, "gitea-admin-id",
                Field.OAUTH_AUTHORIZE_BASE_URL, "http://gitea.internal:3000",
                Field.REDIRECT_URI, "http://127.0.0.1/cb",
                Field.SCOPE, "repo user"));

        RepoProviderSettingsAdapter settings =
                new RepoProviderSettingsAdapter(new GiteeProperties(), env, overlay);
        ReflectionTestUtils.setField(settings, "provider", "gitea");
        GiteaProviderClient client = new GiteaProviderClient(env, settings, new ObjectMapper());

        String url = client.authorizeUrl("S");
        assertTrue(url.startsWith("http://gitea.internal:3000/login/oauth/authorize?"),
                "授权域必须取生效配置（而非环境变量的空值）：" + url);
        assertTrue(url.contains("client_id=gitea-admin-id"), url);
    }

    @Test
    @DisplayName("端口暴露 secret 的**值**（仅供服务端换令牌），且仍受环境变量回落约束")
    void portExposesClientSecretValue() {
        GiteeProperties env = new GiteeProperties();
        env.setClientSecret("env-secret");
        RepoProviderSettings s = TestSettings.giteeWithOverlay(env, null);
        assertEquals("env-secret", s.getClientSecret(),
                "换令牌要用这个值；它必须能经端口取到，否则又回到「绕过端口」的老路");
        assertTrue(s.clientSecretConfigured());
    }
}
