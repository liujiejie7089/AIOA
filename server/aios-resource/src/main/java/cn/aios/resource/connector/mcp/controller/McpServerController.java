package cn.aios.resource.connector.mcp.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.mcp.service.McpBuiltinBridge;
import cn.aios.resource.connector.mcp.service.McpBuiltinBridge.CallResult;
import cn.aios.resource.connector.mcp.service.McpRegistryService;
import cn.aios.resource.connector.mcp.service.McpRegistryService.BuiltinCatalogItem;
import cn.aios.resource.connector.mcp.service.McpRegistryService.ManifestItem;
import cn.aios.resource.connector.mcp.service.McpRegistryService.RegisterRequest;
import cn.aios.resource.connector.mcp.service.McpRegistryService.ServerItem;
import cn.aios.resource.connector.mcp.service.McpRegistryService.ToolItem;
import cn.aios.resource.connector.mcp.service.McpRegistryService.TrustResult;
import cn.aios.resource.connector.mcp.service.McpProbeClient.ProbeResult;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * MCP 服务器注册表接口（docs/59 §10.3，前缀 /api/v1/mcp）。
 *
 * <pre>
 *   GET    /api/v1/mcp/servers                      列表（租户可见）
 *   POST   /api/v1/mcp/servers                      注册外部服务器（trusted=0）
 *   POST   /api/v1/mcp/servers/{code}/probe         仅探测（落 status/last_error/last_probe_at）
 *   POST   /api/v1/mcp/servers/{code}/trust         信任闸门：探测→ok 才 trusted=1 + 覆盖写工具
 *   POST   /api/v1/mcp/servers/{code}/untrust       取消信任
 *   DELETE /api/v1/mcp/servers/{code}               逻辑删（BUILTIN 不可删）
 *   GET    /api/v1/mcp/servers/{code}/tools         已登记工具清单
 *   GET    /api/v1/mcp/manifest                     agent 用：仅 trusted=1 且（BUILTIN⇒CONNECTED）
 *   POST   /api/v1/mcp/builtin/{code}/call          内置工具执行闸门（写 mcp_tool_audit）
 *   GET    /api/v1/mcp/builtin/catalog              内置工具目录全量
 * </pre>
 *
 * <p>所有接口均 {@code AuthUserContext.require()}，不在路径/参数里透传 tenantId/userId。</p>
 */
@RestController
@RequestMapping("/api/v1/mcp")
@RequiredArgsConstructor
public class McpServerController {

    private final McpRegistryService registry;
    private final McpBuiltinBridge bridge;

    @GetMapping("/servers")
    public ApiResponse<List<ServerItem>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.list(user));
    }

    @PostMapping("/servers")
    public ApiResponse<ServerItem> create(@RequestBody(required = false) RegisterRequest body) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.registerExternal(user, body));
    }

    @PostMapping("/servers/{code}/probe")
    public ApiResponse<ProbeResult> probe(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.probe(user, code));
    }

    @PostMapping("/servers/{code}/trust")
    public ApiResponse<TrustResult> trust(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.trust(user, code));
    }

    @PostMapping("/servers/{code}/untrust")
    public ApiResponse<TrustResult> untrust(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.untrust(user, code));
    }

    @DeleteMapping("/servers/{code}")
    public ApiResponse<Void> delete(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        registry.delete(user, code);
        return ApiResponse.ok();
    }

    @GetMapping("/servers/{code}/tools")
    public ApiResponse<List<ToolItem>> tools(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.tools(user, code));
    }

    @GetMapping("/manifest")
    public ApiResponse<List<ManifestItem>> manifest() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(registry.manifest(user));
    }

    @PostMapping("/builtin/{code}/call")
    public ApiResponse<CallResult> call(@PathVariable String code,
                                       @RequestBody(required = false) CallBody body) {
        AuthUser user = AuthUserContext.require();
        String tool = body == null ? null : body.tool();
        Map<String, Object> args = body == null ? null : body.args();
        return ApiResponse.ok(bridge.call(user, code, tool, args));
    }

    @GetMapping("/builtin/catalog")
    public ApiResponse<List<BuiltinCatalogItem>> catalog() {
        AuthUserContext.require();
        return ApiResponse.ok(registry.builtinCatalog());
    }

    /**
     * 内置工具调用请求体。
     *
     * <p>{@code args} 同时接受 {@code arguments} 键（{@code JsonAlias}）：契约（docs/59 §10.3）写的是
     * {@code {tool, arguments}}，而 MCP 协议的字段名也是 {@code arguments}；hub 会原样转发协议里的名字。
     * 只认 {@code args} 会让 hub 转发过来时参数**静默变成 null**（工具照跑、但丢掉全部入参），
     * 这是最难发现的一类契约漂移，故在此显式兜住两种写法。</p>
     */
    public record CallBody(String tool,
                           @com.fasterxml.jackson.annotation.JsonAlias({"args", "arguments"})
                           Map<String, Object> args) {
    }
}
