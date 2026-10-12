package cn.aioa.common.security;

import java.util.ArrayList;
import java.util.List;

/**
 * 密钥强度自检（C-1）：占位默认值 / 空 / 过短，一律视为不安全。
 *
 * <p><b>门控纪律</b>：本类是纯逻辑、不依赖 Spring，便于单元测试直接调用。是否「拒绝启动」
 * 由调用方按激活 profile 决定 —— <b>只有显式 {@code prod} 才 fail-closed 抛异常</b>；
 * {@code default/dev/local/test} 一律只返回违规项，由调用方打 WARN。理由：本地
 * {@code default}（本仓实际回退为 {@code dev}）profile + {@code .env} 未必注入环境变量，
 * 若在 default 上也 fail-closed，会把用户本地后端直接打挂，违背「任何改动都不能打断本地开发」。</p>
 *
 * <p>判据：{@code null / blank / 等于已知占位串 / 长度 < 32（字符）} 任一即违规。</p>
 */
public final class SecretStrengthValidator {

    private SecretStrengthValidator() {
    }

    /** 最短密钥长度（字符）。HMAC-SHA256 / AES-256 至少需要 32 字节。 */
    public static final int MIN_SECRET_LENGTH = 32;

    /** 单个待检密钥（名称仅用于日志/报错，不参与判定）。 */
    public record NamedSecret(String name, String value) {
    }

    /**
     * 对一组密钥做强度校验，返回违规说明列表（空列表 = 全部通过）。
     */
    public static List<String> validate(List<NamedSecret> secrets) {
        List<String> violations = new ArrayList<>();
        if (secrets == null) {
            return violations;
        }
        for (NamedSecret s : secrets) {
            String v = s == null ? null : s.value();
            String name = s == null ? "?" : s.name();
            if (v == null || v.isBlank()) {
                violations.add(name + ": 密钥为空（必须为 >= " + MIN_SECRET_LENGTH + " 字符的有效值）");
                continue;
            }
            if (DevSecretPlaceholders.isKnownPlaceholder(v)) {
                violations.add(name + ": 仍使用占位默认值（" + v + "），生产必须覆盖");
                continue;
            }
            if (v.length() < MIN_SECRET_LENGTH) {
                violations.add(name + ": 长度 " + v.length() + " < " + MIN_SECRET_LENGTH + "（字符）");
            }
        }
        return violations;
    }

    /**
     * 激活 profile 是否代表生产环境。仅当存在一个名为 {@code prod} 的 profile 时返回 true；
     * {@code default/dev/local/test} 及其它一律视为非生产。
     */
    public static boolean isProdProfile(String[] activeProfiles) {
        if (activeProfiles == null) {
            return false;
        }
        for (String p : activeProfiles) {
            if (p != null && "prod".equalsIgnoreCase(p.trim())) {
                return true;
            }
        }
        return false;
    }

    /**
     * 执行门控：违规非空且处于生产 profile 时抛 {@link IllegalStateException} 拒绝启动；
     * 否则仅返回违规列表（调用方应打 WARN）。本方法本身不写日志。
     *
     * @param violations 已计算出的违规列表（来自 {@link #validate} 或调用方手工追加）
     * @param activeProfiles 当前激活的 profile 数组
     * @return 传入的 violations（便于链式处理）
     */
    public static List<String> enforce(List<String> violations, String[] activeProfiles) {
        if (violations == null || violations.isEmpty()) {
            return List.of();
        }
        if (isProdProfile(activeProfiles)) {
            throw new IllegalStateException(
                    "生产环境拒绝以弱密钥/占位密钥启动，请通过环境变量覆盖以下项：\n"
                            + String.join("\n", violations));
        }
        return violations;
    }
}
