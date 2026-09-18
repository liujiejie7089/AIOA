package cn.aioa.gitee.support;

import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.gitee.config.RepoProviderSettingsAdapter;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 令牌密钥错误时的**可执行性**：文案必须指向当前生效的配置键。
 *
 * <p><b>为什么这不是「测字符串」</b>：切托管方后老绑定的密文必然解不开（两个平台
 * 用不同的密钥）。此时用户看到的报错，决定了他是能一次改对，还是去改一个
 * 在当前 provider 下**根本不生效**的配置项、然后把问题查成死胡同。
 * 真机实测的原报错是 500「服务内部错误」+ 日志里的
 * {@code aioa.gitee.token-enc-key}（而当时 provider=gitea）。</p>
 */
class GiteeCryptoProviderAwareTest {

    private RepoProviderSettingsAdapter adapter(String provider, String giteeKey, String giteaKey) {
        GiteeProperties gitee = new GiteeProperties();
        gitee.setTokenEncKey(giteeKey);
        GiteaProperties gitea = new GiteaProperties();
        gitea.setTokenEncKey(giteaKey);
        RepoProviderSettingsAdapter a = new RepoProviderSettingsAdapter(gitee, gitea);
        ReflectionTestUtils.setField(a, "provider", provider);
        return a;
    }

    @Test
    @DisplayName("同密钥往返可解密（不能因为改了文案把正常路径弄坏）")
    void roundTripWorks() {
        GiteeCrypto crypto = new GiteeCrypto(adapter("gitea", "gitee-key", "gitea-key"));
        String enc = crypto.encrypt("aioa-pat-abcdef");
        assertTrue(crypto.isEncrypted(enc), enc);
        assertEquals("aioa-pat-abcdef", crypto.decrypt(enc));
    }

    @Test
    @DisplayName("异平台密文（Tag mismatch）：报错指名 aioa.gitea.token-enc-key 且不误指 gitee 键")
    void foreignCiphertextNamesActiveProviderKey() {
        // 这份密文是用「另一个密钥」写的，模拟切换到 gitea 后遗留的 gitee 绑定
        String foreign = new GiteeCrypto(adapter("gitee", "gitee-key", "gitea-key"))
                .encrypt("gitee-user-token");

        GiteeCrypto onGitea = new GiteeCrypto(adapter("gitea", "gitee-key", "gitea-key"));
        IllegalStateException e = assertThrows(IllegalStateException.class,
                () -> onGitea.decrypt(foreign), "异平台密钥必须解密失败，不能静默返回原文");

        String msg = String.valueOf(e.getMessage());
        assertTrue(msg.contains("aioa.gitea.token-enc-key"),
                "必须指名当前生效的键，实际=" + msg);
        assertFalse(msg.contains("aioa.gitee.token-enc-key"),
                "不能把用户指向一个在 gitea 下不生效的键，实际=" + msg);
        assertTrue(msg.contains("切换过托管方") || msg.contains("重新授权"),
                "必须给出下一步动作，实际=" + msg);
    }

    @Test
    @DisplayName("明文（无 enc: 前缀）原样返回：兼容历史/手工调试数据，不得因加校验而拒读")
    void plaintextPassesThrough() {
        GiteeCrypto crypto = new GiteeCrypto(adapter("gitea", "gitee-key", "gitea-key"));
        assertEquals("plain-token", crypto.decrypt("plain-token"));
        assertFalse(crypto.isEncrypted("plain-token"));
    }
}
