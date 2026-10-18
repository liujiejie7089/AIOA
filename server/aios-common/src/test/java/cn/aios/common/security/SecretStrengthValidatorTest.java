package cn.aios.common.security;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import cn.aios.common.security.SecretStrengthValidator.NamedSecret;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * C-1 密钥 fail-closed 自检逻辑（纯逻辑，无 Spring）。
 *
 * <p>门控纪律：仅 prod profile 抛异常拒绝启动；其它 profile（dev/default/local/test）
 * 即使发现弱密钥也只返回违规项、不抛异常（由调用方打 WARN，不阻断本地开发）。</p>
 */
class SecretStrengthValidatorTest {

    private final NamedSecret jwt = new NamedSecret("aios.jwt.secret", DevSecretPlaceholders.JWT);
    private final NamedSecret good = new NamedSecret("good", "this-is-a-good-32plus-char-secret-key-xyz-1234567890");

    @Test
    @DisplayName("占位默认值被识别为违规")
    void placeholderDetected() {
        List<String> v = SecretStrengthValidator.validate(List.of(jwt));
        assertEquals(1, v.size());
        assertTrue(v.get(0).contains("占位默认值"));
    }

    @Test
    @DisplayName("长度 < 32 的密钥被识别为违规")
    void tooShortDetected() {
        List<String> v = SecretStrengthValidator.validate(
                List.of(new NamedSecret("short", "tooshort")));
        assertEquals(1, v.size());
        assertTrue(v.get(0).contains("长度"));
    }

    @Test
    @DisplayName("空/blank 密钥被识别为违规")
    void blankDetected() {
        List<String> v = SecretStrengthValidator.validate(List.of(new NamedSecret("e", "  ")));
        assertEquals(1, v.size());
        assertTrue(v.get(0).contains("为空"));
    }

    @Test
    @DisplayName(">=32 字符且非占位串的密钥通过")
    void strongPasses() {
        assertTrue(SecretStrengthValidator.validate(List.of(good)).isEmpty());
    }

    @Test
    @DisplayName("isProdProfile：仅 prod 视为生产")
    void prodDetection() {
        assertTrue(SecretStrengthValidator.isProdProfile(new String[]{"prod"}));
        assertTrue(SecretStrengthValidator.isProdProfile(new String[]{"dev", "prod"}));
        assertTrue(SecretStrengthValidator.isProdProfile(new String[]{"PROD"}));
        assertEquals(false, SecretStrengthValidator.isProdProfile(new String[]{"dev"}));
        assertEquals(false, SecretStrengthValidator.isProdProfile(new String[]{"default"}));
        assertEquals(false, SecretStrengthValidator.isProdProfile(new String[]{"local", "test"}));
        assertEquals(false, SecretStrengthValidator.isProdProfile(null));
    }

    @Test
    @DisplayName("prod + 违规 => 抛 IllegalStateException 拒绝启动")
    void prodEnforceThrows() {
        List<String> v = SecretStrengthValidator.validate(List.of(jwt));
        IllegalStateException e = assertThrows(IllegalStateException.class,
                () -> SecretStrengthValidator.enforce(v, new String[]{"prod"}));
        assertTrue(e.getMessage().contains("生产环境拒绝"));
    }

    @Test
    @DisplayName("dev + 违规 => 不抛异常（仅 WARN，不阻断本地开发）")
    void devEnforceDoesNotThrow() {
        List<String> v = SecretStrengthValidator.validate(List.of(jwt));
        // 断言：本地 default/dev 下即使有弱密钥也不抛异常（等价于只 WARN）
        List<String> returned = SecretStrengthValidator.enforce(v, new String[]{"dev"});
        assertEquals(1, returned.size());
    }

    @Test
    @DisplayName("无违规时任何 profile 都不抛")
    void noViolationNoThrow() {
        List<String> v = SecretStrengthValidator.validate(List.of(good));
        assertTrue(SecretStrengthValidator.enforce(v, new String[]{"prod"}).isEmpty());
        assertTrue(SecretStrengthValidator.enforce(v, new String[]{"dev"}).isEmpty());
    }
}
