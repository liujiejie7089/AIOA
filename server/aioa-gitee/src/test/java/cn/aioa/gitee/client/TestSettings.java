package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.gitee.config.PlatformConfigOverlay;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.config.RepoProviderSettingsAdapter;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Map;

/**
 * 客户端单测用的 {@link RepoProviderSettings} 构造工具。
 *
 * <p><b>为什么不各测试各写一套桩</b>：{@code GiteeClient} / {@code GiteaProviderClient}
 * 现在都从端口读可覆盖字段，若每个测试用不同的假桩，就再也无法保证「测试里发出去的 URL」
 * 与「生产里发出去的 URL」走同一条决策路径。这里统一走<b>真实适配器</b>
 * （{@link RepoProviderSettingsAdapter}），只把 provider 钉住、按需注入覆盖层。</p>
 */
final class TestSettings {

    private TestSettings() {
    }

    /** provider=gitee，无管理端覆盖：全部回落 aioa.gitee.* 段。 */
    static RepoProviderSettings gitee() {
        GiteeProperties gitee = new GiteeProperties();
        gitee.setClientId("test-gitee-id");
        gitee.setClientSecret("test-gitee-secret");
        gitee.setRedirectUri("http://127.0.0.1/cb");
        gitee.setOauthAuthorizeBaseUrl("https://gitee.com");
        gitee.setScope("projects hook");
        return adapter(gitee, new GiteaProperties(), null, "gitee");
    }

    /** provider=gitea，无管理端覆盖：全部回落 aioa.gitea.* 段。 */
    static RepoProviderSettings gitea() {
        GiteaProperties gitea = new GiteaProperties();
        gitea.setClientId("test-gitea-id");
        gitea.setClientSecret("test-gitea-secret");
        gitea.setRedirectUri("http://127.0.0.1/cb");
        gitea.setOauthAuthorizeBaseUrl("http://127.0.0.1:1");
        gitea.setScope("repo user");
        return adapter(new GiteeProperties(), gitea, null, "gitea");
    }

    /** provider=gitee + 指定的管理端覆盖层（用于验证覆盖值真的进了出站 URL）。 */
    static RepoProviderSettings giteeWithOverlay(GiteeProperties env, PlatformConfigOverlay overlay) {
        return adapter(env, new GiteaProperties(), overlay, "gitee");
    }

    private static RepoProviderSettings adapter(GiteeProperties g,
                                                GiteaProperties t,
                                                PlatformConfigOverlay overlay,
                                                String provider) {
        RepoProviderSettingsAdapter a =
                new RepoProviderSettingsAdapter(g, t, overlay == null ? new PlatformConfigOverlay() : overlay);
        // provider 字段平时由 @Value 注入；单测无 Spring 上下文，用反射钉住。
        ReflectionTestUtils.setField(a, "provider", provider);
        return a;
    }

    /** 构造一个 provider=gitee 的覆盖层。 */
    static PlatformConfigOverlay overlay(String provider, Map<PlatformConfigOverlay.Field, String> values) {
        PlatformConfigOverlay o = new PlatformConfigOverlay();
        o.apply(provider, true, values);
        return o;
    }
}
