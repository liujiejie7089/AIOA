package cn.aios.resource.connector.mcp.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.mcp.config.McpProperties;
import cn.aios.resource.connector.mcp.entity.McpServer;
import cn.aios.resource.connector.mcp.entity.McpServerTool;
import cn.aios.resource.connector.mcp.mapper.McpServerMapper;
import cn.aios.resource.connector.mcp.mapper.McpServerToolMapper;
import cn.aios.resource.connector.service.ConnectorConnectionService;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * MCP 注册表业务（docs/59 §10.3 的 9 个端点中除 builtin/call 外的全部逻辑）。
 *
 * <p><b>信任闸门</b>：新服务器 {@code trusted=0}，{@code trust} 必须先探测，ok=false 时 trusted 保持 0
 * （业务失败返回 ok=false，HTTP 仍 200，前端好展示）；ok=true 才置 trusted=1 并覆盖写工具目录。</p>
 *
 * <p><b>连接闸门</b>：{@code manifest} 仅返回 trusted=1 且（BUILTIN ⇒ 连接器已 CONNECTED）的服务器，
 * 未连接的内置服务器不出现（判据 2：防止「信任了就能读别人邮箱」的误解）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class McpRegistryService {

    private final McpServerMapper serverMapper;
    private final McpServerToolMapper toolMapper;
    private final ConnectorConnectionService connectionService;
    private final McpProbeClient probeClient;
    private final McpProperties props;
    private final SecretCodec secretCodec;
    private ObjectMapper objectMapper = new ObjectMapper();

    // ---------------- 查询 ----------------

    /** 租户可见的服务器（tenant_id=本租户 或 0 的平台内置）+ 未删除。 */
    public List<ServerItem> list(AuthUser user) {
        List<McpServer> servers = visibleServers(user);
        List<ServerItem> items = new ArrayList<>();
        for (McpServer s : servers) {
            int toolCount = toolMapper.selectCount(new LambdaQueryWrapper<McpServerTool>()
                    .eq(McpServerTool::getServerId, s.getId())).intValue();
            boolean connected = false;
            if (McpServer.SOURCE_BUILTIN.equals(s.getSource()) && s.getConnectorCode() != null
                    && !s.getConnectorCode().isBlank()) {
                connected = ConnectorConnection.STATUS_CONNECTED.equals(
                        connectionService.statusOf(tenantId(user), user.getUserId(), s.getConnectorCode()));
            }
            items.add(new ServerItem(s.getCode(), s.getName(), s.getSource(), s.getTransport(),
                    trusted(s), s.getStatus(), s.getLastError(), s.getLastProbeAt(),
                    s.getConnectorCode(), toolCount, connected));
        }
        return items;
    }

    /** agent 用：仅 trusted=1 且（BUILTIN ⇒ 连接器 CONNECTED）。返回 hub 统一入口 url。 */
    public List<ManifestItem> manifest(AuthUser user) {
        List<McpServer> servers = serverMapper.selectList(new LambdaQueryWrapper<McpServer>()
                .in(McpServer::getTenantId, List.of(0L, tenantId(user)))
                .eq(McpServer::getTrusted, 1)
                .orderByAsc(McpServer::getSort));
        List<ManifestItem> out = new ArrayList<>();
        for (McpServer s : servers) {
            if (McpServer.SOURCE_BUILTIN.equals(s.getSource())) {
                if (s.getConnectorCode() == null || s.getConnectorCode().isBlank()) {
                    continue;
                }
                boolean connected = ConnectorConnection.STATUS_CONNECTED.equals(
                        connectionService.statusOf(tenantId(user), user.getUserId(), s.getConnectorCode()));
                if (!connected) {
                    continue; // 判据 2
                }
            }
            int toolCount = toolMapper.selectCount(new LambdaQueryWrapper<McpServerTool>()
                    .eq(McpServerTool::getServerId, s.getId())).intValue();
            // URL 口径（两源不同，别一律拼 hub）：
            //  - BUILTIN：工具体在 Java 侧、且凭据只有 Java 能解密 ⇒ agent 不能直连，走 hub 的
            //    /mcp/<code>，hub 用调用方 token 回调 /api/v1/mcp/builtin/<code>/call。
            //  - EXTERNAL：上游本身就是标准 MCP 服务器（streamable_http），agent **直连注册地址**。
            //    为什么不也挂 hub 代理：hub 是无状态、无凭据的转发层；做外链代理就得让它持有一份
            //    解密后的上游 headers（等于把 credentials 复制到第二个进程）。这一版选择「不复制」，
            //    代价是 agent 能看到上游地址。真遇到「上游必须带密钥」时，再按 docs/59 §10.2 补代理。
            String url;
            if (McpServer.SOURCE_BUILTIN.equals(s.getSource())) {
                url = props.getHubUrl().replaceAll("/+$/", "") + "/mcp/" + s.getCode();
            } else {
                url = s.getUrl();
                if (url == null || url.isBlank()) {
                    continue; // 无地址的 EXTERNAL 行是脏数据：宁可不给，也不能给一个连不上的地址
                }
            }
            out.add(new ManifestItem(s.getCode(), s.getName(), "streamable_http", url, toolCount));
        }
        return out;
    }

    /** 内置工具目录全量（规格对齐哨兵用，格式与 probe 的 tools 一致，附带 serverCode 以便分组）。 */
    public List<BuiltinCatalogItem> builtinCatalog() {
        List<McpServer> servers = serverMapper.selectList(new LambdaQueryWrapper<McpServer>()
                .eq(McpServer::getSource, McpServer.SOURCE_BUILTIN));
        List<BuiltinCatalogItem> out = new ArrayList<>();
        for (McpServer s : servers) {
            List<McpServerTool> rows = toolMapper.selectList(new LambdaQueryWrapper<McpServerTool>()
                    .eq(McpServerTool::getServerId, s.getId())
                    .orderByAsc(McpServerTool::getSort));
            for (McpServerTool t : rows) {
                out.add(new BuiltinCatalogItem(s.getCode(), t.getName(), t.getDescription(),
                        t.getInputSchema(), readOnly(t)));
            }
        }
        return out;
    }

    /** 单个服务器的工具目录。 */
    public List<ToolItem> tools(AuthUser user, String code) {
        McpServer s = requireVisible(user, code);
        List<McpServerTool> rows = toolMapper.selectList(new LambdaQueryWrapper<McpServerTool>()
                .eq(McpServerTool::getServerId, s.getId())
                .orderByAsc(McpServerTool::getSort));
        return rows.stream().map(t -> new ToolItem(t.getName(), t.getDescription(),
                t.getInputSchema(), readOnly(t), t.getSort())).collect(Collectors.toList());
    }

    // ---------------- 写操作 ----------------

    /**
     * 注册外部服务器：code 规则 + 重名校验 + transport 必填项 + env/headers 加密。trusted=0。
     *
     * <p><b>为什么重名校验要「含软删」查</b>：{@code delete} 走逻辑删除，而唯一键
     * {@code uk_mcp_server(tenant_id, code)} 不含 {@code deleted_at} ⇒ 被软删的行会永久占住这个 code。
     * 只按 {@code deleted_at IS NULL} 查重（{@code selectOne} 的默认行为）看不见死行，于是校验放过、
     * insert 撞唯一键抛 500（实测：E2E 跑第二遍、注册同一个 code 就 500）。这里的口径是：
     * 活着 ⇒ 400 明确报重名；已软删 ⇒ 视为「这个 code 空着」，物理清场（连同旧工具目录）后重新插入，
     * 所以「删除再接同一台服务器」是可重复的。</p>
     */
    @Transactional
    public ServerItem registerExternal(AuthUser user, RegisterRequest req) {
        if (req == null || req.code() == null || !req.code().matches("^[a-z][a-z0-9_]{1,48}$")) {
            throw BizException.badRequest(
                    "服务器 code 非法（须小写字母开头，仅含小写字母/数字/下划线，长度 2-49）");
        }
        if (!McpServer.TRANSPORT_STDIO.equals(req.transport())
                && !McpServer.TRANSPORT_STREAMABLE_HTTP.equals(req.transport())) {
            throw BizException.badRequest("transport 须为 STDIO 或 STREAMABLE_HTTP");
        }
        McpServer dead = serverMapper.selectIncludingDeleted(tenantId(user), req.code());
        if (dead != null && dead.getDeletedAt() == null) {
            throw BizException.badRequest("服务器 code 已存在");
        }
        if (dead != null) {
            // 软删残行占着唯一键：先物理清掉它和它的工具目录，再走正常插入（不复活旧配置）
            toolMapper.purgeByServerId(dead.getId());
            serverMapper.purgeById(dead.getId());
            log.info("MCP 注册：清掉软删残行 code={} id={} 后重新注册", req.code(), dead.getId());
        }
        McpServer s = new McpServer();
        s.setTenantId(tenantId(user));
        s.setCode(req.code());
        s.setName(req == null || req.name() == null ? req.code() : req.name());
        s.setSource(McpServer.SOURCE_EXTERNAL);
        s.setTransport(req.transport());
        s.setTrusted(0);
        s.setStatus(McpServer.STATUS_UNKNOWN);
        s.setSort(100);
        s.setCreatedBy(user.getUserId());
        if (McpServer.TRANSPORT_STDIO.equals(req.transport())) {
            if (req.command() == null || req.command().isBlank()) {
                throw BizException.badRequest("STDIO 传输必须提供 command");
            }
            s.setCommand(req.command());
            s.setArgsJson(toJson(req.args()));
            s.setEnvEnc(encryptMap(req.env()));
        } else {
            if (req.url() == null || !(req.url().startsWith("http://") || req.url().startsWith("https://"))) {
                throw BizException.badRequest("STREAMABLE_HTTP 传输必须提供 http(s) 开头的 url");
            }
            s.setUrl(req.url());
            s.setHeadersEnc(encryptMap(req.headers()));
        }
        // 并发注册同一 code 时上面的查重会双放行，让唯一键兜底；把 500 换成 400 的明确文案
        try {
            serverMapper.insert(s);
        } catch (org.springframework.dao.DuplicateKeyException e) {
            throw BizException.badRequest("服务器 code 已存在");
        }
        return new ServerItem(s.getCode(), s.getName(), s.getSource(), s.getTransport(), false,
                s.getStatus(), null, null, s.getConnectorCode(), 0, false);
    }

    /** 只探测（不落 trusted），顺手把 status/last_error/last_probe_at 落库。 */
    public McpProbeClient.ProbeResult probe(AuthUser user, String code) {
        McpServer s = requireVisible(user, code);
        McpProbeClient.ProbeResult r = probeClient.probe(s);
        persistProbe(s, r, LocalDateTime.now());
        return r;
    }

    /**
     * 落库探测结果。
     *
     * <p><b>为什么不能用 {@code updateById}</b>：MyBatis-Plus 默认字段策略是 NOT_NULL ——
     * 传 null 的字段**不会**进 UPDATE 语句。所以「探测成功后把 lastError 清空」写成
     * {@code s.setLastError(null); updateById(s)} 是**静默无效**的：界面会永远挂着上一次的
     * 错误文案（实测：修好 h2c 之后卡片仍显示「未知 transport：None」）。这里显式用
     * {@code LambdaUpdateWrapper.set(...)} 才能把列真的置 NULL。</p>
     */
    private void persistProbe(McpServer s, McpProbeClient.ProbeResult r, LocalDateTime now) {
        serverMapper.update(null, new LambdaUpdateWrapper<McpServer>()
                .eq(McpServer::getId, s.getId())
                .set(McpServer::getStatus, r.isOk() ? McpServer.STATUS_OK : McpServer.STATUS_ERROR)
                .set(McpServer::getLastError, r.isOk() ? null : truncate(r.getError(), 1024))
                .set(McpServer::getLastProbeAt, now));
        // 同步内存快照，供后续逻辑（如 trust 的 toolCount）使用
        s.setStatus(r.isOk() ? McpServer.STATUS_OK : McpServer.STATUS_ERROR);
        s.setLastError(r.isOk() ? null : truncate(r.getError(), 1024));
        s.setLastProbeAt(now);
    }

    /** 信任：先探测；ok=false ⇒ trusted 保持 0；ok=true ⇒ trusted=1 + 事务内覆盖写工具目录。 */
    @Transactional
    public TrustResult trust(AuthUser user, String code) {
        McpServer s = requireVisible(user, code);
        McpProbeClient.ProbeResult r = probeClient.probe(s);
        LocalDateTime now = LocalDateTime.now();
        persistProbe(s, r, now);
        if (!r.isOk()) {
            return new TrustResult(false, r.getError(), 0);
        }
        s = requireVisible(user, code); // 重新读取最新快照
        s.setTrusted(1);
        s.setStatus(McpServer.STATUS_OK);
        serverMapper.updateById(s);
        int count = syncTools(s, r.getTools());
        return new TrustResult(true, null, count);
    }

    /** 取消信任：保留工具目录便于回看。 */
    public TrustResult untrust(AuthUser user, String code) {
        McpServer s = requireVisible(user, code);
        s.setTrusted(0);
        serverMapper.updateById(s);
        return new TrustResult(true, null, 0);
    }

    /** 删除：仅 EXTERNAL 可删；内置只允许 untrust。逻辑删除（@TableLogic）。 */
    public void delete(AuthUser user, String code) {
        McpServer s = requireVisible(user, code);
        if (McpServer.SOURCE_BUILTIN.equals(s.getSource())) {
            throw BizException.badRequest("内置服务器不允许删除，请改用取消信任");
        }
        serverMapper.deleteById(s.getId());
    }

    // ---------------- 内部 ----------------

    /** 事务内按 name 覆盖写工具目录：存在则更新描述/结构/只读，多余则逻辑删除。 */
    private int syncTools(McpServer s, List<McpProbeClient.Tool> tools) {
        List<McpServerTool> existing = toolMapper.selectList(new LambdaQueryWrapper<McpServerTool>()
                .eq(McpServerTool::getServerId, s.getId()));
        Map<String, McpServerTool> byName = existing.stream()
                .collect(Collectors.toMap(McpServerTool::getName, t -> t, (a, b) -> a));
        Set<String> incoming = new HashSet<>();
        int sort = 1;
        for (McpProbeClient.Tool t : tools) {
            incoming.add(t.getName());
            McpServerTool row = byName.get(t.getName());
            if (row == null) {
                row = new McpServerTool();
                row.setTenantId(s.getTenantId());
                row.setServerId(s.getId());
                row.setName(t.getName());
                row.setCreatedAt(LocalDateTime.now());
            }
            row.setDescription(t.getDescription());
            // 库里存 JSON 字符串；probe 回来的是对象，这里统一序列化（两种 transport 归一）
            row.setInputSchema(schemaText(t.getInputSchema()));
            row.setReadOnly(t.isReadOnly() ? 1 : 0);
            row.setSort(sort++);
            row.setUpdatedAt(LocalDateTime.now());
            row.setDeletedAt(null); // 恢复（若曾被逻辑删除）
            if (row.getId() == null) {
                toolMapper.insert(row);
            } else {
                toolMapper.updateById(row);
            }
        }
        for (McpServerTool row : existing) {
            if (!incoming.contains(row.getName())) {
                row.setDeletedAt(LocalDateTime.now());
                toolMapper.updateById(row);
            }
        }
        return tools.size();
    }

    private List<McpServer> visibleServers(AuthUser user) {
        return serverMapper.selectList(new LambdaQueryWrapper<McpServer>()
                .in(McpServer::getTenantId, List.of(0L, tenantId(user)))
                .orderByAsc(McpServer::getSort));
    }

    private McpServer requireVisible(AuthUser user, String code) {
        McpServer s = serverMapper.selectOne(new LambdaQueryWrapper<McpServer>()
                .eq(McpServer::getCode, code)
                .in(McpServer::getTenantId, List.of(0L, tenantId(user))));
        if (s == null) {
            throw BizException.notFound("MCP 服务器不存在或不可见：" + code);
        }
        return s;
    }

    private String encryptMap(Map<String, String> m) {
        if (m == null || m.isEmpty()) {
            return null;
        }
        try {
            return secretCodec.encrypt(objectMapper.writeValueAsString(m));
        } catch (Exception e) {
            throw new IllegalStateException("MCP 服务器 env/headers 加密失败", e);
        }
    }

    private String toJson(List<String> list) {
        if (list == null || list.isEmpty()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(list);
        } catch (Exception e) {
            return null;
        }
    }

    private static Long tenantId(AuthUser u) {
        return u.getTenantId() == null ? 0L : u.getTenantId();
    }

    private static boolean trusted(McpServer s) {
        return s.getTrusted() != null && s.getTrusted() == 1;
    }

    private static boolean readOnly(McpServerTool t) {
        return t.getReadOnly() != null && t.getReadOnly() == 1;
    }

    private static String truncate(String s, int n) {
        if (s == null) {
            return null;
        }
        return s.length() <= n ? s : s.substring(0, n);
    }

    // ---------------- DTO ----------------

    public record ServerItem(String code, String name, String source, String transport,
                             boolean trusted, String status, String lastError,
                             LocalDateTime lastProbeAt, String connectorCode,
                             int toolCount, boolean connected) {
    }

    public record TrustResult(boolean ok, String error, int toolCount) {
    }

    public record ManifestItem(String code, String name, String transport, String url, int toolCount) {
    }

    public record BuiltinCatalogItem(String serverCode, String name, String description,
                                     String inputSchema, boolean readOnly) {
    }

    public record ToolItem(String name, String description, String inputSchema,
                           boolean readOnly, int sort) {
    }

    public record RegisterRequest(String code, String name, String transport, String command,
                                  List<String> args, Map<String, String> env,
                                  String url, Map<String, String> headers) {
    }

    /**
     * 把 probe 回来的 {@code inputSchema}（可能是 Map、String 或 null）统一成存库用的 JSON 字符串。
     * 序列化失败不能炸掉整次 trust —— 那会把一个坏工具变成「整个服务器信任失败」，
     * 用户只看到一句「网关不可用」，看不出是哪个工具的 schema 有问题。
     */
    private String schemaText(Object schema) {
        if (schema == null) {
            return "{}";
        }
        if (schema instanceof String str) {
            return str.isBlank() ? "{}" : str;
        }
        try {
            return objectMapper.writeValueAsString(schema);
        } catch (Exception e) {
            log.warn("inputSchema 序列化失败，已降级为空对象: {}", e.getClass().getSimpleName());
            return "{}";
        }
    }
}
