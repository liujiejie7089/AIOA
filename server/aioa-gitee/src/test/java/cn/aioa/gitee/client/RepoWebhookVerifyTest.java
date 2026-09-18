package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Webhook 投递校验测试（两家机制不同，各自守一条）。
 *
 * <p><b>为什么这是全模块最该被测的一段</b>：Webhook 端点是平台上<b>唯一</b>无需登录态
 * 就能写数据的入口。校验写错不会让任何既有功能变红 —— 只会静默地把这个入口变成公开写接口
 * （任何人都能伪造提交记录）。因此这里的断言方向是「**不通过的必须不通过**」，
 * 而不是「正常情况能通过」。</p>
 *
 * <p>HMAC 期望值由 <b>Python 的 {@code hmac} 模块独立计算</b>后写死，不是拿本实现的输出
 * 回填的 —— 否则实现写错时测试会跟着一起错，等于没有测试。</p>
 */
class RepoWebhookVerifyTest {

    private static final String SECRET = "s3cret-key";

    private static GiteaProviderClient gitea() {
        GiteaProperties props = new GiteaProperties();
        props.setBaseUrl("http://127.0.0.1:1/api/v1");
        return new GiteaProviderClient(props, new ObjectMapper());
    }

    private static GiteeClient gitee() {
        return new GiteeClient(new GiteeProperties(), new ObjectMapper());
    }

    private static Map<String, String> headers(String k, String v) {
        Map<String, String> m = new HashMap<>();
        if (k != null) {
            m.put(k, v);
        }
        return m;
    }

    // ==================================================================
    // Gitea：HMAC-SHA256
    // ==================================================================

    @Nested
    @DisplayName("Gitea：HMAC-SHA256 签名校验")
    class GiteaHmac {

        /** 期望值来源：Python hmac.new(b's3cret-key', body, sha256).hexdigest()。 */
        private static final String BODY_JSON = "{\"ref\":\"refs/heads/master\"}";
        private static final String EXPECTED_HEX =
                "2e360a7d00b491c91785fcb918310f405dfe10c516f9f0642ff8486d3154a4af";

        @Test
        @DisplayName("HMAC 计算与独立实现（Python hmac）逐字符一致")
        void hmacMatchesIndependentImplementation() {
            assertEquals(EXPECTED_HEX,
                    GiteaProviderClient.hmacSha256Hex(BODY_JSON.getBytes(StandardCharsets.UTF_8), SECRET));
        }

        @Test
        @DisplayName("中文报文的 HMAC 也一致（验证按字节计算，没被字符集往返污染）")
        void hmacMatchesForNonAsciiBody() {
            // Python: hmac.new(b's3cret-key', '{"备注":"中文"}'.encode('utf-8'), sha256).hexdigest()
            assertEquals("1a2fadc24a58aa249a4731ea718b6adbed888ce13412b1e7c06c42beff2df2a4",
                    GiteaProviderClient.hmacSha256Hex(
                            "{\"备注\":\"中文\"}".getBytes(StandardCharsets.UTF_8), SECRET));
        }

        @Test
        @DisplayName("空报文的 HMAC 与独立实现一致")
        void hmacEmptyBody() {
            // Python: hmac.new(b's3cret-key', b'', sha256).hexdigest()
            assertEquals("03b5d47de6f8548b83940d24f99f8345cb156d953238ce3a1b7cb6ece090dcd5",
                    GiteaProviderClient.hmacSha256Hex(new byte[0], SECRET));
        }

        @Test
        @DisplayName("原生头 X-Gitea-Signature（无前缀）校验通过")
        void acceptsNativeHeader() {
            assertTrue(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitea-Signature", EXPECTED_HEX), SECRET));
        }

        @Test
        @DisplayName("GitHub 兼容头 X-Hub-Signature-256（带 sha256= 前缀）校验通过")
        void acceptsHubHeaderWithPrefix() {
            assertTrue(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Hub-Signature-256", "sha256=" + EXPECTED_HEX), SECRET));
        }

        @Test
        @DisplayName("十六进制大小写不敏感")
        void signatureCaseInsensitive() {
            assertTrue(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitea-Signature", EXPECTED_HEX.toUpperCase()), SECRET));
        }

        @Test
        @DisplayName("签名头大小写不敏感（不同 HTTP 栈规范化程度不同）")
        void headerNameCaseInsensitive() {
            assertTrue(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("x-gitea-signature", EXPECTED_HEX), SECRET));
        }

        @Test
        @DisplayName("**报文被改动一个字节 → 必须拒绝**（否则签名形同虚设）")
        void rejectsTamperedBody() {
            String tampered = "{\"ref\":\"refs/heads/main\"}";
            assertFalse(gitea().verifyWebhook(tampered.getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitea-Signature", EXPECTED_HEX), SECRET),
                    "报文与签名不匹配时必须拒绝");
        }

        @Test
        @DisplayName("**换一个密钥 → 必须拒绝**")
        void rejectsWrongSecret() {
            assertFalse(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitea-Signature", EXPECTED_HEX), "another-secret"));
        }

        @Test
        @DisplayName("缺少签名头 → 必须拒绝（不能因为「没带」就放行）")
        void rejectsMissingSignatureHeader() {
            assertFalse(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers(null, null), SECRET));
            assertFalse(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    Map.of(), SECRET));
        }

        @Test
        @DisplayName("密钥为空 → 必须拒绝（未配置密钥的项目不得成为公开写入口）")
        void rejectsBlankSecret() {
            assertFalse(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitea-Signature", EXPECTED_HEX), ""));
            assertFalse(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitea-Signature", EXPECTED_HEX), null));
        }

        @Test
        @DisplayName("报文为 null → 必须拒绝（不抛异常，也不放行）")
        void rejectsNullBody() {
            assertFalse(gitea().verifyWebhook(null,
                    headers("X-Gitea-Signature", EXPECTED_HEX), SECRET));
        }

        @Test
        @DisplayName("sha1= 前缀被明确拒绝，而不是拿 sha1 的值去比 sha256")
        void rejectsSha1Prefix() {
            assertFalse(gitea().verifyWebhook(BODY_JSON.getBytes(StandardCharsets.UTF_8),
                    headers("X-Hub-Signature-256", "sha1=" + EXPECTED_HEX), SECRET),
                    "sha1 摘要长度不同，明确拒绝以便日志指向「客户端用了弱算法」");
        }

        @Test
        @DisplayName("事件头/请求 id 头名是 Gitea 的（写成 Gitee 的会取不到值）")
        void headerNamesAreGiteaStyle() {
            assertEquals("X-Gitea-Event", gitea().webhookEventHeader());
            assertEquals("X-Gitea-Delivery", gitea().webhookRequestIdHeader());
        }
    }

    // ==================================================================
    // Gitee：明文共享密钥比对（回归 —— 必须与此前行为完全一致）
    // ==================================================================

    @Nested
    @DisplayName("Gitee：明文共享密钥比对（回归）")
    class GiteePlaintext {

        @Test
        @DisplayName("X-Gitee-Token 与密钥相等时通过")
        void acceptsMatchingToken() {
            assertTrue(gitee().verifyWebhook("{}".getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitee-Token", SECRET), SECRET));
        }

        @Test
        @DisplayName("密钥不符 / 缺失 / 为空一律拒绝")
        void rejectsMismatch() {
            byte[] body = "{}".getBytes(StandardCharsets.UTF_8);
            assertFalse(gitee().verifyWebhook(body, headers("X-Gitee-Token", "wrong"), SECRET));
            assertFalse(gitee().verifyWebhook(body, headers("X-Gitee-Token", ""), SECRET));
            assertFalse(gitee().verifyWebhook(body, Map.of(), SECRET));
            assertFalse(gitee().verifyWebhook(body, headers("X-Gitee-Token", SECRET), ""));
            assertFalse(gitee().verifyWebhook(body, headers("X-Gitee-Token", SECRET), null));
        }

        @Test
        @DisplayName("Gitee 不看报文内容：校验只看共享密钥（与 Gitea 的签名机制本质不同）")
        void giteeDoesNotDependOnBody() {
            // 同一密钥下，任意报文都通过 —— 这正是「把 Gitea 的签名校验套到 Gitee 上」会失败的原因
            assertTrue(gitee().verifyWebhook("anything".getBytes(StandardCharsets.UTF_8),
                    headers("X-Gitee-Token", SECRET), SECRET));
        }

        @Test
        @DisplayName("事件头/请求 id 头名是 Gitee 的（回归）")
        void headerNamesAreGiteeStyle() {
            assertEquals("X-Gitee-Event", gitee().webhookEventHeader());
            assertEquals("X-Gitee-Request-Id", gitee().webhookRequestIdHeader());
        }
    }

    // ==================================================================
    // 常量时间比对
    // ==================================================================

    @Test
    @DisplayName("常量时间十六进制比对：等长才比内容，长度不同直接 false")
    void constantTimeEqualsHex() {
        assertTrue(GiteaProviderClient.constantTimeEqualsHex("abcd", "abcd"));
        assertTrue(GiteaProviderClient.constantTimeEqualsHex("ABCD", "abcd"));
        assertFalse(GiteaProviderClient.constantTimeEqualsHex("abcd", "abce"));
        assertFalse(GiteaProviderClient.constantTimeEqualsHex("abcd", "abc"));
        assertFalse(GiteaProviderClient.constantTimeEqualsHex(null, "abcd"));
        assertFalse(GiteaProviderClient.constantTimeEqualsHex("abcd", null));
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "   "})
    @DisplayName("空白密钥不构成有效凭证")
    void blankSecretNeverValid(String blank) {
        assertFalse(gitea().verifyWebhook("{}".getBytes(StandardCharsets.UTF_8),
                headers("X-Gitea-Signature", blank), blank));
        assertFalse(gitee().verifyWebhook("{}".getBytes(StandardCharsets.UTF_8),
                headers("X-Gitee-Token", blank), blank));
    }
}
