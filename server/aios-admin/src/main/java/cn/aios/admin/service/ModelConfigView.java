package cn.aios.admin.service;

import cn.aios.admin.entity.ModelConfig;
import cn.aios.admin.support.ModelKeyCodec;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 模型配置的前端视图：**绝不包含 API Key 明文**。
 *
 * <p>只暴露掩码 {@code apiKeyMasked} 与实际生效来源 {@code apiKeySource}
 * （DB = 管理端填写，ENV = 环境变量，NONE = 未配置），避免密钥经列表接口回显到浏览器。
 *
 * <p>2026-11-04（docs/72）：补齐与用户端模型账号**同名同义**的采样/传输参数，
 * 并用 {@code syncState} 回执本次保存是否已热更新到 agent（SYNCED / PENDING）。
 */
public record ModelConfigView(
        Long id,
        String providerKey,
        String providerType,
        String name,
        String baseUrl,
        String modelName,
        String apiKeyEnv,
        String apiKeyMasked,
        String apiKeySource,
        Boolean enabled,
        Boolean isDefault,
        Integer sort,
        BigDecimal temperature,
        BigDecimal topP,
        Integer maxTokens,
        BigDecimal presencePenalty,
        BigDecimal frequencyPenalty,
        Integer maxContext,
        Integer timeoutSeconds,
        Integer retryAttempts,
        Boolean streamEnabled,
        LocalDateTime createdAt,
        LocalDateTime updatedAt,
        String syncState
) {

    public static final String SOURCE_DB = "DB";
    public static final String SOURCE_ENV = "ENV";
    public static final String SOURCE_NONE = "NONE";

    /** 已热更新到 agent。 */
    public static final String SYNCED = "SYNCED";

    /** 已落库但未推送成功（agent 离线），下次保存或点「同步」即可补上。 */
    public static final String PENDING = "PENDING";

    /**
     * 由实体 + 「可展示的密钥片段」构造（明文只用于生成掩码，不进入视图）。
     *
     * <p>source 由调用方判定：DB = 管理端填写，ENV = 环境变量（含 agent 侧已加载但本进程读不到的情况，
     * 此时 shownKey 为 null，UI 展示「已配置（环境变量）」而不是「未配置」）。
     */
    public static ModelConfigView of(ModelConfig cfg, String shownKey, String source) {
        return of(cfg, shownKey, source, SYNCED);
    }

    public static ModelConfigView of(ModelConfig cfg, String shownKey, String source, String syncState) {
        return new ModelConfigView(
                cfg.getId(),
                cfg.getProviderKey(),
                cfg.getProviderType(),
                cfg.getName(),
                cfg.getBaseUrl(),
                cfg.getModelName(),
                cfg.getApiKeyEnv(),
                ModelKeyCodec.mask(shownKey),
                source,
                cfg.getEnabled(),
                cfg.getIsDefault(),
                cfg.getSort(),
                cfg.getTemperature(),
                cfg.getTopP(),
                cfg.getMaxTokens(),
                cfg.getPresencePenalty(),
                cfg.getFrequencyPenalty(),
                cfg.getMaxContext(),
                cfg.getTimeoutSeconds(),
                cfg.getRetryAttempts(),
                cfg.getStreamEnabled(),
                cfg.getCreatedAt(),
                cfg.getUpdatedAt(),
                syncState);
    }
}
