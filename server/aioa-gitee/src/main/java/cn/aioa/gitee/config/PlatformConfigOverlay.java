package cn.aioa.gitee.config;

import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 平台级参数的<b>内存覆盖层</b>：管理端保存的值从这里被 {@link RepoProviderSettingsAdapter} 读到。
 *
 * <p><b>为什么单独抽一个「哑」持有者，而不是让适配器直接依赖配置服务</b>：
 * 配置服务要用 {@code GiteeCrypto} 解密 Client Secret，而 {@code GiteeCrypto} 的密钥又来自
 * {@link RepoProviderSettings}（即适配器）——适配器若再依赖服务，就构成
 * 适配器 → 服务 → 加密器 → 适配器 的**循环依赖**。把值放进这个不含任何依赖的持有者后，
 * 依赖方向变成单向：服务 → 覆盖层 ← 适配器。</p>
 *
 * <p><b>★ 语义（逐字段）</b>：只有「本表里<b>非 NULL</b>的列」才进入覆盖层，逐字段替换环境变量的值；
 * <b>列为 NULL ⇒ 该字段回落环境变量</b>；列为空串是**有效值**（表示「管理端显式清空」）。
 * 之所以是逐字段而不是整体：整体覆盖会让「首次保存时没填的密钥把环境变量的值静默遮蔽」，
 * 那是一个用户完全看不见的数据丢失。</p>
 *
 * <p>并发：写入只发生在启动加载与保存之后，读取发生在请求线程。字段用 {@code volatile}
 * 发布一个**不可变** Map，读到的一定是某一版完整快照，不会看到「改了一半」的中间态。</p>
 */
@Component
public class PlatformConfigOverlay {

    /** 可被管理端覆盖的字段（与 {@code gitee_platform_config} 列一一对应）。 */
    public enum Field {
        ENABLED,
        CLIENT_ID,
        CLIENT_SECRET,
        REDIRECT_URI,
        OAUTH_AUTHORIZE_BASE_URL,
        SCOPE,
        ORG,
        WEBHOOK_BASE_URL,
        BIND_RETURN_URL
    }

    /**
     * 全部字段名（供静态断言与文档共用，避免两处各写一份）。
     *
     * <p><b>刻意用 camelCase（与实体字段、接口 JSON、前端 {@code GiteePlatformFieldKey} 同一套词表）</b>：
     * 三处若各用各的命名（实体 camelCase / yml 用 kebab），静态断言就只能按顺序对齐，
     * 而顺序是最容易被无声改动的。env / yml 那侧的 kebab 键（{@code client-id} 等）属于部署口径，
     * 见 {@code V77} 与 {@code deploy/ENV.md}。</p>
     */
    public static final String[] FIELD_NAMES = {
            "enabled", "clientId", "clientSecret", "redirectUri", "oauthAuthorizeBaseUrl",
            "scope", "org", "webhookBaseUrl", "bindReturnUrl"
    };

    /** 是否已存在该 provider 的配置行（决定界面显示「管理端已配置」还是「全部来自环境变量」）。 */
    private volatile boolean rowExists = false;

    private volatile String provider = "";

    private volatile Map<Field, String> covered = Map.of();

    /** 是否已存在该 provider 的配置行。 */
    public boolean hasRow() {
        return rowExists;
    }

    /** 生效配置所属的托管方（用于防止切换 provider 后张冠李戴）。 */
    public String ownerProvider() {
        return provider;
    }

    /** 当前被管理端覆盖的字段数（界面与启动自检都拿它报「管理端覆盖了几项」）。 */
    public int coveredCount() {
        return covered.size();
    }

    /**
     * 该字段是否应改用覆盖值。
     *
     * @param activeProvider 当前生效的托管方标识；与写入来源不一致时一律返回 false（回落 env），
     *                       避免「表里存的是 gitee 的值，却拿去当 gitea 的配置用」
     */
    public boolean covers(Field f, String activeProvider) {
        return covered.containsKey(f)
                && provider.equalsIgnoreCase(activeProvider == null ? "" : activeProvider.trim());
    }

    /**
     * 取覆盖值。
     *
     * @return 覆盖值（可能是空串）；调用方**必须先**用 {@link #covers} 判断，
     *         否则会拿到未定义的回落语义
     */
    public String get(Field f) {
        String v = covered.get(f);
        return v == null ? "" : v;
    }

    /**
     * 载入一版覆盖（仅含非 NULL 列）。
     *
     * @param ownerProvider 行的 provider
     * @param rowExists     该 provider 是否已有配置行
     * @param values        「非 NULL 列 → 值」；null 视为无覆盖
     */
    public void apply(String ownerProvider, boolean rowExists, Map<Field, String> values) {
        Map<Field, String> copy = new LinkedHashMap<>();
        if (values != null) {
            copy.putAll(values);
        }
        this.provider = ownerProvider == null ? "" : ownerProvider.trim();
        this.rowExists = rowExists;
        this.covered = Map.copyOf(copy);
    }

    /** 清除覆盖（删除行 / 加载失败时调用）⇒ 适配器全部回落环境变量。 */
    public void clear() {
        this.covered = Map.of();
        this.provider = "";
        this.rowExists = false;
    }
}
