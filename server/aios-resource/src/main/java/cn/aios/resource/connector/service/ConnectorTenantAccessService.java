package cn.aios.resource.connector.service;

import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.entity.ConnectorTenantAccess;
import cn.aios.resource.connector.mapper.ConnectorDefMapper;
import cn.aios.resource.connector.mapper.ConnectorTenantAccessMapper;
import cn.aios.resource.connector.mcp.entity.McpToolAudit;
import cn.aios.resource.connector.mcp.mapper.McpToolAuditMapper;
import cn.aios.security.AuthUser;
import cn.aios.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 租户接入授权：docs/92 的判据唯一落点。
 *
 * <p><b>三层闸门</b>（全部集中在 {@link #decide}，避免判据散落在 manifest / configReady / hub
 * 各写一份而漂移）：</p>
 * <ol>
 *   <li><b>租户层</b>：{@code connector_tenant_access} 有行且 {@code enabled=1}；
 *       未接入 / 已停用都拒绝。这是本次改造的主闸门。</li>
 *   <li><b>机构层</b>：配置了 {@code scope_institutions} 白名单时，按
 *       {@code AuthUser.institutionId}（primary 机构，docs/92 D3①）判定；空名单 = 全租户。</li>
 *   <li><b>用户层</b>：{@code PermissionCatalog.holds(CHAT_BASIC)} 粗闸 +
 *       {@code config_json.allowedUserIds} 可选白名单（非空时仅列内用户可调用）。</li>
 * </ol>
 *
 * <p><b>为什么 OPEN 连接器直接放行</b>：{@code connector_def.access_mode='OPEN'} 是历史行为
 * （平台统一接入），qq_mail / wecom_cli 等仍走原来的 CONNECTED / configReady 判据，
 * 本服务不介入 —— 改造只收紧声明为 TENANT 的连接器，避免误伤既有能力（docs/92 A11）。</p>
 *
 * <p><b>实时生效</b>：接入态每次查库、不进 JWT claim、不做长期缓存，管理员启用/停用后
 * 下一次 manifest 或工具调用即生效（docs/92 风险 7）。</p>
 *
 * <p><b>审计</b>：hub 每次 {@code tools/call} 前回调 {@code /api/v1/mcp/access/{code}/check}，
 * 本服务在判定的同时写一条 {@code mcp_tool_audit}（含 tenant_id），被拒的调用同样留痕
 * —— 沿用 {@code McpBuiltinBridge} 的口径。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ConnectorTenantAccessService {

    /** 接入模式：平台统一接入（历史行为）。 */
    public static final String ACCESS_OPEN = "OPEN";
    /** 接入模式：需租户完成接入配置后该租户才可用（本次改造目标）。 */
    public static final String ACCESS_TENANT = "TENANT";

    private final ConnectorTenantAccessMapper accessMapper;
    private final ConnectorDefMapper defMapper;
    private final McpToolAuditMapper auditMapper;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // ---------------- 判据 ----------------

    /**
     * 该连接器是否需要租户接入授权（数据驱动，读 {@code connector_def.access_mode}）。
     *
     * <p>判定只认 {@code tenant_id=0 且 ACTIVE} 的平台定义行；脏数据 / 未知 code 一律按 OPEN
     * 处理（保持历史行为，不因为一行配置缺失把整个系统锁死）。</p>
     */
    public boolean requiresTenantAccess(String code) {
        if (code == null || code.isBlank()) {
            return false;
        }
        ConnectorDef def = defMapper.selectOne(new LambdaQueryWrapper<ConnectorDef>()
                .eq(ConnectorDef::getTenantId, 0L)
                .eq(ConnectorDef::getCode, code)
                .eq(ConnectorDef::getStatus, ConnectorDef.STATUS_ACTIVE));
        return def != null && ACCESS_TENANT.equalsIgnoreCase(def.getAccessMode());
    }

    /**
     * 租户层就绪度（无 user 上下文），供 {@code ConnectorCatalogService.configReadyInternal()}
     * 与 {@code McpRegistryService.usableForAgent()} 使用。
     *
     * <p>只判「租户是否启用」；机构/用户范围需要 {@link AuthUser}，放在 {@link #decide}。</p>
     */
    public ConfigReady tenantReady(String code, Long tenantId) {
        if (!requiresTenantAccess(code)) {
            return new ConfigReady(true, null);
        }
        ConnectorTenantAccess a = find(tenantId, code);
        if (a == null) {
            return new ConfigReady(false,
                    "本租户尚未接入「" + code + "」，请联系租户管理员在「连接器接入」中完成配置并启用");
        }
        if (!Boolean.TRUE.equals(a.getEnabled())) {
            return new ConfigReady(false, a.getEnabledAt() != null
                    ? "本租户已停用「" + code + "」，请联系租户管理员重新启用"
                    : "本租户已配置但尚未启用「" + code + "」，请联系租户管理员启用");
        }
        return new ConfigReady(true, null);
    }

    /**
     * 完整调用判定：租户启用 → 机构白名单 → 用户粗闸/白名单。
     *
     * <p>manifest 与 hub 回调共用本方法，保证「看得到工具」与「调得动工具」是同一套判据
     * （docs/92 风险 3：隐藏工具不是安全边界，两层必须一致）。</p>
     */
    public Decision decide(AuthUser user, String code, String tool) {
        if (user == null) {
            return Decision.deny("缺少登录身份，无法调用该连接器");
        }
        if (!requiresTenantAccess(code)) {
            return Decision.ok(tenantId(user), null);
        }
        if (!PermissionCatalog.holds(user, PermissionCatalog.CHAT_BASIC)) {
            return Decision.deny("当前用户没有对话权限，无法调用该连接器");
        }
        Long tid = tenantId(user);
        ConfigReady ready = tenantReady(code, tid);
        if (!ready.ready()) {
            return Decision.deny(ready.hint());
        }
        ConnectorTenantAccess a = find(tid, code);

        // 机构层：primary 机构口径（docs/92 D3①）；空白名单 = 全租户放行
        List<Long> scope = parseLongArray(a.getScopeInstitutions());
        if (!scope.isEmpty()) {
            Long iid = user.getInstitutionId();
            if (iid == null || !scope.contains(iid)) {
                return Decision.deny("当前用户所属机构不在「" + code + "」的允许范围内，请联系租户管理员调整机构白名单");
            }
        }

        // 用户层：config_json.allowedUserIds 可选白名单（非空时仅列内用户可调用）
        List<Long> allowedUsers = allowedUserIds(a.getConfigJson());
        if (!allowedUsers.isEmpty() && !allowedUsers.contains(user.getUserId())) {
            return Decision.deny("当前用户不在「" + code + "」的允许调用名单内，请联系租户管理员");
        }
        return Decision.ok(tid, configString(a.getConfigJson(), "baseUrl"));
    }

    /**
     * hub 回调校验端点：判定 + 写审计。
     *
     * <p>hub 侧 scfy 是原生 server，工具不经过 {@code /api/v1/mcp/builtin/{code}/call}，
     * 因此原本不会写 {@code mcp_tool_audit}。这里在每次工具调用前补一条带 tenant_id 的记录，
     * 让「接入配置 + 调用审计 + 用量」都能按租户归属（docs/92 §2.4 / A7）。</p>
     */
    public CheckResult check(AuthUser user, String code, String tool) {
        long start = System.currentTimeMillis();
        Decision d = decide(user, code, tool);
        writeAudit(user, code, tool, d.ok(), d.reason(), System.currentTimeMillis() - start);
        return new CheckResult(d.ok(), d.reason(), user == null ? null : tenantId(user),
                user == null ? null : user.getUserId(), d.baseUrl());
    }

    // ---------------- 管理端（租户管理员） ----------------

    /** 本租户所有「按租户接入」连接器的状态清单（管理端渲染用，数据驱动、不硬编码 code）。 */
    public List<AccessView> list(Long tenantId) {
        List<ConnectorDef> defs = defMapper.selectList(new LambdaQueryWrapper<ConnectorDef>()
                .eq(ConnectorDef::getTenantId, 0L)
                .eq(ConnectorDef::getStatus, ConnectorDef.STATUS_ACTIVE)
                .eq(ConnectorDef::getAccessMode, ACCESS_TENANT)
                .orderByAsc(ConnectorDef::getSort));
        List<AccessView> out = new ArrayList<>();
        for (ConnectorDef d : defs) {
            out.add(view(tenantId, d.getCode()));
        }
        return out;
    }

    /** 接入四态 + 配置视图。给管理端与状态查询端点。 */
    public AccessView view(Long tenantId, String code) {
        ConnectorTenantAccess a = find(tenantId, code);
        Status status;
        if (a == null) {
            status = Status.NOT_CONNECTED;
        } else if (Boolean.TRUE.equals(a.getEnabled())) {
            status = Status.ENABLED;
        } else if (a.getEnabledAt() != null) {
            status = Status.DISABLED;
        } else {
            status = Status.CONFIGURED_DISABLED;
        }
        Map<String, Object> config = parseObject(a == null ? null : a.getConfigJson());
        // 不回显 allowedUserIds 之外的敏感内容；这里只回显可编辑的几项
        Map<String, Object> viewConfig = new LinkedHashMap<>();
        if (config.containsKey("baseUrl")) {
            viewConfig.put("baseUrl", config.get("baseUrl"));
        }
        if (config.containsKey("allowedUserIds")) {
            viewConfig.put("allowedUserIds", config.get("allowedUserIds"));
        }
        return new AccessView(code, requiresTenantAccess(code), status.name(),
                a != null && Boolean.TRUE.equals(a.getEnabled()),
                parseLongArray(a == null ? null : a.getScopeInstitutions()),
                viewConfig,
                a == null ? null : a.getEnabledAt(),
                a == null ? null : a.getEnabledBy());
    }

    /** 启用（幂等）：无行则按「已启用」创建，有行则置 enabled=1。 */
    @Transactional
    public AccessView enable(AuthUser admin, String code) {
        requireManage(admin, code);
        return upsert(admin, code, true, null, null);
    }

    /** 停用（幂等）：保留配置行，enabled=0；历史 enabled_at 不清除，用于区分「待启用/已停用」。 */
    @Transactional
    public AccessView disable(AuthUser admin, String code) {
        requireManage(admin, code);
        return upsert(admin, code, false, null, null);
    }

    /**
     * 配置接入范围（机构白名单 / 租户级 baseUrl / 用户白名单），不改变启用态。
     *
     * <p>{@code scope=null} 表示「不修改」，传空列表表示「清空白名单 = 全租户」；
     * {@code config=null} 表示不修改，传空 Map 表示清空租户级配置。</p>
     */
    @Transactional
    public AccessView configure(AuthUser admin, String code, List<Long> scope,
                                Map<String, Object> config) {
        requireManage(admin, code);
        return upsert(admin, code, null, scope, config);
    }

    private void requireManage(AuthUser admin, String code) {
        if (admin == null) {
            throw BizException.forbidden("需要登录");
        }
        if (!PermissionCatalog.holds(admin, PermissionCatalog.CONNECTOR_ACCESS_MANAGE)) {
            throw BizException.forbidden("需要租户管理员权限才能配置连接器接入");
        }
        if (!requiresTenantAccess(code)) {
            throw BizException.badRequest("该连接器不是按租户接入模式，无需配置：" + code);
        }
    }

    /**
     * upsert：唯一键不含 deleted_at，软删行会永久占位 ⇒ 先探场，命中死行走裸 SQL 复活
     * （与 {@code ConnectorTenantConfigMapper} / {@code McpServerMapper} 同款坑，见 pitfalls 80）。
     */
    private AccessView upsert(AuthUser admin, String code, Boolean enabled,
                              List<Long> scope, Map<String, Object> config) {
        Long tid = tenantId(admin);
        LocalDateTime now = LocalDateTime.now();
        ConnectorTenantAccess dead = accessMapper.selectIncludingDeleted(tid, code);

        Boolean finalEnabled = enabled;
        if (dead != null && finalEnabled == null) {
            finalEnabled = Boolean.TRUE.equals(dead.getEnabled());
        }
        if (finalEnabled == null) {
            finalEnabled = false; // 新行默认「已配置待启用」，不自动放行
        }

        String scopeJson = scope == null
                ? (dead == null ? null : dead.getScopeInstitutions())
                : toJson(scope);
        String configJson = config == null
                ? (dead == null ? null : dead.getConfigJson())
                : toJson(config);

        if (dead != null && dead.getDeletedAt() != null) {
            accessMapper.reviveAndUpdate(dead.getId(), finalEnabled, scopeJson, configJson,
                    admin.getUserId(), now);
        } else if (dead != null) {
            dead.setEnabled(finalEnabled);
            dead.setScopeInstitutions(scopeJson);
            dead.setConfigJson(configJson);
            dead.setUpdatedBy(admin.getUserId());
            dead.setUpdatedAt(now);
            if (Boolean.TRUE.equals(finalEnabled)) {
                dead.setEnabledBy(admin.getUserId());
                dead.setEnabledAt(now);
            }
            accessMapper.updateById(dead);
        } else {
            ConnectorTenantAccess a = new ConnectorTenantAccess();
            a.setTenantId(tid);
            a.setConnectorCode(code);
            a.setEnabled(finalEnabled);
            a.setScopeInstitutions(scopeJson);
            a.setConfigJson(configJson);
            a.setCreatedBy(admin.getUserId());
            a.setUpdatedBy(admin.getUserId());
            a.setCreatedAt(now);
            a.setUpdatedAt(now);
            if (Boolean.TRUE.equals(finalEnabled)) {
                a.setEnabledBy(admin.getUserId());
                a.setEnabledAt(now);
            }
            accessMapper.insert(a);
        }
        log.info("租户接入配置更新 tenantId={} code={} enabled={} by={}", tid, code, finalEnabled,
                admin.getUserId());
        return view(tid, code);
    }

    // ---------------- 内部 ----------------

    private ConnectorTenantAccess find(Long tenantId, String code) {
        if (code == null || code.isBlank()) {
            return null;
        }
        return accessMapper.selectOne(new LambdaQueryWrapper<ConnectorTenantAccess>()
                .eq(ConnectorTenantAccess::getTenantId, tenantId)
                .eq(ConnectorTenantAccess::getConnectorCode, code)
                .last("LIMIT 1"));
    }

    private List<Long> parseLongArray(String raw) {
        if (raw == null || raw.isBlank()) {
            return List.of();
        }
        try {
            JsonNode arr = objectMapper.readTree(raw);
            if (!arr.isArray()) {
                return List.of();
            }
            List<Long> out = new ArrayList<>();
            for (JsonNode n : arr) {
                if (n.canConvertToLong()) {
                    out.add(n.asLong());
                }
            }
            return out;
        } catch (Exception e) {
            log.warn("scope_institutions 解析失败，按不限机构处理 raw={}：{}", raw, e.getMessage());
            return List.of();
        }
    }

    private List<Long> allowedUserIds(String configJson) {
        Map<String, Object> cfg = parseObject(configJson);
        Object v = cfg.get("allowedUserIds");
        if (!(v instanceof List<?> list)) {
            return List.of();
        }
        List<Long> out = new ArrayList<>();
        for (Object o : list) {
            if (o instanceof Number n) {
                out.add(n.longValue());
            } else if (o instanceof String s && !s.isBlank()) {
                try {
                    out.add(Long.parseLong(s.trim()));
                } catch (NumberFormatException ignored) {
                    // 脏值跳过，不因一条坏配置把整个租户锁死
                }
            }
        }
        return out;
    }

    private String configString(String configJson, String key) {
        Object v = parseObject(configJson).get(key);
        return v == null ? null : String.valueOf(v);
    }

    private Map<String, Object> parseObject(String raw) {
        if (raw == null || raw.isBlank()) {
            return Map.of();
        }
        try {
            JsonNode node = objectMapper.readTree(raw);
            if (!node.isObject()) {
                return Map.of();
            }
            Map<String, Object> out = new LinkedHashMap<>();
            node.fields().forEachRemaining(e -> {
                JsonNode v = e.getValue();
                if (v.isArray()) {
                    List<Object> arr = new ArrayList<>();
                    v.forEach(x -> arr.add(x.isNumber() ? x.numberValue()
                            : x.isBoolean() ? x.booleanValue() : x.asText()));
                    out.put(e.getKey(), arr);
                } else if (v.isNumber()) {
                    out.put(e.getKey(), v.numberValue());
                } else if (v.isBoolean()) {
                    out.put(e.getKey(), v.booleanValue());
                } else if (!v.isNull()) {
                    out.put(e.getKey(), v.asText());
                }
            });
            return out;
        } catch (Exception e) {
            log.warn("config_json 解析失败，按空配置处理：{}", e.getMessage());
            return Map.of();
        }
    }

    private String toJson(Object o) {
        if (o == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            throw BizException.badRequest("接入配置序列化失败：" + e.getMessage());
        }
    }

    private void writeAudit(AuthUser user, String code, String tool, boolean ok,
                            String reason, long duration) {
        try {
            McpToolAudit a = new McpToolAudit();
            a.setTenantId(user == null ? 0L : tenantId(user));
            a.setUserId(user == null ? null : user.getUserId());
            a.setServerCode(code);
            a.setToolName(tool == null || tool.isBlank() ? "(access-check)" : tool);
            a.setArgsDigest("-");   // check 端点拿不到工具入参，绝不编造摘要
            a.setOk(ok ? 1 : 0);
            a.setError(ok ? null : truncate(reason, 512));
            a.setDurationMs(duration);
            a.setCreatedAt(LocalDateTime.now());
            auditMapper.insert(a);
        } catch (Exception e) {
            // 审计写失败不能把「准入判定」变成失败：用户会以为没权限而反复重试
            log.warn("mcp_tool_audit 写入失败（不影响准入判定）: {}", e.getClass().getSimpleName());
        }
    }

    private static Long tenantId(AuthUser u) {
        return u == null || u.getTenantId() == null ? 0L : u.getTenantId();
    }

    private static String truncate(String s, int n) {
        if (s == null) {
            return null;
        }
        return s.length() <= n ? s : s.substring(0, n);
    }

    // ---------------- DTO ----------------

    public enum Status {
        /** 未接入：无配置行（新租户默认态）。 */
        NOT_CONNECTED,
        /** 已配置待启用：有行、enabled=0、从未启用过。 */
        CONFIGURED_DISABLED,
        /** 已启用。 */
        ENABLED,
        /** 已停用：曾启用过，被管理员停用。 */
        DISABLED
    }

    public record ConfigReady(boolean ready, String hint) {
    }

    /** 判定结果。baseUrl 为租户级数据源覆盖（null = 用平台默认），hub 侧据此选地址。 */
    public record Decision(boolean ok, String reason, Long tenantId, String baseUrl) {
        static Decision ok(Long tid, String baseUrl) {
            return new Decision(true, null, tid, baseUrl);
        }

        static Decision deny(String reason) {
            return new Decision(false, reason, null, null);
        }
    }

    /** hub 回调的返回体。 */
    public record CheckResult(boolean ok, String reason, Long tenantId, Long userId, String baseUrl) {
    }

    /** 管理端视图：四态 + 是否需要租户接入 + 机构白名单 + 可编辑配置。 */
    public record AccessView(String code, boolean requiresTenantAccess, String status,
                             boolean enabled, List<Long> scopeInstitutions,
                             Map<String, Object> config, LocalDateTime enabledAt,
                             Long enabledBy) {
    }
}
