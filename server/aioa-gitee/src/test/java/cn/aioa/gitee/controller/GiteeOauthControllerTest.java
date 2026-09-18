package cn.aioa.gitee.controller;

import cn.aioa.gitee.config.RepoProviderSettings;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 绑定结果页的「非正式站点」告警判定。
 *
 * <p><b>为什么必须单测这一段</b>：成功页只在**真实浏览器授权回调**之后才渲染，
 * 而真实授权需要 Gitea 的登录态（自动化不了）。也就是说这条判据没有任何端到端覆盖，
 * 只能在这里钉住 —— 而它一旦判错，代价是**把成功说成可疑**：
 * 2026-09-18 真机实测，判定写死 {@code gitee.com} ⇒ 真实自建 Gitea（{@code 172.16.8.249:3000}）
 * 被判成桩 ⇒ 用户**绑定成功**的页面上出现「⚠ 本次授权未经过真实 Gitea」。</p>
 */
class GiteeOauthControllerTest {

    /** 只用得到 props，另两个依赖给 null 即可（构造器由 Lombok 生成）。 */
    private GiteeOauthController controller(RepoProviderSettings props) {
        return new GiteeOauthController(null, null, props);
    }

    private RepoProviderSettings props(String authUrl, boolean sandbox) {
        RepoProviderSettings p = mock(RepoProviderSettings.class);
        when(p.getOauthAuthorizeBaseUrl()).thenReturn(authUrl);
        when(p.authorizeHostIsSandbox()).thenReturn(sandbox);
        when(p.providerLabel()).thenReturn("Gitea");
        when(p.sandboxAuthorizeWarning(anyString())).thenReturn("warn");
        return p;
    }

    @Test
    @DisplayName("**真机回归**：真实自建 Gitea 授权成功后，成功页不得出现「未经过真实站点」告警")
    void realGiteaBindPageHasNoWarning() {
        assertNull(controller(props("http://172.16.8.249:3000", false)).nonProdAuthorizeHost(),
                "判成桩就会在**成功**页警告「本次授权未经过真实 Gitea」");
    }

    @Test
    @DisplayName("被指向桩时仍要 fail-loud：成功页必须给出该域名让用户看得见")
    void stubAuthorizeStillWarns() {
        assertEquals("127.0.0.1",
                controller(props("http://127.0.0.1:8090", true)).nonProdAuthorizeHost());
    }

    @Test
    @DisplayName("授权域解析不出主机名时不编造告警（无处可展示，也不该说可疑）")
    void unparsableHostDoesNotWarn() {
        assertNull(controller(props("不是个地址", true)).nonProdAuthorizeHost());
        assertNull(controller(props(null, true)).nonProdAuthorizeHost());
    }

    @Test
    @DisplayName("判据来自设置端口，控制器不再自己比较域名（否则切托管方必漏改）")
    void judgementComesFromSettingsNotTheController() {
        // 同一个「看起来像自建实例」的地址，判定权在设置端：
        // 设置端说不是桩 ⇒ 不告警；说是桩 ⇒ 告警。控制器不得自行改写结论。
        assertNull(controller(props("http://172.16.8.249:3000", false)).nonProdAuthorizeHost());
        assertNotNull(controller(props("http://172.16.8.249:3000", true)).nonProdAuthorizeHost());
    }
}
