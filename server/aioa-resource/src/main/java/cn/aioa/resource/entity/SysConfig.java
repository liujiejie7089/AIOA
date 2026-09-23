package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 系统参数配置（V18）：管理端面向租户管理员的运行期可调参数。
 * 参数键租户内唯一；数值型带 min/max 校验；default_value 用于「恢复默认」。
 */
@Data
@TableName("sys_config")
public class SysConfig {

    public static final String GROUP_CONVERSATION = "CONVERSATION";
    public static final String GROUP_QUOTA = "QUOTA";
    public static final String GROUP_KNOWLEDGE = "KNOWLEDGE";
    public static final String GROUP_SECURITY = "SECURITY";
    public static final String GROUP_COMMON = "COMMON";

    public static final String TYPE_INT = "INT";
    public static final String TYPE_DECIMAL = "DECIMAL";
    public static final String TYPE_BOOL = "BOOL";
    public static final String TYPE_STRING = "STRING";
    public static final String TYPE_JSON = "JSON";

    /**
     * 「默认 AI」参数键：用户端**未选择任何专家**时的兜底对象，取值为 {@code ai_expert.expert_key}。
     *
     * <p>单一事实源：迁移 V62 写入参数行、{@code AdminConfigController.BUILTIN_DEFAULTS} 写入
     * 出厂兜底、{@code CatalogService} 读取并标记 —— 三处必须引用本常量，不得各写字符串字面量。</p>
     */
    public static final String KEY_DEFAULT_EXPERT = "chat.default_expert_key";

    /** {@link #KEY_DEFAULT_EXPERT} 的出厂取值：V62 内置的全局专家 {@code general}。 */
    public static final String DEFAULT_EXPERT_KEY = "general";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 参数键（租户内唯一） */
    private String configKey;

    /** 参数值（统一以字符串存储） */
    private String configValue;

    /** INT / DECIMAL / BOOL / STRING / JSON */
    private String valueType;

    /** CONVERSATION / QUOTA / KNOWLEDGE / SECURITY / COMMON */
    private String groupCode;

    private String configName;

    private String description;

    /** 单位：轮 / 秒 / % / MB / 年 …… */
    private String unit;

    private String defaultValue;

    private BigDecimal minValue;

    private BigDecimal maxValue;

    /** 是否允许管理端修改 */
    private Boolean editable;

    private Integer sortNo;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
