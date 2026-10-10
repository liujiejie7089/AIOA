package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.config.GiteeConfig;
import cn.aioa.gitee.config.PlatformConfigOverlay;
import cn.aioa.gitee.config.PlatformConfigOverlay.Field;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteePlatformConfig;
import cn.aioa.gitee.mapper.GiteePlatformConfigMapper;
import cn.aioa.gitee.support.GiteeCrypto;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 仓库联动<b>平台级参数</b>的读写与生效（管理端「系统配置 → 仓库配置」）。
 *
 * <p><b>为什么要它</b>：这些参数原先只能由环境变量注入；生产服务器在隧道机之后，
 * 改一次要动服务器上的 {@code deploy/.env} 并重建容器。本服务把其中「可运维」的 9 项
 * （见 {@link PlatformConfigOverlay.Field}）落到表 {@code gitee_platform_config}，
 * 保存即生效、无需重启。</p>
 *
 * <p><b>生效路径（唯一）</b>：{@link #save} / {@link #clear} → 重建 {@link PlatformConfigOverlay}
 * 的覆盖快照 → {@link RepoProviderSettings#isEnabled()} 等访问器立即读到新值。
 * 业务代码<b>一行都不用改</b>，因为它们本来就只认 {@code RepoProviderSettings} 端口。
 * 这也是为什么本服务不去直接改 {@code GiteeProperties}：那会造出「谁先读谁生效」的时序谜题。</p>
 *
 * <p><b>回落语义（逐字段）</b>：列为 NULL ⇒ 该字段回落环境变量；列为空串 ⇒ 生效值为空。
 * 见 {@code V77__gitee_platform_config.sql} 头部注释。</p>
 *
 * <p><b>安全</b>：Client Secret 落库前经 {@link GiteeCrypto} 加密（与访问令牌同规格），
 * 且本服务的任何视图<b>都不回传 Secret 明文</b>，只回「是否已配置」。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteePlatformConfigService {

    /** 合法组织 login：字母/数字/-/_/.，长度 1–128（与 Gitee 侧一致）。 */
    private static final Pattern ORG_PATTERN = Pattern.compile("^[A-Za-z0-9._-]{1,128}$");

    /** 必须同时具备的两个 scope —— 二者独立，缺一即功能静默失效。 */
    private static final String SCOPE_PROJECTS = "projects";
    private static final String SCOPE_HOOK = "hook";

    // ---- 视图键名（与前端契约；与实体字段同名的 camelCase）----
    private static final String K_ENABLED = "enabled";
    private static final String K_CLIENT_ID = "clientId";
    private static final String K_CLIENT_SECRET = "clientSecret";
    private static final String K_REDIRECT_URI = "redirectUri";
    private static final String K_OAUTH = "oauthAuthorizeBaseUrl";
    private static final String K_SCOPE = "scope";
    private static final String K_ORG = "org";
    private static final String K_WEBHOOK = "webhookBaseUrl";
    private static final String K_BIND = "bindReturnUrl";

    /** 视图键 → 覆盖层字段。顺序即界面顺序；两处口径由此单一来源保证一致。 */
    private static final Map<String, Field> KEYS = new LinkedHashMap<>();

    static {
        KEYS.put(K_ENABLED, Field.ENABLED);
        KEYS.put(K_CLIENT_ID, Field.CLIENT_ID);
        KEYS.put(K_CLIENT_SECRET, Field.CLIENT_SECRET);
        KEYS.put(K_REDIRECT_URI, Field.REDIRECT_URI);
        KEYS.put(K_OAUTH, Field.OAUTH_AUTHORIZE_BASE_URL);
        KEYS.put(K_SCOPE, Field.SCOPE);
        KEYS.put(K_ORG, Field.ORG);
        KEYS.put(K_WEBHOOK, Field.WEBHOOK_BASE_URL);
        KEYS.put(K_BIND, Field.BIND_RETURN_URL);
    }

    /**
     * 字段元信息（键 / 标签 / 控件类型 / 提示）。
     *
     * <p><b>为什么由后端给而不是前端写死</b>：字段集合是「后端能力」的一部分，
     * 前端再抄一份，就会出现「后端加了字段、前端漏渲染」——而这种缺口只在真机上才被发现。
     * 附带的好处是标签与提示跟校验规则同一处维护（例如 scope 必须含 hook 的说明）。</p>
     */
    private static final List<Map<String, Object>> FIELD_META = List.of(
            meta(K_ENABLED, "平台总开关", "BOOL",
                    "关闭后任务不入队、Webhook 不处理；各租户仍可另行关闭自己的开关"),
            meta(K_CLIENT_ID, "Client ID", "TEXT",
                    "Gitee「设置 → 第三方应用」详情页；非密文，可展示"),
            meta(K_CLIENT_SECRET, "Client Secret", "SECRET",
                    "登记页只显示一次。留空＝保持不变；要清空请点「清空密钥」"),
            meta(K_REDIRECT_URI, "OAuth 回调地址", "TEXT",
                    "须与第三方应用登记页逐字符一致；本地用 localhost，不要用 127.0.0.1"),
            meta(K_OAUTH, "授权跳转域", "TEXT",
                    "用户浏览器打开的授权页基址；真实 Gitee 为 https://gitee.com"),
            meta(K_SCOPE, "授权 scope", "TEXT",
                    "必须同时含 projects 与 hook：前者缺则建仓/读写被拒，后者缺则 Webhook 被拒"),
            meta(K_ORG, "平台默认组织", "TEXT",
                    "租户未自配组织时的回落值；留空＝仓库建在授权用户名下"),
            meta(K_WEBHOOK, "Webhook 回调基址", "TEXT",
                    "必须是托管方能访问到的公网地址；填 127.0.0.1/localhost 必然配置失败"),
            meta(K_BIND, "授权后回跳地址", "TEXT",
                    "绑定完成后前端跳转的页面地址")
    );

    private static Map<String, Object> meta(String key, String label, String type, String hint) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("key", key);
        m.put("label", label);
        m.put("type", type);
        m.put("hint", hint);
        return m;
    }

    private final GiteePlatformConfigMapper mapper;
    private final GiteeCrypto crypto;
    private final PlatformConfigOverlay overlay;
    private final RepoProviderSettings props;
    private final GiteeConfig giteeConfig;

    // ======================================================================
    // 加载与生效
    // ======================================================================

    /**
     * 启动加载。
     *
     * <p>放在 {@code @PostConstruct} 是为了尽量早生效；失败不抛（库/迁移未就绪时按环境变量运行），
     * 并另挂 {@link ApplicationReadyEvent} 再试一次兜底。</p>
     */
    @PostConstruct
    void bootLoad() {
        reloadQuietly("启动");
    }

    /** 上下文完全就绪后兜底再加载一次（幂等）。 */
    @EventListener(ApplicationReadyEvent.class)
    void readyLoad() {
        reloadQuietly("就绪");
    }

    /** 加载失败只告警：配置读不到时应按环境变量运行，而不是让整个应用起不来。 */
    private void reloadQuietly(String why) {
        try {
            reload(true);
        } catch (Exception e) {
            overlay.clear();
            log.warn("[gitee] 平台参数加载失败（{}），本次按环境变量运行：{}", why, e.toString());
        }
    }

    /**
     * 读库 → 解密 → 推入覆盖层，并打印一次**生效值**自检。
     *
     * @param logWiring 是否打印接线自检（启动与保存后打印；避免重复刷屏时可关）
     * @return 是否已有该 provider 的配置行
     */
    public synchronized boolean reload(boolean logWiring) {
        String provider = props.providerName();
        GiteePlatformConfig row = findByProvider(provider);
        List<String> warns = new ArrayList<>();
        applyOverlay(provider, row, warns);
        if (logWiring) {
            logWiring(warns);
        }
        return row != null;
    }

    /**
     * 把配置行（非 NULL 列）推入覆盖层。
     *
     * <p>解不开的密文<b>不视为覆盖</b>：那说明 {@code token-enc-key} 被改过，
     * 硬用会把「密钥不对」伪装成「配置为空」，反而更难查。此处降级为该字段回落环境变量并告警。</p>
     */
    private void applyOverlay(String provider, GiteePlatformConfig row, List<String> warns) {
        if (row == null) {
            overlay.clear();
            return;
        }
        Map<Field, String> m = new LinkedHashMap<>();
        if (row.getEnabled() != null) {
            m.put(Field.ENABLED, String.valueOf(row.getEnabled()));
        }
        put(m, Field.CLIENT_ID, row.getClientId());
        put(m, Field.REDIRECT_URI, row.getRedirectUri());
        put(m, Field.OAUTH_AUTHORIZE_BASE_URL, row.getOauthAuthorizeBaseUrl());
        put(m, Field.SCOPE, row.getScope());
        put(m, Field.ORG, row.getOrg());
        put(m, Field.WEBHOOK_BASE_URL, row.getWebhookBaseUrl());
        put(m, Field.BIND_RETURN_URL, row.getBindReturnUrl());
        if (row.getClientSecret() != null) {
            try {
                m.put(Field.CLIENT_SECRET, crypto.decrypt(row.getClientSecret()));
            } catch (Exception e) {
                warns.add("Client Secret 解密失败，已回落环境变量：" + e.getMessage());
            }
        }
        overlay.apply(provider, true, m);
    }

    private void put(Map<Field, String> m, Field f, String v) {
        if (v != null) {
            m.put(f, v);
        }
    }

    /** 打印**生效值**（而非环境变量值）——展示与事实必须同源，否则日志会把排查引偏。 */
    private void logWiring(List<String> warns) {
        int adminCount = overlay.coveredCount();
        log.info("[gitee] 接线(生效)：enabled={} api={} 授权跳转={}{} scope=\"{}\" org=\"{}\""
                        + " oauth={} 来源={}（管理端覆盖 {} 项）",
                props.isEnabled(),
                props.getBaseUrl(),
                props.getOauthAuthorizeBaseUrl(),
                props.authorizeHostIsSandbox() ? "  ⚠ 非官方站点（用户到不了真实站点）" : "",
                props.getScope(),
                StringUtils.hasText(props.getOrg()) ? props.getOrg() : "(空 → 建在授权用户名下)",
                props.oauthConfigured() ? "已配置" : "未配置",
                overlay.hasRow() ? "管理端+环境变量" : "环境变量",
                adminCount);
        giteeConfig.checkScope(props.isEnabled(), props.getScope());
        for (String w : warns) {
            log.warn("[gitee] {}", w);
        }
    }

    // ======================================================================
    // 视图
    // ======================================================================

    /**
     * 「仓库配置」页的平台参数视图。
     *
     * <p>每个字段都带 {@code source}（{@code ADMIN}=管理端填写 / {@code ENV}=环境变量），
     * 让运维一眼看清「这个值到底是谁给的」——这是本次改造要解决的核心困惑。</p>
     */
    public Map<String, Object> view() {
        String provider = props.providerName();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("provider", provider);
        m.put("providerLabel", props.providerLabel());
        m.put("configKey", props.configKeyPrefix());
        m.put("configured", overlay.hasRow());
        m.put("adminOverridden", overlay.coveredCount());
        m.put("fields", FIELD_META);

        Map<String, Object> values = new LinkedHashMap<>();
        for (Map.Entry<String, Field> e : KEYS.entrySet()) {
            values.put(e.getKey(), effectiveValue(e.getKey()));
        }
        // Secret 恒回空串：见类注释「安全」
        values.put(K_CLIENT_SECRET, "");
        m.put("values", values);

        // 是否已配置 Secret（唯一对外暴露的口径）
        m.put("clientSecretConfigured", props.clientSecretConfigured());
        m.put("oauthConfigured", props.oauthConfigured());

        Map<String, Object> sources = new LinkedHashMap<>();
        for (Map.Entry<String, Field> e : KEYS.entrySet()) {
            sources.put(e.getKey(), overlay.covers(e.getValue(), provider) ? "ADMIN" : "ENV");
        }
        m.put("sources", sources);

        List<String> warnings = new ArrayList<>();
        String scope = props.getScope() == null ? "" : props.getScope().trim();
        if (StringUtils.hasText(scope)) {
            List<String> parts = List.of(scope.split("\\s+"));
            if (!parts.contains(SCOPE_PROJECTS) || !parts.contains(SCOPE_HOOK)) {
                warnings.add("当前 scope 缺少「" + SCOPE_PROJECTS + "」或「" + SCOPE_HOOK + "」："
                        + "前者缺则建仓与读写文件被拒，后者缺则 Webhook 配置被拒。");
            }
        }
        if (props.isEnabled() && !props.oauthConfigured()) {
            warnings.add("已启用但 OAuth 尚未配齐（" + props.getClientId() + " / Secret）："
                    + "个人「绑定账号」入口会直接报错，但建仓与成员同步可用。");
        }
        m.put("warnings", warnings);
        return m;
    }

    /** 某字段的**生效值**（读端口，不读属性对象）——保证与业务代码看到的是同一个值。 */
    private Object effectiveValue(String key) {
        switch (key) {
            case K_ENABLED: return props.isEnabled();
            case K_CLIENT_ID: return props.getClientId();
            case K_CLIENT_SECRET: return "";
            case K_REDIRECT_URI: return props.getRedirectUri();
            case K_OAUTH: return props.getOauthAuthorizeBaseUrl();
            case K_SCOPE: return props.getScope();
            case K_ORG: return props.getOrg();
            case K_WEBHOOK: return props.getWebhookBaseUrl();
            case K_BIND: return props.getBindReturnUrl();
            default: return "";
        }
    }

    // ======================================================================
    // 保存 / 清除
    // ======================================================================

    /**
     * 保存（upsert）平台参数。
     *
     * <p><b>逐字段语义</b>：body 里<b>出现的键</b>才会被写入（含空串＝显式清空）；
     * <b>没出现的键保持原值</b>。前端因此可以把表单里没动过的字段原样回传，
     * 而 Secret 留空时不回传即可保持原密文。</p>
     *
     * @param body        形如 {@code {enabled, clientId, clientSecret, redirectUri, ...}}
     * @param actorUserId 操作人
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> save(Map<String, Object> body, Long actorUserId) {
        if (body == null || body.isEmpty()) {
            throw BizException.badRequest("请求体不能为空");
        }
        String provider = props.providerName();
        GiteePlatformConfig row = findByProvider(provider);
        boolean created = row == null;
        if (created) {
            row = new GiteePlatformConfig();
            row.setProvider(provider);
        }

        if (body.containsKey(K_ENABLED)) {
            row.setEnabled(asBool(body.get(K_ENABLED)));
        }
        if (body.containsKey(K_CLIENT_ID)) {
            row.setClientId(text(body.get(K_CLIENT_ID)));
        }
        if (body.containsKey(K_CLIENT_SECRET)) {
            String s = text(body.get(K_CLIENT_SECRET));
            // 空串 = 显式清除（"清除密钥"由前端显式发送空串，而不是「没填」——没填就不在 body 里）
            row.setClientSecret(s.isEmpty() ? "" : crypto.encrypt(s));
        }
        if (body.containsKey(K_REDIRECT_URI)) {
            row.setRedirectUri(text(body.get(K_REDIRECT_URI)));
        }
        if (body.containsKey(K_OAUTH)) {
            row.setOauthAuthorizeBaseUrl(text(body.get(K_OAUTH)));
        }
        if (body.containsKey(K_SCOPE)) {
            row.setScope(text(body.get(K_SCOPE)));
        }
        if (body.containsKey(K_ORG)) {
            row.setOrg(text(body.get(K_ORG)));
        }
        if (body.containsKey(K_WEBHOOK)) {
            row.setWebhookBaseUrl(text(body.get(K_WEBHOOK)));
        }
        if (body.containsKey(K_BIND)) {
            row.setBindReturnUrl(text(body.get(K_BIND)));
        }

        validate(row);
        row.setUpdatedBy(actorUserId);
        if (created) {
            mapper.insert(row);
            log.info("[gitee] 已写入平台参数 provider={}", provider);
        } else {
            mapper.updateById(row);
            log.info("[gitee] 已更新平台参数 provider={}", provider);
        }
        return reloadAndView();
    }

    /**
     * 清除平台参数（删行），9 个字段全部交还环境变量。
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> clear() {
        String provider = props.providerName();
        GiteePlatformConfig row = findByProvider(provider);
        if (row != null) {
            mapper.deleteById(row.getId());
            log.info("[gitee] 已清除平台参数 provider={}（改由环境变量提供）", provider);
        }
        return reloadAndView();
    }

    /** 保存/清除后立即重建覆盖层并回视图——避免「保存成功但页面还是旧值」。 */
    private Map<String, Object> reloadAndView() {
        reload(false);
        return view();
    }

    // ======================================================================
    // 校验
    // ======================================================================

    /**
     * 强校验。
     *
     * <p><b>为什么 scope 缺失要直接拒绝</b>：Gitee 的 {@code hook} 是独立 scope，
     * 缺它不会报错，只会「建仓成功、Webhook 被拒」，且失败点离配置点很远（本项目已实测两次）。
     * 配置页是这类参数的唯一入口，在这里拦住比在生产上以「Webhook 怎么不触发」出现要好。</p>
     */
    private void validate(GiteePlatformConfig row) {
        if (StringUtils.hasText(row.getClientId()) && row.getClientId().length() > 128) {
            throw BizException.badRequest("Client ID 过长（>128）");
        }
        checkUrl(row.getRedirectUri(), "OAuth 回调地址");
        checkUrl(row.getOauthAuthorizeBaseUrl(), "授权跳转域");
        checkUrl(row.getWebhookBaseUrl(), "Webhook 回调基址");
        checkUrl(row.getBindReturnUrl(), "授权后回跳地址");
        if (StringUtils.hasText(row.getOrg()) && !ORG_PATTERN.matcher(row.getOrg()).matches()) {
            throw BizException.badRequest(props.providerLabel()
                    + " 组织名非法（仅允许字母/数字/-/_/.，长度 1–128）：" + row.getOrg());
        }
        String scope = row.getScope();
        if (StringUtils.hasText(scope)) {
            List<String> parts = List.of(scope.trim().split("\\s+"));
            if (!parts.contains(SCOPE_PROJECTS) || !parts.contains(SCOPE_HOOK)) {
                throw BizException.badRequest("scope 必须同时包含 " + SCOPE_PROJECTS + " 与 " + SCOPE_HOOK
                        + "（当前：" + scope + "）。Gitee 的 " + SCOPE_HOOK + " 是独立 scope，"
                        + "不会被 " + SCOPE_PROJECTS + " 顺带授予；缺它会导致「建仓成功但 Webhook 配置被拒」。");
            }
        }
    }

    /** 非空的 URL 字段必须是 http(s) 绝对地址（否则会在调用时才炸，且报错离配置点很远）。 */
    private void checkUrl(String v, String label) {
        if (!StringUtils.hasText(v)) {
            return;
        }
        String s = v.trim();
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            throw BizException.badRequest(label + " 必须是 http:// 或 https:// 开头的绝对地址：" + s);
        }
    }

    // ======================================================================
    // 内部
    // ======================================================================

    private GiteePlatformConfig findByProvider(String provider) {
        if (!StringUtils.hasText(provider)) {
            return null;
        }
        return mapper.selectOne(new LambdaQueryWrapper<GiteePlatformConfig>()
                .eq(GiteePlatformConfig::getProvider, provider)
                .last("limit 1"));
    }

    private static String text(Object v) {
        return v == null ? "" : String.valueOf(v).trim();
    }

    private static Boolean asBool(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof Boolean b) {
            return b;
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) {
            return null;
        }
        if ("1".equals(s) || "true".equalsIgnoreCase(s)) {
            return Boolean.TRUE;
        }
        if ("0".equals(s) || "false".equalsIgnoreCase(s)) {
            return Boolean.FALSE;
        }
        throw BizException.badRequest("开关取值非法（应为 true/false）：" + s);
    }
}
