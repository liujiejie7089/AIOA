package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Gitea 请求体构造测试。
 *
 * <p><b>为什么这批断言值得存在</b>：下面每一项都对应一个
 * 「接口返回 200、功能却没生效」的静默失效陷阱 —— 提交一份没有 {@code active:true}
 * 的 Webhook、或一份带 {@code path} 的建仓体，服务端都会<b>正常返回</b>，
 * 而问题要等到「回调怎么不来」「URL 怎么不是我想要的」才暴露，且那时离改动点已经很远。
 * 把这些约定变成可断言的值，回归时才有东西能挡住。</p>
 *
 * <p>这些方法都是纯函数（不碰 HTTP、不依赖 Spring），所以断言是确定性的。</p>
 */
class GiteaProviderRequestBodyTest {

    // ==================================================================
    // 建仓体
    // ==================================================================

    @Test
    @DisplayName("建仓体：type/内容符合 CreateRepoOption（auto_init 必须显式传）")
    void createRepoBodyShape() {
        Map<String, Object> body = GiteaProviderClient.buildCreateRepoBody(
                "部门十一项目", "dept11-aioa", "描述", true, true,
                GiteaProperties.RepoNameSource.AUTO, 100);

        assertEquals("dept11-aioa", body.get("name"), "AUTO 应优先取 path 以保证 URL 为 ASCII");
        assertEquals("描述", body.get("description"));
        assertEquals(true, body.get("private"));
        assertEquals(true, body.get("auto_init"), "auto_init 不传会建出空仓库，首次写文件会失败");
    }

    @Test
    @DisplayName("建仓体：**不得**出现 Gitea 不存在的 path，以及创建体不接受的 has_issues/has_wiki")
    void createRepoBodyMustNotCarryGiteeOnlyFields() {
        Map<String, Object> body = GiteaProviderClient.buildCreateRepoBody(
                "n", "p", "d", false, true,
                GiteaProperties.RepoNameSource.AUTO, 100);

        // 这三个键带上不会报错、但完全没有效果 —— 属静默失效，必须不存在
        assertFalse(body.containsKey("path"),
                "Gitea 的 CreateRepoOption 没有 path 字段（name 兼作 URL 片段）");
        assertFalse(body.containsKey("has_issues"),
                "has_issues 不在创建体里（属 EditRepoOption），带上无效果");
        assertFalse(body.containsKey("has_wiki"),
                "has_wiki 不在创建体里（属 EditRepoOption），带上无效果");
        assertEquals(4, body.size(), "建仓体应恰好 4 个键：" + body.keySet());
    }

    @ParameterizedTest(name = "[{index}] source={0} name={1} path={2} -> {3}")
    @DisplayName("仓库标识来源：AUTO 优先 path / NAME 用 name / PATH 强制 path")
    @CsvSource({
            "AUTO, '部门十一',  'dept11',      'dept11'",
            "AUTO, '部门十一',  '',            '部门十一'",
            "NAME, '部门十一',  'dept11',      '部门十一'",
            "PATH, '部门十一',  'dept11',      'dept11'"
    })
    void resolveRepoName(String source, String name, String path, String expected) {
        String got = GiteaProviderClient.resolveRepoName(
                name, path, GiteaProperties.RepoNameSource.valueOf(source), 100);
        assertEquals(expected, got);
    }

    @Test
    @DisplayName("PATH 来源但 path 为空：报错而不是静默回落到 name")
    void resolveRepoNamePathRequired() {
        RepoProviderException e = assertThrows(RepoProviderException.class, () ->
                GiteaProviderClient.resolveRepoName("部门十一", null,
                        GiteaProperties.RepoNameSource.PATH, 100));
        assertTrue(e.getMessage().contains("path"), "错误信息应指明是 path 缺失：" + e.getMessage());
    }

    @Test
    @DisplayName("仓库标识超长时按上限截断")
    void resolveRepoNameTruncates() {
        assertEquals("abcd", GiteaProviderClient.resolveRepoName(
                "abcdefg", null, GiteaProperties.RepoNameSource.NAME, 4));
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"", "   "})
    @DisplayName("标识来源为 null/空白：报错而不是产出空仓库名")
    void resolveRepoNameRejectsBlank(String blank) {
        assertThrows(RepoProviderException.class, () ->
                GiteaProviderClient.resolveRepoName(blank, blank,
                        GiteaProperties.RepoNameSource.AUTO, 100));
    }

    // ==================================================================
    // Webhook 体 —— 两个静默失效陷阱
    // ==================================================================

    @Test
    @DisplayName("Webhook 体：**active 必须为 true**（实例规范默认 false ⇒ 不置 true 则建好即停用，回调一条不来）")
    void hookBodyMustBeActive() {
        Map<String, Object> body = GiteaProviderClient.buildCreateHookBody(
                "https://aioa.example.com/api/v1/gitea/webhook/1", "s3cret", true, true, true, true);

        assertEquals(Boolean.TRUE, body.get("active"),
                "active 默认 false，不显式置 true 会得到一个「已创建但已停用」的 Webhook");
    }

    @Test
    @DisplayName("Webhook 体：type 必须是通用 Webhook（gitea），config.secret 承载 HMAC 密钥")
    void hookBodyTypeAndSecret() {
        Map<String, Object> body = GiteaProviderClient.buildCreateHookBody(
                "https://aioa.example.com/hook", "s3cret", true, false, false, false);

        assertEquals("gitea", body.get("type"), "通用 Webhook 的 type 取值就是 gitea");

        @SuppressWarnings("unchecked")
        Map<String, Object> config = (Map<String, Object>) body.get("config");
        assertEquals("https://aioa.example.com/hook", config.get("url"));
        assertEquals("json", config.get("content_type"));
        assertEquals("s3cret", config.get("secret"), "secret 是 HMAC-SHA256 的密钥（回调头 X-Gitea-Signature）");
    }

    @Test
    @DisplayName("Webhook 体：密钥为空时不写入 secret 键（而不是写入空串）")
    void hookBodyOmitsBlankSecret() {
        Map<String, Object> body = GiteaProviderClient.buildCreateHookBody(
                "https://x/hook", "  ", true, false, false, false);
        @SuppressWarnings("unchecked")
        Map<String, Object> config = (Map<String, Object>) body.get("config");
        assertFalse(config.containsKey("secret"), "空白密钥不应写成空串，那会建出无签名校验的 hook");
        assertNull(config.get("secret"));
    }

    @Test
    @DisplayName("事件名必须是 Gitea 的下划线风格，且按开关精确组合")
    void hookEventsAreGiteaStyle() {
        assertEquals(List.of("push"), GiteaProviderClient.hookEvents(true, false, false, false));
        assertEquals(List.of("issues"), GiteaProviderClient.hookEvents(false, false, true, false));
        assertEquals(List.of("pull_request", "pull_request_review"),
                GiteaProviderClient.hookEvents(false, true, false, false));
        assertEquals(List.of("issue_comment", "pull_request_review_comment"),
                GiteaProviderClient.hookEvents(false, false, false, true));
    }

    @Test
    @DisplayName("事件名不得出现 Gitee 的空格式（写错不报错，只会导致该事件永不投递）")
    void hookEventsContainNoGiteeStyleNames() {
        List<String> all = GiteaProviderClient.hookEvents(true, true, true, true);
        for (String ev : all) {
            assertFalse(ev.contains(" "), "事件名不应含空格（Gitee 风格如 \"Push Hook\"）：" + ev);
            assertEquals(ev.toLowerCase(), ev, "事件名应为小写下划线风格：" + ev);
        }
        assertTrue(all.contains("push") && all.contains("pull_request")
                        && all.contains("issues") && all.contains("issue_comment"),
                "四类核心事件都应被订阅：" + all);
    }

    @Test
    @DisplayName("全关时事件列表为空（调用方据此可判断「这个 hook 什么都不会来」）")
    void hookEventsAllOff() {
        assertTrue(GiteaProviderClient.hookEvents(false, false, false, false).isEmpty());
    }

    // ==================================================================
    // 错误语义映射
    // ==================================================================

    @Test
    @DisplayName("401 映射为「令牌失效、不可重试」")
    void exceptionMapping401() {
        RepoProviderException e = RepoProviderException.of(401, "Unauthorized");
        assertTrue(e.isTokenInvalid());
        assertFalse(e.isRetryable());
        assertEquals(401, e.getStatus());
    }

    @Test
    @DisplayName("403 且文案提示 scope 不足 → 视为授权问题（提示重新授权才对症）")
    void exceptionMapping403Scope() {
        RepoProviderException e = RepoProviderException.of(403,
                "token does not have at least one of required scope(s): [write:repository]");
        assertTrue(e.isTokenInvalid(), "scope 不足属授权问题，应提示重新授权");
        assertFalse(e.isRetryable());
    }

    @Test
    @DisplayName("403 且与 scope 无关 → 普通拒绝，不误判为需要重新授权")
    void exceptionMapping403Plain() {
        RepoProviderException e = RepoProviderException.of(403, "user does not have permission");
        assertFalse(e.isTokenInvalid(), "普通权限不足不该让用户去重新授权");
        assertFalse(e.isRetryable());
    }

    @ParameterizedTest
    @ValueSource(ints = {429, 500, 502, 503})
    @DisplayName("限流与 5xx 可重试")
    void exceptionMappingRetryable(int status) {
        assertTrue(RepoProviderException.of(status, "x").isRetryable());
    }

    @ParameterizedTest
    @ValueSource(ints = {400, 404, 409, 422})
    @DisplayName("参数/状态类 4xx 不可重试（重试一万次也不会好）")
    void exceptionMappingNotRetryable(int status) {
        RepoProviderException e = RepoProviderException.of(status, "x");
        assertFalse(e.isRetryable());
        assertFalse(e.isTokenInvalid());
    }

    @Test
    @DisplayName("基类默认托管方名为中性词，Gitee 子类覆写为 Gitee")
    void providerNames() {
        assertEquals("代码托管平台", RepoProviderException.of(400, "x").providerName());
        assertEquals("Gitee", new GiteeApiException(400, 0, "x", false, false).providerName(),
                "Gitee 文案必须保持逐字不变");
    }
}
