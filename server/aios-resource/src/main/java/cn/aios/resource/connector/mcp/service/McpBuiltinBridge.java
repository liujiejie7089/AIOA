package cn.aios.resource.connector.mcp.service;

import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.mcp.entity.McpServer;
import cn.aios.resource.connector.mcp.entity.McpToolAudit;
import cn.aios.resource.connector.mcp.mapper.McpServerMapper;
import cn.aios.resource.connector.mcp.mapper.McpToolAuditMapper;
import cn.aios.resource.connector.mcp.spi.McpBuiltinHandler;
import cn.aios.resource.connector.service.ConnectorConnectionService;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 内置 MCP 工具执行闸门（docs/59 §10.3 {@code POST /api/v1/mcp/builtin/{code}/call}）。
 *
 * <p><b>判权链</b>：服务器可见 + {@code trusted=1} +（BUILTIN ⇒ 连接器 CONNECTED）⇒ 才允许执行；
 * 找不到对应 handler ⇒ 「工具未实现」。每调用一次都写一条 {@code mcp_tool_audit}
 * （{@code args_digest} 为参数规范 JSON 的 SHA-256，<b>绝不</b>存参数原文）。</p>
 *
 * <p><b>失败语义</b>：{@code BizException} 取中文 message；其余异常只取简单类名；
 * <b>不</b>把堆栈或参数原文写进返回/日志。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class McpBuiltinBridge {

    private final List<McpBuiltinHandler> handlers;
    private final McpServerMapper serverMapper;
    private final McpToolAuditMapper auditMapper;
    private final ConnectorConnectionService connectionService;
    private ObjectMapper objectMapper = new ObjectMapper();

    public record CallResult(boolean ok, Object data, String error) {
    }

    /**
     * 执行内置工具。
     *
     * <p><b>审计口径（判据：闸门拦下的调用也要留痕）</b>：无论成功、业务失败、还是被闸门
     * 直接拒绝（未信任 / 连接器未连接 / 工具未实现），<b>都写一条</b> {@code mcp_tool_audit}。
     * 理由：被拒的调用恰恰是最需要留痕的一类（有人在试未授权的服务器）。只在成功路径写审计，
     * 会让「越权尝试」在库里完全不可见。审计本身失败不影响工具结果（只 warn）。</p>
     */
    public CallResult call(AuthUser user, String code, String tool, Map<String, Object> args) {
        long start = System.currentTimeMillis();
        String digest = argsDigest(args);
        CallResult result;
        try {
            result = doCall(user, code, tool, args);
        } catch (BizException e) {
            result = new CallResult(false, null, truncate(e.getMessage(), 512));
        } catch (Exception e) {
            log.debug("MCP 内置工具调用异常: {}", e.getClass().getSimpleName());
            result = new CallResult(false, null, e.getClass().getSimpleName());
        }
        writeAudit(user, code, tool, digest, result.ok(), result.error(),
                System.currentTimeMillis() - start);
        return result;
    }

    /** 判权 + 分派（不含审计）；失败统一抛 {@link BizException}，由 {@link #call} 收敛。 */
    private CallResult doCall(AuthUser user, String code, String tool, Map<String, Object> args) {
        McpServer s = serverMapper.selectOne(new LambdaQueryWrapper<McpServer>()
                .eq(McpServer::getCode, code)
                .in(McpServer::getTenantId, List.of(0L,
                        user.getTenantId() == null ? 0L : user.getTenantId())));
        if (s == null) {
            return new CallResult(false, null, "MCP 服务器不存在");
        }
        if (s.getTrusted() == null || s.getTrusted() != 1) {
            return new CallResult(false, null, "该 MCP 服务器尚未信任");
        }
        if (McpServer.SOURCE_BUILTIN.equals(s.getSource()) && s.getConnectorCode() != null
                && !s.getConnectorCode().isBlank()) {
            Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
            boolean connected = ConnectorConnection.STATUS_CONNECTED.equals(
                    connectionService.statusOf(tenantId, user.getUserId(), s.getConnectorCode()));
            if (!connected) {
                return new CallResult(false, null,
                        "连接器未连接：请先在「连接器」里完成 " + s.getName() + " 授权");
            }
        }
        McpBuiltinHandler handler = null;
        for (McpBuiltinHandler h : handlers) {
            if (code.equals(h.serverCode()) && h.supports(tool)) {
                handler = h;
                break;
            }
        }
        if (handler == null) {
            return new CallResult(false, null, "工具未实现：" + tool);
        }
        Object data = handler.call(tool, args, user);
        return new CallResult(true, data, null);
    }

    private void writeAudit(AuthUser user, String code, String tool, String digest,
                            boolean ok, String error, long duration) {
        McpToolAudit a = new McpToolAudit();
        a.setTenantId(user.getTenantId() == null ? 0L : user.getTenantId());
        a.setUserId(user.getUserId());
        a.setServerCode(code);
        a.setToolName(tool);
        a.setArgsDigest(digest);
        a.setOk(ok ? 1 : 0);
        a.setError(error);
        a.setDurationMs(duration);
        a.setCreatedAt(LocalDateTime.now());
        try {
            auditMapper.insert(a);
        } catch (Exception e) {
            // 审计写失败不能把「工具已经真的执行了」变成失败返回（用户会以为没执行而重试）
            log.warn("mcp_tool_audit 写入失败（不影响工具结果）: {}", e.getClass().getSimpleName());
        }
    }

    /** 参数规范 JSON（键排序）的 SHA-256 十六进制摘要；绝不保存参数原文。 */
    private String argsDigest(Map<String, Object> args) {
        try {
            ObjectMapper canonical = new ObjectMapper();
            canonical.configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
            String json = canonical.writeValueAsString(args == null ? Map.of() : args);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] h = md.digest(json.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : h) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            return "digest-error";
        }
    }

    private static String truncate(String s, int n) {
        if (s == null) {
            return null;
        }
        return s.length() <= n ? s : s.substring(0, n);
    }
}
