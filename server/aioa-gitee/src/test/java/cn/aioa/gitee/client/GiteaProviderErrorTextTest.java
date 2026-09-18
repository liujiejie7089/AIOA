package cn.aioa.gitee.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 错误体「人话」提取：{@code error_description} 必须优先于 {@code error}。
 *
 * <p>守的是「排障信息在入口就被丢掉」这一类缺陷。真机实测（Gitea 1.26.2，2026-09-18）
 * 换令牌端点 {@code POST /login/oauth/access_token} 的错误体形状与其它路由不同：</p>
 * <pre>
 * 旧 OAuth 应用（登记页显示的密钥）→ {"error":"unauthorized_client",
 *                                    "error_description":"invalid client secret"}
 * 正确密钥 + 无效授权码            → {"error":"unauthorized_client",
 *                                    "error_description":"client is not authorized"}
 * </pre>
 *
 * <p>{@code error} 恒为 {@code unauthorized_client}，两种截然不同的故障（平台侧密钥失配 /
 * 授权码无效）在页面上会显示成<b>同一个字符串</b>，用户截图只剩
 * {@code 原因：unauthorized_client}，无法据此定位 —— 正是本用例锁住的行为。</p>
 */
class GiteaProviderErrorTextTest {

    private static final ObjectMapper M = new ObjectMapper();

    private static JsonNode json(String s) {
        try {
            return M.readTree(s);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    @Test
    @DisplayName("OAuth 错误体：取 error_description，并保留 error 码以便对照文档")
    void prefersErrorDescription() {
        String r = GiteaProviderClient.firstDetail(json(
                "{\"error\":\"unauthorized_client\",\"error_description\":\"invalid client secret\"}"));
        assertEquals("invalid client secret（unauthorized_client）", r);
    }

    @Test
    @DisplayName("同为 unauthorized_client 的两种故障必须可区分（这是本修复的全部意义）")
    void twoFailuresMustNotCollapseIntoOne() {
        String secretWrong = GiteaProviderClient.firstDetail(json(
                "{\"error\":\"unauthorized_client\",\"error_description\":\"invalid client secret\"}"));
        String codeWrong = GiteaProviderClient.firstDetail(json(
                "{\"error\":\"unauthorized_client\",\"error_description\":\"client is not authorized\"}"));
        assertTrue(!secretWrong.equals(codeWrong),
                "密钥失配与授权码无效被判成同一字符串就等于没有信息：" + secretWrong);
    }

    @Test
    @DisplayName("errors[] 优先于 error_description（协作方 422 场景不能被改坏）")
    void errorsArrayStillWins() {
        String r = GiteaProviderClient.firstDetail(json(
                "{\"message\":\"GetUserByName\",\"errors\":[\"user does not exist [uid: 0, name: x]\"],"
                        + "\"error\":\"unauthorized_client\",\"error_description\":\"invalid client secret\"}"));
        assertEquals("user does not exist [uid: 0, name: x]", r);
    }

    @Test
    @DisplayName("只有 error 码时退回 error（无 description 不能变成 null）")
    void fallsBackToErrorCode() {
        assertEquals("invalid_client",
                GiteaProviderClient.firstDetail(json("{\"error\":\"invalid_client\"}")));
    }

    @Test
    @DisplayName("description 与 error 相同时不重复拼接")
    void noDuplicationWhenEqual() {
        assertEquals("boom",
                GiteaProviderClient.firstDetail(json("{\"error\":\"boom\",\"error_description\":\"boom\"}")));
    }

    @Test
    @DisplayName("两者都缺时返回 null，交由上层走原文截断，而不是伪造文案")
    void nullWhenNothingUsable() {
        assertNull(GiteaProviderClient.firstDetail(json("{\"unexpected\":1}")));
    }
}
