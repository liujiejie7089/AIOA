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
            String status = ready.ready() ? (conn == null ? ConnectorConnection.STATUS_NEED_AUTH : conn.getStatus())
                    : ConnectorConnection.STATUS_NEED_AUTH;
            items.add(new ConnectorItem(
                    def.getCode(), def.getName(), def.getGroupName(), def.getIcon(), def.getSummary(),
                    def.getAuthMode(), ready.ready(), status,
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

    private ConfigReady configReadyInternal(ConnectorDef def, Long tenantId) {
        if (ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            return new ConfigReady(true, null, ConfigSource.NONE);
        }
        WeComCredentials creds = resolveWeCom(tenantId);
        if (creds != null) {
            return new ConfigReady(true, null, creds.source());
        }
        return new ConfigReady(false, "缺少企业微信应用配置：corpId / agentId / corpSecret", ConfigSource.NONE);
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

    /** GET /connectors 单条。 */
    public record ConnectorItem(String code, String name, String group, String icon, String summary,
                               String authMode, boolean configReady, String status,
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
