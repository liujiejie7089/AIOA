package cn.aios.common.crypto;

import cn.aios.common.security.DevSecretPlaceholders;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * 连接器凭据的静态加密（AES-256-GCM）。
 *
 * <p><b>密文格式</b>：{@code enc:} + Base64(12 字节 IV ‖ 密文 ‖ 16 字节 GCM Tag)。
 * 与 {@code GiteeCrypto} 完全同口径（同一套 IV/Tag 长度与密钥派生），以便安全审计时作为统一范式理解。
 * 无 {@code enc:} 前缀的值按<b>明文</b>读回 —— 兼容手工写入的调试数据，避免升级即不可读。</p>
 *
 * <p><b>密钥派生</b>：配置的密钥经 SHA-256 取 32 字节，于是长度不足 32 字节也不会报错
 * （但生产必须覆盖默认值，否则默认密钥在仓库里等于没加密）。</p>
 *
 * <p><b>解密失败抛异常而<b>不</b>返回 null/空串</b>：静默返回空会让上层把「密钥不对」
 * 误判成「用户没绑过账号」，从而给出完全错误的提示。</p>
 */
@Component
@ConfigurationProperties(prefix = "aios.connector")
@Getter
@Setter
public class SecretCodec {

    private static final String PREFIX = "enc:";
    private static final int IV_LEN = 12;
    private static final int TAG_BITS = 128;

    /** 加密密钥（AES-256）：生产必须通过 aios.connector.secret-key 覆盖，否则等于未加密。 */
    private String secretKey = DevSecretPlaceholders.CONNECTOR_SECRET_KEY;

    private final SecureRandom random = new SecureRandom();

    /** 加密；入参为 null / 空串时原样返回（凭据可能为空，如仅用 refresh_token 的场景）。 */
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
            throw new IllegalStateException("连接器凭据加密失败", e);
        }
    }

    /**
     * 解密。无 {@code enc:} 前缀按明文返回（兼容历史 / 手工数据）。
     *
     * <p>解密失败抛 {@link IllegalStateException} —— <b>绝不</b>静默返回 null/空串/明文，
     * 否则会把「密钥变更导致解密失败」误判成「用户未连接」，误导排障方向。</p>
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
            throw new IllegalStateException("连接器凭据解密失败：请确认 aios.connector.secret-key 未被变更；"
                    + "若刚切换过密钥，则这条密文是用旧密钥写的，需要重新连接授权", e);
        }
    }

    /** 是否已是密文（用于判断是否需要重写）。 */
    public boolean isEncrypted(String v) {
        return v != null && v.startsWith(PREFIX);
    }

    private SecretKeySpec key() {
        try {
            String raw = secretKey == null ? "" : secretKey;
            byte[] k = MessageDigest.getInstance("SHA-256").digest(raw.getBytes(StandardCharsets.UTF_8));
            return new SecretKeySpec(k, "AES");
        } catch (Exception e) {
            throw new IllegalStateException("无法派生连接器凭据加密密钥", e);
        }
    }
}
