package cn.aioa.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 模型配置（管理端模型管理）：一条 = 一个可调用模型供应方。
 * 保存后由服务端推送 agent（/internal/v1/models/apply）热加载，变更即时生效。
 *
 * <p>V61 起支持「手动添加模型」：providerType 决定新增表单的预填项，
 * apiKey 存密文（见 ModelKeyCodec，列表接口只回掩码），temperature / maxContext 随配置下发生效。
 */
@TableName("model_config")
public class ModelConfig {

    public static final String DEFAULT_KEY = "echo";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String providerKey;

    /** 大模型类型：minimax / deepseek / dashscope / vllm / ollama / custom。 */
    private String providerType;

    private String name;

    private String baseUrl;

    private String modelName;

    private String apiKeyEnv;

    /** API Key 密文（ModelKeyCodec 加密）；为空表示仅走环境变量 apiKeyEnv。 */
    private String apiKey;

    /** 采样温度；null 时回落 agent 侧默认。 */
    private BigDecimal temperature;

    /** 最大上下文长度（token）；0/null 表示不限制。 */
    private Integer maxContext;

    private Boolean enabled;

    private Boolean isDefault;

    private Integer sort;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    public Long getId() { return id; }

    public String getProviderKey() { return providerKey; }

    public String getName() { return name; }

    public String getBaseUrl() { return baseUrl; }

    public String getModelName() { return modelName; }

    public String getProviderType() { return providerType; }

    public String getApiKeyEnv() { return apiKeyEnv; }

    public String getApiKey() { return apiKey; }

    public BigDecimal getTemperature() { return temperature; }

    public Integer getMaxContext() { return maxContext; }

    public Boolean getEnabled() { return enabled; }

    public Boolean getIsDefault() { return isDefault; }

    public Integer getSort() { return sort; }

    public LocalDateTime getCreatedAt() { return createdAt; }

    public LocalDateTime getUpdatedAt() { return updatedAt; }

    public Long getCreatedBy() { return createdBy; }

    public void setId(Long id) { this.id = id; }

    public void setProviderKey(String providerKey) { this.providerKey = providerKey; }

    public void setName(String name) { this.name = name; }

    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }

    public void setModelName(String modelName) { this.modelName = modelName; }

    public void setProviderType(String providerType) { this.providerType = providerType; }

    public void setApiKeyEnv(String apiKeyEnv) { this.apiKeyEnv = apiKeyEnv; }

    public void setApiKey(String apiKey) { this.apiKey = apiKey; }

    public void setTemperature(BigDecimal temperature) { this.temperature = temperature; }

    public void setMaxContext(Integer maxContext) { this.maxContext = maxContext; }

    public void setEnabled(Boolean enabled) { this.enabled = enabled; }

    public void setIsDefault(Boolean isDefault) { this.isDefault = isDefault; }

    public void setSort(Integer sort) { this.sort = sort; }

    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }

    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }

    public void setCreatedBy(Long createdBy) { this.createdBy = createdBy; }
}
