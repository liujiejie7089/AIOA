package cn.aioa.admin.support;

import lombok.extern.slf4j.Slf4j;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * 模型 API Key 落库加密（AES-256-GCM）。
 *
 * <p>为什么加密：管理端「手动添加模型」允许管理员直接填写 API Key。明文入库会被
 * 数据库备份 / 运维导出带出去，因此只存密文；列表接口永远只返回掩码（见 ModelConfigView），
 * 明文仅在推送 agent 热加载时解密后走内网传输。
 *
 * <p>密钥来源（按优先级）：
 * <ol>
 *   <li>{@code AIOA_MODEL_KEY_ENC_KEY} —— 模型专用，建议生产单独配置；</li>
 *   <li>{@code AIOA_GITEE_TOKEN_ENC_KEY} —— 复用项目既有的令牌加密键；</li>
 *   <li>内置默认 —— 仅保证单机开发可用，启动日志会 WARN（等价于弱保护，生产必须配置上面任一个）。</li>
 * </ol>
 * 密钥字符串经 SHA-256 收敛为 32 字节 AES 密钥，因此长度不限。
 */
@Slf4j
@Component
public class ModelKeyCodec {

    /** 密文前缀：用于识别「已加密」，也便于将来换算法时演进版本。 */
    private static final String PREFIX = "ENC1:";

    private static final String ALGORITHM = "AES/GCM/NoPadding";
    private static final int IV_BYTES = 12;
    private static final int TAG_BITS = 128;

    private static final String FALLBACK_SECRET = "aioa-model-key-dev-only";

    private final SecretKey secretKey;
    private final boolean usingFallback;

    public ModelKeyCodec(Environment env) {
        String secret = firstNonBlank(
                env.getProperty("AIOA_MODEL_KEY_ENC_KEY"),
                env.getProperty("aioa.model.key.enc.key"),
                env.getProperty("AIOA_GITEE_TOKEN_ENC_KEY"),
                env.getProperty("aioa.gitee.token-enc-key"));
        this.usingFallback = secret == null;
        this.secretKey = buildKey(usingFallback ? FALLBACK_SECRET : secret);
        if (usingFallback) {
            log.warn("AIOA_MODEL_KEY_ENC_KEY / AIOA_GITEE_TOKEN_ENC_KEY 均未配置，"
                    + "模型 API Key 将使用内置开发密钥加密（弱保护）。生产环境请配置其中之一。");
        }
    }

    /** 加密；明文为空返回 null。 */
    public String encrypt(String plain) {
        if (plain == null || plain.isBlank()) {
            return null;
        }
        try {
            byte[] iv = new byte[IV_BYTES];
            new SecureRandom().nextBytes(iv);
            Cipher cipher = Cipher.getInstance(ALGORITHM);
            cipher.init(Cipher.ENCRYPT_MODE, secretKey, new GCMParameterSpec(TAG_BITS, iv));
            byte[] body = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            byte[] packed = new byte[iv.length + body.length];
            System.arraycopy(iv, 0, packed, 0, iv.length);
            System.arraycopy(body, 0, packed, iv.length, body.length);
            return PREFIX + Base64.getEncoder().encodeToString(packed);
        } catch (Exception e) {
            throw new IllegalStateException("模型 API Key 加密失败", e);
        }
    }

    /** 解密；无前缀（历史明文/空值）按原样返回，保证读取路径不中断。 */
    public String decrypt(String stored) {
        if (stored == null || stored.isBlank() || !stored.startsWith(PREFIX)) {
            return stored;
        }
        try {
            byte[] packed = Base64.getDecoder().decode(stored.substring(PREFIX.length()));
            byte[] iv = new byte[IV_BYTES];
            byte[] body = new byte[packed.length - IV_BYTES];
            System.arraycopy(packed, 0, iv, 0, IV_BYTES);
            System.arraycopy(packed, IV_BYTES, body, 0, body.length);
            Cipher cipher = Cipher.getInstance(ALGORITHM);
            cipher.init(Cipher.DECRYPT_MODE, secretKey, new GCMParameterSpec(TAG_BITS, iv));
            return new String(cipher.doFinal(body), StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new IllegalStateException("模型 API Key 解密失败（密钥被更换？）", e);
        }
    }

    /** 展示用掩码：只留前 4 与后 4 位，短串全掩码。 */
    public static String mask(String plain) {
        if (plain == null || plain.isBlank()) {
            return "";
        }
        String s = plain.trim();
        if (s.length() <= 8) {
            return "****";
        }
        return s.substring(0, 4) + "****" + s.substring(s.length() - 4);
    }

    public boolean isUsingFallback() {
        return usingFallback;
    }

    private static SecretKey buildKey(String secret) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] key = digest.digest(secret.getBytes(StandardCharsets.UTF_8));
            return new SecretKeySpec(key, "AES");
        } catch (Exception e) {
            throw new IllegalStateException("模型加密密钥初始化失败", e);
        }
    }

    private static String firstNonBlank(String... candidates) {
        for (String c : candidates) {
            if (c != null && !c.isBlank()) {
                return c;
            }
        }
        return null;
    }
}
