package cn.aios.resource.connector.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.config.ConnectorProperties;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.entity.ConnectorTenantConfig;
import cn.aios.resource.connector.mapper.ConnectorConnectionMapper;
import cn.aios.resource.connector.mapper.ConnectorDefMapper;
import cn.aios.resource.connector.mapper.ConnectorTenantConfigMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 连接器目录：清单 / 配置就绪度 / 详情（docs/58 §4）。
 *
 * <p><b>配置就绪度（configReady）判定只在这一处</b>：</p>
 * <ul>
 *   <li>CREDENTIAL（QQ 邮箱）：恒 true —— 用户用自己的授权码，不需要应用级凭据；</li>
 *   <li>OAUTH2（企业微信）：先取租户级 {@code connector_tenant_config.secret_json}（enabled=1），
 *       否则回退平台级 {@code aios.connector.wechat-work.*}；corpId/agentId/corpSecret 三者都非空才就绪。</li>
 * </ul>
 *
 * <p><b>状态只读 connection 表</b>：configReady=false 时无论是否已连都强制 {@code NEED_AUTH} +
 * 附 {@code configHint}（缺哪个键），绝不返回假的已连接。</p>
 */
@Slf4j
@Service
public class ConnectorCatalogService {

    private static final String WECHAT_WORK = "wechat_work";

    private final ConnectorDefMapper defMapper;
    private final ConnectorTenantConfigMapper tenantConfigMapper;
    private final ConnectorConnectionMapper connectionMapper;
    private final ConnectorProperties props;
    private final SecretCodec secretCodec;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ConnectorCatalogService(ConnectorDefMapper defMapper,
                                   ConnectorTenantConfigMapper tenantConfigMapper,
                                   ConnectorConnectionMapper connectionMapper,
                                   ConnectorProperties props,
                                   SecretCodec secretCodec) {
        this.defMapper = defMapper;
        this.tenantConfigMapper = tenantConfigMapper;
        this.connectionMapper = connectionMapper;
        this.props = props;
        this.secretCodec = secretCodec;
    }

    /** GET /connectors：一次拿全目录 + 我的连接状态 + 配置就绪度（避免 N+1）。 */
    public List<ConnectorItem> list(Long tenantId, Long userId) {
        List<ConnectorDef> defs = defMapper.selectList(new LambdaQueryWrapper<ConnectorDef>()
                .eq(ConnectorDef::getTenantId, 0L)
                .eq(ConnectorDef::getStatus, ConnectorDef.STATUS_ACTIVE)
                .orderByAsc(ConnectorDef::getSort));

        Map<String, ConnectorConnection> connByCode = connectionMapper.selectList(
                        new LambdaQueryWrapper<ConnectorConnection>()
                                .eq(ConnectorConnection::getTenantId, tenantId)
                                .eq(ConnectorConnection::getUserId, userId))
                .stream().collect(Collectors.toMap(ConnectorConnection::getConnectorCode, c -> c, (a, b) -> a));

        List<ConnectorItem> items = new ArrayList<>();
        for (ConnectorDef def : defs) {
            ConfigReady ready = configReadyInternal(def, tenantId);
            ConnectorConnection conn = connByCode.get(def.getCode());
            // 连接态只信库：connector_connection 是唯一真相源（hub 授权成功后回写，见 docs/63 §9.2）。
            // 别再用 ready 门把状态强降级成 NEED_AUTH —— 那会让「manifest 已放行、界面却显示未连接」
            // 自相矛盾（2026-10-30 实测：S5 通过而 S4 失败）。应用配置就绪度是另一根轴，
            // 由 configReady/configHint 单独表达，前端本就按 configReady 先分支（_oa_app.js connStatusChip）。
            String status = conn == null ? ConnectorConnection.STATUS_NEED_AUTH : conn.getStatus();
            items.add(new ConnectorItem(
                    def.getCode(), def.getName(), def.getGroupName(), def.getIcon(), def.getSummary(),
                    def.getAuthMode(), ready.ready(), ready.ready() ? null : ready.hint(), status,
                    conn == null ? null : conn.getAccountLabel(),
                    conn == null ? null : conn.getConnectedAt(),
                    conn == null ? null : conn.getLastCheckedAt(),
                    conn == null ? null : conn.getLastError(),
                    ready.source() == ConfigSource.PLATFORM));
        }
        return items;
    }

    /** GET /connectors/{code}：用途 / 授权说明 / 需要填什么 / 帮助链接。 */
    public ConnectorDetail detail(String code, Long tenantId) {
        ConnectorDef def = requireDef(code);
        List<ConnectorField> fields = List.of();
        if (ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            fields = credentialFields(def.getCode());
        }
        return new ConnectorDetail(def.getCode(), def.getName(), def.getGroupName(), def.getIcon(),
                def.getSummary(), def.getAuthMode(), fields, def.getHelpText(), def.getHelpUrl());
    }

    /**
     * 授权形态（OAUTH2 / CREDENTIAL / API_KEY），供 MCP 闸门区分「谁负责授权」：
     * 前两者按用户连接态判，API_KEY 按租户配置就绪度判。未知 code 返回 null。
     */
    public String authMode(String code) {
        if (code == null || code.isBlank()) {
            return null;
        }
        return activeDefs().stream()
                .filter(d -> code.equals(d.getCode()))
                .map(ConnectorDef::getAuthMode)
                .findFirst()
                .orElse(null);
    }

    /** 配置就绪度（对外）。未就绪时 hint 指出缺哪个键。 */
    public ConfigReadyResult configReady(String code, Long tenantId) {
        ConnectorDef def = requireDef(code);
        ConfigReady r = configReadyInternal(def, tenantId);
        return new ConfigReadyResult(r.ready(), r.hint());
    }

    /** 取 OAUTH2 应用凭据（租户级优先，平台级兜底）。null = 无可用配置。供 WeComOAuthService 复用。 */
    public WeComCredentials resolveWeCom(Long tenantId) {
        ConnectorTenantConfig tc = tenantConfigMapper.selectOne(new LambdaQueryWrapper<ConnectorTenantConfig>()
                .eq(ConnectorTenantConfig::getTenantId, tenantId)
                .eq(ConnectorTenantConfig::getConnectorCode, WECHAT_WORK));
        if (tc != null && Boolean.TRUE.equals(tc.getEnabled())
                && tc.getSecretJson() != null && !tc.getSecretJson().isBlank()) {
            try {
                String json = secretCodec.decrypt(tc.getSecretJson());
                JsonNode node = objectMapper.readTree(json);
                String corpId = text(node, "corpId");
                String agentId = text(node, "agentId");
                String corpSecret = text(node, "corpSecret");
                if (allNotBlank(corpId, agentId, corpSecret)) {
                    return new WeComCredentials(corpId, agentId, corpSecret, ConfigSource.TENANT);
                }
            } catch (Exception e) {
                log.warn("企业微信租户配置解密/解析失败，回退平台配置: {}", e.getMessage());
            }
        }
        ConnectorProperties.WeChatWork ww = props.getWechatWork();
        if (allNotBlank(ww.getCorpId(), ww.getAgentId(), ww.getCorpSecret())) {
            return new WeComCredentials(ww.getCorpId(), ww.getAgentId(), ww.getCorpSecret(),
                    ConfigSource.PLATFORM);
        }
        return null;
    }

    /** CREDENTIAL 连接器的字段声明（前端弹层渲染用）。 */
    public List<ConnectorField> credentialFields(String code) {
        if ("qq_mail".equals(code)) {
            return List.of(
                    new ConnectorField("email", "text", "QQ 邮箱地址", true, "123456789@qq.com",
                            "用于接收与发送邮件的 QQ 邮箱"),
                    new ConnectorField("authCode", "password", "IMAP/SMTP 授权码", true, "",
                            "QQ邮箱→设置→账户→开启 IMAP/SMTP 服务→生成授权码"));
        }
        return List.of();
    }

    public ConnectorDef requireDef(String code) {
        ConnectorDef def = defMapper.selectOne(new LambdaQueryWrapper<ConnectorDef>()
                .eq(ConnectorDef::getTenantId, 0L)
                .eq(ConnectorDef::getCode, code));
        if (def == null) {
            throw BizException.notFound("连接器不存在：" + code);
        }
        return def;
    }

    /** 连接器的应用级配置项（来自 connector_def.config_keys，JSON 数组文本）。
     *  空列表 = 该连接器没有应用级凭据（如 QQ 邮箱走用户自填授权码）。 */
    public List<String> configKeys(String code) {
        ConnectorDef def = requireDef(code);
        String raw = def.getConfigKeys();
        if (raw == null || raw.isBlank()) {
            return List.of();
        }
        try {
            JsonNode arr = objectMapper.readTree(raw);
            List<String> out = new java.util.ArrayList<>();
            if (arr.isArray()) {
                for (JsonNode n : arr) {
                    if (n.isTextual() && !n.asText().isBlank()) {
                        out.add(n.asText().trim());
                    }
                }
            }
            return out;
        } catch (Exception e) {
            log.warn("config_keys 解析失败 code={} raw={}：{}", code, raw, e.getMessage());
            return List.of();
        }
    }

    /** 平台级连接器目录（tenant_id=0 且 ACTIVE），供管理端配置页枚举。 */
    public List<ConnectorDef> activeDefs() {
        return defMapper.selectList(new LambdaQueryWrapper<ConnectorDef>()
                .eq(ConnectorDef::getTenantId, 0L)
                .eq(ConnectorDef::getStatus, ConnectorDef.STATUS_ACTIVE)
                .orderByAsc(ConnectorDef::getSort));
    }

    private ConfigReady configReadyInternal(ConnectorDef def, Long tenantId) {
        if (ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            return new ConfigReady(true, null, ConfigSource.NONE);
        }
        List<String> keys = configKeys(def.getCode());
        if (keys.isEmpty()) {
            return new ConfigReady(true, null, ConfigSource.NONE);
        }
        ConnectorTenantConfig tc = tenantConfigMapper.selectOne(new LambdaQueryWrapper<ConnectorTenantConfig>()
                .eq(ConnectorTenantConfig::getTenantId, tenantId)
                .eq(ConnectorTenantConfig::getConnectorCode, def.getCode()));
        if (tc != null && Boolean.TRUE.equals(tc.getEnabled())
                && tc.getSecretJson() != null && !tc.getSecretJson().isBlank()) {
            try {
                JsonNode node = objectMapper.readTree(secretCodec.decrypt(tc.getSecretJson()));
                boolean complete = keys.stream().allMatch(k -> !text(node, k).isBlank());
                if (complete) {
                    return new ConfigReady(true, null, ConfigSource.TENANT);
                }
            } catch (Exception e) {
                log.warn("连接器 {} 租户配置解密/解析失败：{}", def.getCode(), e.getMessage());
            }
        }
        // 平台级兜底只对内置的企业微信成立（ConnectorProperties 里只有企微三件套）
        if (WECHAT_WORK.equals(def.getCode())) {
            WeComCredentials creds = resolveWeCom(tenantId);
            if (creds != null) {
                return new ConfigReady(true, null, creds.source());
            }
        }
        return new ConfigReady(false, "缺少应用配置：" + String.join(" / ", keys), ConfigSource.NONE);
    }

    private static String text(JsonNode node, String key) {
        JsonNode v = node.get(key);
        return v == null || v.isNull() ? null : v.asText();
    }

    private static boolean allNotBlank(String... vals) {
        for (String v : vals) {
            if (v == null || v.isBlank()) {
                return false;
            }
        }
        return true;
    }

    // ---------------- 响应 / 内部 DTO ----------------

    /** GET /connectors 单条。configHint = 应用配置未就绪时缺什么（就绪则为 null）。 */
    public record ConnectorItem(String code, String name, String group, String icon, String summary,
                               String authMode, boolean configReady, String configHint, String status,
                               String accountLabel, java.time.LocalDateTime connectedAt,
                               java.time.LocalDateTime lastCheckedAt, String lastError,
                               boolean isPlatformManaged) {
    }

    /** GET /connectors/{code} 详情。 */
    public record ConnectorDetail(String code, String name, String group, String icon, String summary,
                                 String mode, List<ConnectorField> fields, String helpText,
                                 String helpUrl) {
    }

    /** CREDENTIAL 字段声明。 */
    public record ConnectorField(String key, String type, String label, boolean required,
                                String placeholder, String helpText) {
    }

    /** connect/start 返回（CREDENTIAL 给 fields，OAUTH2 给 authUrl）。 */
    public record ConnectorStart(String mode, String authUrl, List<ConnectorField> fields) {
    }

    /** configReady 对外结果。 */
    public record ConfigReadyResult(boolean ready, String hint) {
    }

    /** 企业微信应用凭据（含来源）。 */
    public record WeComCredentials(String corpId, String agentId, String corpSecret, ConfigSource source) {
    }

    private record ConfigReady(boolean ready, String hint, ConfigSource source) {
    }

    enum ConfigSource {
        PLATFORM, TENANT, NONE
    }
}
