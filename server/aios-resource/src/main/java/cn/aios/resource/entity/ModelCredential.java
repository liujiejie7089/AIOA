package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 模型账号（凭证）：一把可调用的 Key + 它的归属。
 *
 * <p><b>为什么另立一张表而不复用 {@code model_config}</b>：{@code model_config} 是
 * <b>全局单份</b>（无 tenant_id、无属主），表达的是「平台级默认通道」；
 * 而账号是「某个人的私产」—— 需要租户隔离、需要属主、需要能被邀请共享，
 * 三件事 {@code model_config} 一件都做不到。</p>
 *
 * <p><b>密钥存密文</b>（{@code api_key_cipher}，AES-256-GCM，见 {@code SecretCodec}）。
 * 与 {@code model_config} 的「Key 只驻留 agent 内存」不同：那是平台配置、可由运维重新下发；
 * 这是用户资产，重启后必须还能读出来用。</p>
 */
@Data
@TableName("model_credential")
public class ModelCredential {

    /** 用户自行在供应商注册的账号：供应商侧计费，公司不收费。 */
    public static final String OWNER_PERSONAL = "PERSONAL";

    /** 公司统一采购/提供的账号：走公司额度，公司收费。 */
    public static final String OWNER_COMPANY = "COMPANY";

    public static final String STATUS_ENABLED = "ENABLED";
    public static final String STATUS_DISABLED = "DISABLED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** PERSONAL / COMPANY */
    private String ownerType;

    /** PERSONAL 必填（注册人 = 主账号持有人 = 共享时的承担人）；COMPANY 为 NULL */
    private Long ownerUserId;

    /** 与 agent provider 注册表对齐：deepseek / dashscope / vllm / ollama / minimax */
    private String providerKey;

    private String providerType;

    private String name;

    /** 空 = 回退 provider 注册表 */
    private String baseUrl;

    /** 空 = 回退 provider 注册表 */
    private String modelName;

    // ---- 采样 / 传输参数（2026-11-04，docs/72）：与平台 model_config 同名同义 ----
    // 未填 = 继承平台该 provider 的配置（agent 侧 _apply_credential 按缺省回落）

    private java.math.BigDecimal temperature;

    /** 核采样；null = 不下发，沿用供应商默认 */
    private java.math.BigDecimal topP;

    /** 单次回复上限；0 = 不下发 */
    private Integer maxTokens;

    /** 上下文窗口；0 = 不限制 */
    private Integer maxContext;

    private java.math.BigDecimal presencePenalty;

    private java.math.BigDecimal frequencyPenalty;

    /** 单次上游请求超时（秒） */
    private Integer timeoutSeconds;

    /** 总尝试次数（含首次） */
    private Integer retryAttempts;

    /** 是否流式输出 */
    private Boolean streamEnabled;

    /** SecretCodec 密文（enc: 前缀）；任何接口都不回传明文 */
    private String apiKeyCipher;

    /** 掩码 sk-****3f9a，仅用于辨认是哪把 Key */
    private String keyHint;

    /** 是否允许邀请同事共用 */
    private Integer shareEnabled;

    private String status;

    private String remark;

    private LocalDateTime createdAt;

    private Long createdBy;

    private LocalDateTime updatedAt;

    private Long updatedBy;

    @TableLogic
    private LocalDateTime deletedAt;

    // ---------- 领域判断（唯一判定点，Controller/Service 不再各写一份） ----------

    public boolean isCompany() {
        return OWNER_COMPANY.equalsIgnoreCase(ownerType);
    }

    public boolean isEnabled() {
        return STATUS_ENABLED.equalsIgnoreCase(status);
    }

    public boolean shareAllowed() {
        return shareEnabled != null && shareEnabled == 1;
    }

    /**
     * 是否公司收费 —— <b>由账号来源推导，绝不接受前端传参</b>。
     * 前端能传就能伪造账单口径；这个值只允许从 ownerType 出来。
     */
    public boolean companyCharged() {
        return isCompany();
    }

    /**
     * 平台侧的承担人：PERSONAL = 账号持有人；COMPANY = 0（公司池）。
     * 同样由来源推导，不接受外部输入。
     */
    public Long chargeUserId() {
        return isCompany() ? 0L : ownerUserId;
    }
}
