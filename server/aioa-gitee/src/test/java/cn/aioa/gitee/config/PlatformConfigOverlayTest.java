package cn.aioa.gitee.config;

import cn.aioa.gitee.config.PlatformConfigOverlay.Field;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 平台参数覆盖层的语义测试。
 *
 * <p><b>为什么这三条语义必须被测试钉死</b>：它们全都是「看不出错、但值不对」的类型，
 * 且都曾以别的形式踩过：</p>
 * <ul>
 *   <li><b>逐字段</b>：若改成「有行就整体覆盖」，一次「只填了组织」的保存会把环境变量里的
 *       Client Secret 静默遮蔽 —— 用户看不见这次丢失，只会在某天发现授权失败。</li>
 *   <li><b>空串是有效值</b>：若把空串当「无覆盖」，用户就永远清不掉一个环境变量里存在的
 *       Webhook 基址（表现为「我清空了，页面刷新又回来了」）。</li>
 *   <li><b>provider 隔离</b>：若不做归属校验，表里存的 gitee 组织会被拿去当 gitea 的组织用，
 *       症状是仓库建到了错误的地方。</li>
 * </ul>
 */
class PlatformConfigOverlayTest {

    /** 造一个 env 值明确的适配器（Gitee 段），provider=gitee。 */
    private RepoProviderSettingsAdapter adapter(PlatformConfigOverlay overlay) {
        GiteeProperties gitee = new GiteeProperties();
        gitee.setEnabled(true);
        gitee.setOrg("env-org");
        gitee.setWebhookBaseUrl("https://env-hook.example.com");
        gitee.setClientId("env-id");
        gitee.setClientSecret("env-secret");
        RepoProviderSettingsAdapter a =
                new RepoProviderSettingsAdapter(gitee, new GiteaProperties(), overlay);
        ReflectionTestUtils.setField(a, "provider", "gitee");
        return a;
    }

    private static Map<Field, String> map(Object... kv) {
        Map<Field, String> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((Field) kv[i], (String) kv[i + 1]);
        }
        return m;
    }

    @Test
    @DisplayName("无覆盖：全部回落环境变量（空表 = 改造前的行为，零回归）")
    void fallsBackToEnvWhenEmpty() {
        RepoProviderSettings s = adapter(new PlatformConfigOverlay());
        assertEquals("env-org", s.getOrg());
        assertEquals("https://env-hook.example.com", s.getWebhookBaseUrl());
        assertEquals("env-id", s.getClientId());
        assertTrue(s.clientSecretConfigured(), "环境变量的 Secret 应被视为已配置");
        assertTrue(s.isEnabled());
    }

    @Test
    @DisplayName("逐字段覆盖：只覆盖 org，其它字段仍取环境变量（不得整体遮蔽）")
    void overridesOnlyTheGivenField() {
        PlatformConfigOverlay ov = new PlatformConfigOverlay();
        ov.apply("gitee", true, map(Field.ORG, "admin-org"));
        RepoProviderSettings s = adapter(ov);

        assertEquals("admin-org", s.getOrg(), "被覆盖的字段取管理端值");
        assertEquals("https://env-hook.example.com", s.getWebhookBaseUrl(), "未覆盖的字段必须回落环境变量");
        assertEquals("env-id", s.getClientId(), "未覆盖的 Client ID 不得被清空");
        assertTrue(s.clientSecretConfigured(), "未覆盖的 Client Secret 不得被清空");
    }

    @Test
    @DisplayName("空串是有效值：管理端清空后不得被环境变量的值顶回来")
    void emptyStringIsAnExplicitValue() {
        PlatformConfigOverlay ov = new PlatformConfigOverlay();
        ov.apply("gitee", true, map(Field.WEBHOOK_BASE_URL, ""));
        RepoProviderSettings s = adapter(ov);

        assertEquals("", s.getWebhookBaseUrl(), "空串必须生效（否则用户永远清不掉这个值）");
        assertEquals("env-org", s.getOrg(), "同一行未覆盖的字段仍取环境变量");
    }

    @Test
    @DisplayName("provider 隔离：表里存的是 gitee 的值，切到 gitea 必须不采用")
    void overlayIsIgnoredForOtherProvider() {
        PlatformConfigOverlay ov = new PlatformConfigOverlay();
        ov.apply("gitea", true, map(Field.ORG, "gitea-admin-org"));
        RepoProviderSettings s = adapter(ov); // provider=gitee

        assertEquals("env-org", s.getOrg(), "非本托管方的覆盖不得生效");
        assertFalse(ov.covers(Field.ORG, "gitee"), "covers() 必须自带归属校验");
        assertTrue(ov.covers(Field.ORG, "gitea"));
    }

    @Test
    @DisplayName("clear() 后全部回落环境变量（对应「恢复为环境变量」按钮）")
    void clearRestoresEnv() {
        PlatformConfigOverlay ov = new PlatformConfigOverlay();
        ov.apply("gitee", true, map(Field.ORG, "admin-org", Field.ENABLED, "false"));
        RepoProviderSettings s = adapter(ov);
        assertEquals("admin-org", s.getOrg());
        assertFalse(s.isEnabled(), "管理端可以关掉总开关");

        ov.clear();
        assertEquals("env-org", s.getOrg());
        assertTrue(s.isEnabled());
        assertEquals(0, ov.coveredCount());
        assertFalse(ov.hasRow());
    }
}
