package cn.aioa.admin.service;

import cn.aioa.admin.entity.ModelConfig;
import cn.aioa.admin.support.ModelKeyCodec;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 模型配置的前端视图：**绝不包含 API Key 明文**。
 *
 * <p>只暴露掩码 {@code apiKeyMasked} 与实际生效来源 {@code apiKeySource}
 * （DB = 管理端填写，ENV = 环境变量，NONE = 未配置），避免密钥经列表接口回显到浏览器。
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
        Integer maxContext,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) {

    public static final String SOURCE_DB = "DB";
    public static final String SOURCE_ENV = "ENV";
    public static final String SOURCE_NONE = "NONE";

    /**
     * 由实体 + 「可展示的密钥片段」构造（明文只用于生成掩码，不进入视图）。
     *
     * <p>source 由调用方判定：DB = 管理端填写，ENV = 环境变量（含 agent 侧已加载但本进程读不到的情况，
     * 此时 shownKey 为 null，UI 展示「已配置（环境变量）」而不是「未配置」）。
     */
    public static ModelConfigView of(ModelConfig cfg, String shownKey, String source) {
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
                cfg.getMaxContext(),
                cfg.getCreatedAt(),
                cfg.getUpdatedAt());
    }
}
