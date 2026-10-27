package cn.aios.resource.connector.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.entity.ConnectorTenantConfig;
import cn.aios.resource.connector.mapper.ConnectorTenantConfigMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 租户级连接器配置管理（docs/58 §5：{@code connector_tenant_config.secret_json}）。
 *
 * <p>让「待管理员配置」可以在管理端动态解除：管理员在界面上填 corpId / agentId / corpSecret，
 * SecretCodec 加密后落 {@code secret_json}（优先级高于平台级 {@code aios.connector.wechat-work.*}，
 * 见 {@link ConnectorCatalogService#resolveWeCom}）。</p>
 *
 * <p><b>掩码纪律</b>（对齐 ModelConfigService）：GET 绝不回明文——corpId/agentId 部分掩码、
 * corpSecret 全掩码；PUT 提交掩码值或空串 = 保留旧值，绝不把掩码当新值写库。</p>
 */
@Slf4j
@Service
public class ConnectorTenantConfigService {

    private final ConnectorTenantConfigMapper mapper;
    private final ConnectorCatalogService catalogService;
    private final SecretCodec secretCodec;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ConnectorTenantConfigService(ConnectorTenantConfigMapper mapper,
                                        ConnectorCatalogService catalogService,
                                        SecretCodec secretCodec) {
        this.mapper = mapper;
        this.catalogService = catalogService;
        this.secretCodec = secretCodec;
    }

    /** 当前配置（掩码视图）。返回值不含任何明文密钥。 */
    public Map<String, Object> view(Long tenantId, String code) {
        requireOauth2Connector(code);
        ConnectorTenantConfig tc = select(tenantId, code);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", code);
        boolean exists = tc != null;
        String corpId = "", agentId = "", corpSecret = "";
        if (exists) {
            JsonNode node = decryptSafe(tc.getSecretJson());
            corpId = text(node, "corpId");
            agentId = text(node, "agentId");
            corpSecret = text(node, "corpSecret");
        }
        out.put("corpId", mask(corpId, true));
        out.put("agentId", mask(agentId, true));
        out.put("corpSecretSet", !corpSecret.isBlank());
        out.put("corpSecret", mask(corpSecret, false));
        out.put("enabled", exists && Boolean.TRUE.equals(tc.getEnabled()));
        out.put("configured", !corpId.isBlank() && !agentId.isBlank() && !corpSecret.isBlank());
        ConnectorCatalogService.ConfigReadyResult ready = catalogService.configReady(code, tenantId);
        out.put("configReady", ready.ready());
        out.put("configHint", ready.hint());
        return out;
    }

    /** 保存配置。corpId / agentId / corpSecret 任一传空串或掩码值 = 保留旧值。 */
    public Map<String, Object> upsert(Long tenantId, Long userId, String code,
                                      String corpId, String agentId, String corpSecret, Boolean enabled) {
        requireOauth2Connector(code);
        ConnectorTenantConfig tc = select(tenantId, code);
        boolean exists = tc != null;

        String oldCorpId = "", oldAgentId = "", oldSecret = "";
        if (exists) {
            JsonNode node = decryptSafe(tc.getSecretJson());
            oldCorpId = text(node, "corpId");
            oldAgentId = text(node, "agentId");
            oldSecret = text(node, "corpSecret");
        }
        String newCorpId = pick(corpId, oldCorpId);
        String newAgentId = pick(agentId, oldAgentId);
        String newSecret = pick(corpSecret, oldSecret);
        if (newCorpId.isBlank() || newAgentId.isBlank() || newSecret.isBlank()) {
            throw BizException.badRequest("corpId / agentId / corpSecret 均不能为空（留空表示保留旧值）");
        }

        String json;
        try {
            com.fasterxml.jackson.databind.node.ObjectNode n = objectMapper.createObjectNode();
            n.put("corpId", newCorpId);
            n.put("agentId", newAgentId);
            n.put("corpSecret", newSecret);
            json = objectMapper.writeValueAsString(n);
        } catch (Exception e) {
            throw new IllegalStateException("构造配置 JSON 失败", e);
        }

        LocalDateTime now = LocalDateTime.now();
        // 唯一键不含 deleted_at：软删行占位时不能 insert，须复活更新（坑：Duplicate entry uk_tenant_config）
        ConnectorTenantConfig any = mapper.selectIncludingDeleted(tenantId, code);
        if (any != null) {
            mapper.reviveAndUpdate(any.getId(), secretCodec.encrypt(json),
                    enabled == null || enabled, userId, now);
        } else {
            ConnectorTenantConfig ins = new ConnectorTenantConfig();
            ins.setTenantId(tenantId);
            ins.setConnectorCode(code);
            ins.setSecretJson(secretCodec.encrypt(json));
            ins.setEnabled(enabled == null || enabled);
            ins.setUpdatedBy(userId);
            ins.setCreatedAt(now);
            ins.setUpdatedAt(now);
            mapper.insert(ins);
        }
        log.info("租户级连接器配置已保存 code={} tenantId={} by={}", code, tenantId, userId);
        return view(tenantId, code);
    }

    /** 清除配置（@TableLogic 逻辑删），卡片回到「待管理员配置」。 */
    public void clear(Long tenantId, String code) {
        requireOauth2Connector(code);
        ConnectorTenantConfig tc = select(tenantId, code);
        if (tc != null) {
            mapper.deleteById(tc.getId());
        }
    }

    /** @TableLogic 自动过滤已删行。 */
    private ConnectorTenantConfig select(Long tenantId, String code) {
        return mapper.selectOne(new LambdaQueryWrapper<ConnectorTenantConfig>()
                .eq(ConnectorTenantConfig::getTenantId, tenantId)
                .eq(ConnectorTenantConfig::getConnectorCode, code));
    }

    /** 只允许 OAUTH2 型连接器（CREDENTIAL 型走用户凭据，无租户级应用配置）。 */
    private void requireOauth2Connector(String code) {
        ConnectorDef def = catalogService.requireDef(code);
        if (!ConnectorDef.AUTH_MODE_OAUTH2.equals(def.getAuthMode())) {
            throw BizException.badRequest("连接器 " + code + " 不是 OAUTH2 型，无租户级应用配置");
        }
    }

    /** 掩码值 / null / 空白 = 保留旧值。 */
    private static String pick(String submitted, String old) {
        if (submitted == null || submitted.isBlank() || submitted.contains("••") || submitted.contains("**")) {
            return old == null ? "" : old;
        }
        return submitted.trim();
    }

    /** 部分掩码：保留前 4 后 2；全掩码：固定占位（配合 corpSecretSet 判断是否已配）。 */
    private static String mask(String v, boolean partial) {
        if (v == null || v.isBlank()) {
            return "";
        }
        if (!partial) {
            return "••••••";
        }
        if (v.length() <= 6) {
            return "••••";
        }
        return v.substring(0, 4) + "••" + v.substring(v.length() - 2);
    }

    private JsonNode decryptSafe(String secretJson) {
        try {
            return objectMapper.readTree(secretCodec.decrypt(secretJson));
        } catch (Exception e) {
            log.debug("secret_json 解密失败: {}", e.getClass().getSimpleName());
            return null;
        }
    }

    private static String text(JsonNode node, String key) {
        return node == null ? "" : node.path(key).asText("");
    }
}
