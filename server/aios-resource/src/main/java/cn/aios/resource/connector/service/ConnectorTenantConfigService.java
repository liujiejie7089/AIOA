package cn.aios.resource.connector.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.entity.ConnectorTenantConfig;
import cn.aios.resource.connector.mapper.ConnectorTenantConfigMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 租户级连接器应用凭据管理（管理员侧控制面）。
 *
 * <p><b>权威在运行时</b>：连接器的工具跑在 mcp-hub 里，凭据必须落到 hub 才生效。因此本类把
 * 写入/读取<b>委托</b>给 {@link ConnectorCredentialGateway}（hub 的
 * {@code /api/v1/connectors/{code}/credentials}），MySQL 的 {@code connector_tenant_config}
 * 只作<b>影子记录</b>——用于 {@code configReady} 判定、管理端列表与 hub 不可用时的只读展示。
 * 影子写失败只告警，不影响保存成功（权威已落库）。</p>
 *
 * <p><b>schema 驱动</b>：字段列表来自 {@code connector_def.config_keys}（JSON 数组），
 * 不写死 corpId / agentId / corpSecret。新增第三方应用只需给 {@code connector_def}
 * 插一行并声明 keys，管理端表单自动出现对应输入框，本类无需改动。</p>
 *
 * <p><b>掩码纪律</b>（对齐 ModelConfigService）：GET 绝不回明文——敏感键（名称含
 * secret / password / token / apiKey / authCode）只回「已配置」布尔，其余回前 4 位。</p>
 */
@Slf4j
@Service
public class ConnectorTenantConfigService {

    /** 敏感键判定：命中即永不明文回显。集中一处，前后端口径一致。 */
    private static final String SENSITIVE_PATTERN = "(?i).*(secret|password|passwd|token|apikey|api_key|authcode).*";

    private static final String HUB_DOWN_MESSAGE =
            "连接器运行时（mcp-hub）不可达，配置未保存；请先启动 mcp-hub 并确认 AIOS_MCP_HUB=true";

    private final ConnectorTenantConfigMapper mapper;
    private final ConnectorCatalogService catalogService;
    private final SecretCodec secretCodec;
    private final ConnectorCredentialGateway gateway;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ConnectorTenantConfigService(ConnectorTenantConfigMapper mapper,
                                        ConnectorCatalogService catalogService,
                                        SecretCodec secretCodec,
                                        ConnectorCredentialGateway gateway) {
        this.mapper = mapper;
        this.catalogService = catalogService;
        this.secretCodec = secretCodec;
        this.gateway = gateway;
    }

    /** 管理端下拉：所有有应用级配置项的连接器 + 当前就绪状态。 */
    public List<Map<String, Object>> list(Long tenantId) {
        return list(tenantId, null);
    }

    public List<Map<String, Object>> list(Long tenantId, String authorization) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ConnectorDef def : catalogService.activeDefs()) {
            List<String> keys = catalogService.configKeys(def.getCode());
            if (keys.isEmpty()) {
                continue;
            }
            ConnectorTenantConfig tc = select(tenantId, def.getCode());
            boolean configured = tc != null && complete(decryptSafe(tc.getSecretJson()), keys);
            if (!configured) {
                // 影子记录缺失/不全时以运行时为准（避免 hub 已配好、列表仍显示待配置）
                Map<String, Object> hub = gateway.fetch(def.getCode(), authorization);
                configured = hub != null && Boolean.TRUE.equals(hub.get("configured"));
            }
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("code", def.getCode());
            item.put("name", def.getName());
            item.put("authMode", def.getAuthMode());
            item.put("configKeys", keys);
            item.put("enabled", tc != null && Boolean.TRUE.equals(tc.getEnabled()));
            item.put("configured", configured);
            out.add(item);
        }
        return out;
    }

    public Map<String, Object> view(Long tenantId, String code) {
        return view(tenantId, code, null);
    }

    /** 当前配置（掩码视图）。返回值不含任何明文密钥。 */
    public Map<String, Object> view(Long tenantId, String code, String authorization) {
        List<String> keys = requireConfigurable(code);
        Map<String, Object> hub = gateway.fetch(code, authorization);
        if (hub != null) {
            return fromHub(tenantId, code, keys, hub);
        }
        return fromLegacy(tenantId, code, keys);
    }

    /**
     * 保存（通用）。字段集合来自 {@code config_keys}；空串/掩码值 = 保留旧值（语义在 hub 侧统一实现，
     * 本方法不再重复判定，避免两端口径漂移）。
     *
     * @param authorization 调用者的 Authorization，原样转发给 hub（hub 仍走 Java 判定身份/角色）
     */
    public Map<String, Object> upsertValues(Long tenantId, Long userId, String code,
                                            Map<String, String> submitted, Boolean enabled,
                                            String authorization) {
        List<String> keys = requireConfigurable(code);
        if (!gateway.available()) {
            throw new BizException(503, HUB_DOWN_MESSAGE + "（AIOS_MCP_HUB=false 时连接器运行时未启用）");
        }
        Map<String, Object> hub = gateway.put(code, submitted, enabled, authorization);
        if (hub == null) {
            throw new BizException(503, HUB_DOWN_MESSAGE);
        }
        shadowWrite(tenantId, userId, code, keys, submitted, enabled);
        log.info("连接器凭据已保存 code={} tenantId={} keys={} by={}", code, tenantId, keys, userId);
        return fromHub(tenantId, code, keys, hub);
    }

    /** 兼容入口（企业微信三件套）。内部转成通用 values 提交。 */
    public Map<String, Object> upsert(Long tenantId, Long userId, String code,
                                      String corpId, String agentId, String corpSecret, Boolean enabled) {
        Map<String, String> values = new LinkedHashMap<>();
        values.put("corpId", corpId);
        values.put("agentId", agentId);
        values.put("corpSecret", corpSecret);
        return upsertValues(tenantId, userId, code, values, enabled, null);
    }

    /** 清除配置：先清运行时（生效），再清影子记录（展示）。 */
    public void clear(Long tenantId, String code) {
        clear(tenantId, code, null);
    }

    public void clear(Long tenantId, String code, String authorization) {
        requireConfigurable(code);
        if (gateway.available()) {
            Map<String, Object> hub = gateway.delete(code, authorization);
            if (hub == null) {
                throw new BizException(503, HUB_DOWN_MESSAGE + "，配置可能仍在使用中");
            }
        }
        ConnectorTenantConfig tc = select(tenantId, code);
        if (tc != null) {
            mapper.deleteById(tc.getId());
        }
    }

    // ---------- 内部 ----------

    /** hub 返回的掩码视图 → 本接口既有的响应结构（含少量兼容旧前端的字段）。 */
    private Map<String, Object> fromHub(Long tenantId, String code, List<String> keys, Map<String, Object> hub) {
        Map<String, Object> values = asMap(hub.get("values"));
        boolean configured = Boolean.TRUE.equals(hub.get("configured"));
        Object hint = hub.get("hint");

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", code);
        out.put("configKeys", keys);
        out.put("values", values);
        out.put("enabled", Boolean.TRUE.equals(hub.get("enabled")));
        out.put("configured", configured);
        // 兼容旧前端（企业微信页面的固定字段）
        out.put("corpId", str(values.get("corpId")));
        out.put("agentId", str(values.get("agentId")));
        out.put("corpSecret", "");
        out.put("corpSecretSet", Boolean.TRUE.equals(values.get("corpSecretSet")));
        out.put("configReady", configured);
        out.put("configHint", configured ? "" : (hint == null ? "待管理员配置" : String.valueOf(hint)));
        out.put("source", "hub");
        out.put("hubAvailable", true);
        return out;
    }

    /** hub 不可用时的只读兜底：读影子记录，并明确标注来源，避免让人误以为配置已生效。 */
    private Map<String, Object> fromLegacy(Long tenantId, String code, List<String> keys) {
        ConnectorTenantConfig tc = select(tenantId, code);
        JsonNode node = tc == null ? null : decryptSafe(tc.getSecretJson());

        Map<String, String> plain = new LinkedHashMap<>();
        for (String k : keys) {
            plain.put(k, text(node, k));
        }

        Map<String, Object> values = new LinkedHashMap<>();
        for (Map.Entry<String, String> e : plain.entrySet()) {
            if (isSensitive(e.getKey())) {
                values.put(e.getKey(), "");
                values.put(e.getKey() + "Set", !e.getValue().isBlank());
            } else {
                values.put(e.getKey(), mask(e.getValue(), true));
            }
        }

        ConnectorCatalogService.ConfigReadyResult ready = catalogService.configReady(code, tenantId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", code);
        out.put("configKeys", keys);
        out.put("values", values);
        out.put("enabled", tc != null && Boolean.TRUE.equals(tc.getEnabled()));
        out.put("configured", complete(node, keys));
        out.put("corpId", plain.containsKey("corpId") ? mask(plain.get("corpId"), true) : "");
        out.put("agentId", plain.containsKey("agentId") ? mask(plain.get("agentId"), true) : "");
        out.put("corpSecret", "");
        out.put("corpSecretSet", !text(node, "corpSecret").isBlank());
        out.put("configReady", ready.ready());
        out.put("configHint", ready.hint());
        out.put("source", "legacy");
        out.put("hubAvailable", false);
        return out;
    }

    /**
     * 影子记录（MySQL）：只用于 configReady / 列表展示 / hub 不可用时只读兜底。
     * <b>失败只告警不影响保存成功</b>——权威已写进 hub。
     */
    private void shadowWrite(Long tenantId, Long userId, String code, List<String> keys,
                             Map<String, String> submitted, Boolean enabled) {
        try {
            ConnectorTenantConfig tc = select(tenantId, code);
            JsonNode old = tc == null ? null : decryptSafe(tc.getSecretJson());
            Map<String, String> merged = new LinkedHashMap<>();
            for (String k : keys) {
                String incoming = submitted == null ? null : submitted.get(k);
                merged.put(k, pick(incoming, text(old, k)));
            }
            ObjectNode n = objectMapper.createObjectNode();
            merged.forEach(n::put);
            String json = objectMapper.writeValueAsString(n);

            LocalDateTime now = LocalDateTime.now();
            // 唯一键不含 deleted_at：软删行占位时不能 insert，须复活更新
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
        } catch (Exception e) {
            log.warn("连接器影子记录写入失败（不影响运行时生效） code={} err={}", code, e.getClass().getSimpleName());
        }
    }

    /** 有应用级配置项才允许管理员配置；返回声明的键列表。 */
    private List<String> requireConfigurable(String code) {
        List<String> keys = catalogService.configKeys(code);
        if (keys.isEmpty()) {
            throw BizException.badRequest("连接器 " + code + " 没有应用级配置项（config_keys 为空），无需管理员配置");
        }
        return keys;
    }

    /** 必填项是否齐全。 */
    private static boolean complete(JsonNode node, List<String> keys) {
        return keys.stream().allMatch(k -> !text(node, k).isBlank());
    }

    static boolean isSensitive(String key) {
        return key != null && key.matches(SENSITIVE_PATTERN);
    }

    /** @TableLogic 自动过滤已删行。 */
    private ConnectorTenantConfig select(Long tenantId, String code) {
        return mapper.selectOne(new LambdaQueryWrapper<ConnectorTenantConfig>()
                .eq(ConnectorTenantConfig::getTenantId, tenantId)
                .eq(ConnectorTenantConfig::getConnectorCode, code));
    }

    /** 掩码值 / null / 空白 = 保留旧值。 */
    private static String pick(String submitted, String old) {
        if (submitted == null || submitted.isBlank() || submitted.contains("••") || submitted.contains("**")) {
            return old == null ? "" : old;
        }
        return submitted.trim();
    }

    /** 部分掩码：保留前 4 后 2；全掩码：固定占位。 */
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
        if (secretJson == null || secretJson.isBlank()) {
            return null;
        }
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

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }
}
