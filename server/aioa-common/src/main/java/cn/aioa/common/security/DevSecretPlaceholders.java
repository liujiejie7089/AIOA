package cn.aioa.common.security;

import java.util.List;

/**
 * 已知的「开发占位默认密钥」集中登记处（C-1）。
 *
 * <p><b>为什么集中在一处</b>：密钥 fail-closed 的启动自检、以及各 {@code *Properties}
 * 字段的默认值，都必须引用同一组字符串。散落多份会导致「改了自检的占位清单、
 * 却忘了改属性默认值」之类的口径漂移 —— 于是真实生产仍用着占位密钥却自检绿灯。
 * 把所有已知占位串归到这里，属性默认值与自检逻辑都 {@code import} 它，从源头保证一致。</p>
 *
 * <p><b>注意</b>：{@code application.yml} 里 {@code ${AIOA_*:占位串}} 的占位串是 YAML 字面量，
 * 无法引用 Java 常量，因此那里仍保留字面量（且按纪律<b>不得删除</b>，否则缺环境变量时
 * Spring 绑定失败会直接打断本地开发）。本类与 yml 字面量必须保持逐字一致，由自检逻辑
 * 通过 {@link #isKnownPlaceholder(String)} 兜底比对。</p>
 */
public final class DevSecretPlaceholders {

    private DevSecretPlaceholders() {
    }

    /** 用户侧 JWT HS256 密钥的占位默认值（aioa.jwt.secret）。 */
    public static final String JWT = "aioa-dev-jwt-secret-please-change-in-production";

    /** 服务间 JWT HS256 密钥的占位默认值（aioa.service-jwt.secret）。 */
    public static final String SERVICE_JWT = "aioa-dev-service-jwt-secret-please-change";

    /** Gitee 令牌加密密钥的占位默认值（aioa.gitee.token-enc-key）。 */
    public static final String GITEE_TOKEN_ENC = "aioa-dev-gitee-token-key-please-change";

    /** Gitea 令牌加密密钥的占位默认值（aioa.gitea.token-enc-key）。 */
    public static final String GITEA_TOKEN_ENC = "aioa-dev-gitea-token-key-please-change";

    /** 模型 API Key 落库加密的内置 fallback 密钥（无 env 覆盖时使用，弱保护）。 */
    public static final String MODEL_KEY_FALLBACK = "aioa-model-key-dev-only";

    /**
     * 模型密钥的取值来源环境变量候选（优先级由高到低）。
     * {@code ModelKeyCodec} 的读取与启动自检都引用此清单，避免两份候选列表漂移。
     */
    public static final List<String> MODEL_KEY_ENV_CANDIDATES = List.of(
            "AIOA_MODEL_KEY_ENC_KEY",
            "aioa.model.key.enc.key",
            "AIOA_GITEE_TOKEN_ENC_KEY",
            "aioa.gitee.token-enc-key");

    /** 是否为任一已知开发占位串（精确相等比对）。 */
    public static boolean isKnownPlaceholder(String v) {
        if (v == null) {
            return false;
        }
        return v.equals(JWT)
                || v.equals(SERVICE_JWT)
                || v.equals(GITEE_TOKEN_ENC)
                || v.equals(GITEA_TOKEN_ENC)
                || v.equals(MODEL_KEY_FALLBACK);
    }
}
