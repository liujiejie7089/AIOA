package cn.aioa.gitee.support;

import cn.aioa.gitee.config.RepoProviderSettings;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * Gitee 令牌的静态加密（AES-256-GCM）。
 *
 * <p><b>为什么必须加密</b>：{@code access_token} 等价于「以该用户身份读写其全部仓库」的凭据。
 * 明文入库意味着只要有人拿到一次库的读权限（备份、慢日志、只读从库）就能直接接管仓库，
 * 而用户完全无感。加密后密钥与应用分离，泄露单库不构成接管。</p>
 *
 * <p><b>密文格式</b>：{@code enc:} + Base64(12 字节 IV ‖ 密文 ‖ 16 字节 GCM Tag)。
 * 无 {@code enc:} 前缀的值按**明文**读回 —— 兼容手工写入的调试数据，避免升级即不可读。</p>
 *
 * <p><b>密钥派生</b>：配置的密钥经 SHA-256 取 32 字节，于是长度不足 32 字节也不会报错
 * （但生产必须覆盖默认值，否则默认密钥在仓库里等于没加密）。</p>
 */
@Component
@RequiredArgsConstructor
public class GiteeCrypto {

    private static final String PREFIX = "enc:";
    private static final int IV_LEN = 12;
    private static final int TAG_BITS = 128;

    private final RepoProviderSettings props;
    private final SecureRandom random = new SecureRandom();

    /** 加密；入参为 null / 空串时原样返回（令牌可能为空，如仅用 refresh_token）。 */
    public String encrypt(String plain) {
        if (plain == null || plain.isEmpty()) {
            return plain;
        }
        try {
            byte[] iv = new byte[IV_LEN];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key(), new GCMParameterSpec(TAG_BITS, iv));
            byte[] ct = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));

            byte[] out = new byte[iv.length + ct.length];
            System.arraycopy(iv, 0, out, 0, iv.length);
            System.arraycopy(ct, 0, out, iv.length, ct.length);
            return PREFIX + Base64.getEncoder().encodeToString(out);
        } catch (Exception e) {
            throw new IllegalStateException(props.providerLabel() + " 令牌加密失败", e);
        }
    }

    /**
     * 解密。无 {@code enc:} 前缀按明文返回（兼容历史 / 手工数据）。
     *
     * <p>解密失败抛异常而**不返回 null** —— 静默返回 null 会让上层把「密钥不对」
     * 误判成「用户没绑过账号」，从而给出完全错误的提示。</p>
     *
     * <p><b>文案必须指名当前生效的属性键</b>：密钥来自 {@code aioa.gitee.token-enc-key}
     * 还是 {@code aioa.gitea.token-enc-key} 取决于 provider；说错会让人去改一个
     * 根本不生效的配置项，把排查引到错误方向。</p>
     */
    public String decrypt(String stored) {
        if (stored == null || stored.isEmpty()) {
            return stored;
        }
        if (!stored.startsWith(PREFIX)) {
            return stored;
        }
        try {
            byte[] raw = Base64.getDecoder().decode(stored.substring(PREFIX.length()));
            byte[] iv = new byte[IV_LEN];
            System.arraycopy(raw, 0, iv, 0, IV_LEN);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(TAG_BITS, iv));
            byte[] pt = cipher.doFinal(raw, IV_LEN, raw.length - IV_LEN);
            return new String(pt, StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new IllegalStateException("令牌解密失败：请确认 " + props.tokenEncKeyProperty()
                    + " 未被变更；若刚切换过托管方（aioa.repo.provider），"
                    + "则这条密文是用另一个平台的密钥写的，需要重新授权绑定", e);
        }
    }

    /** 是否已是密文（用于判断是否需要重写）。 */
    public boolean isEncrypted(String v) {
        return v != null && v.startsWith(PREFIX);
    }

    private SecretKeySpec key() {
        try {
            String raw = props.getTokenEncKey() == null ? "" : props.getTokenEncKey();
            byte[] k = MessageDigest.getInstance("SHA-256").digest(raw.getBytes(StandardCharsets.UTF_8));
            return new SecretKeySpec(k, "AES");
        } catch (Exception e) {
            throw new IllegalStateException("无法派生 " + props.providerLabel() + " 令牌加密密钥", e);
        }
    }
}
