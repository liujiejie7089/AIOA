package cn.aios.resource.connector.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.service.ConnectorTenantAccessService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 连接器按租户接入 API（docs/92 阶段 2/4）。
 *
 * <pre>
 *   GET    /api/v1/connector-access                   本租户所有按租户接入连接器状态清单
 *   GET    /api/v1/connector-access/{code}            本租户接入四态（登录可读，用于用户端提示）
 *   GET    /api/v1/mcp/access/{code}/check?tool=xxx    hub 回调：调用前准入校验 + 写审计
 *   POST   /api/v1/admin/connector-access/{code}/enable    启用（租户管理员）
 *   POST   /api/v1/admin/connector-access/{code}/disable   停用（租户管理员）
 *   PUT    /api/v1/admin/connector-access/{code}/config    配置机构白名单 / 租户级配置（租户管理员）
 * </pre>
 *
 * <p><b>身份口径</b>：全部走 {@code AuthUserContext.require()}，tenantId / userId 从登录态取，
 * 不在路径或参数里透传 —— 与 {@code McpServerController} 一致，防止改个参数就查别人租户。
 * hub 回调端点同样带调用者的 JWT（由 agent 经 MCP header 透传，见
 * {@code agent/aios_ai/tools/client.py}），因此 Java 仍是唯一身份权威，hub 不持密钥、不解析 token。</p>
 *
 * <p><b>管理动作</b>的权限闸在 {@code ConnectorTenantAccessService#requireManage}：
 * {@code PermissionCatalog.CONNECTOR_ACCESS_MANAGE}（系统/租户管理员），沿用全仓
 * 「手动 holds() 校验、不用 @PreAuthorize」的惯例。</p>
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class ConnectorAccessController {

    private final ConnectorTenantAccessService accessService;

    /** 本租户所有按租户接入连接器的状态清单（数据驱动，前端不硬编码 code）。 */
    @GetMapping("/connector-access")
    public ApiResponse<List<ConnectorTenantAccessService.AccessView>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(accessService.list(tenantId(user)));
    }

    /** 本租户接入状态。普通登录用户也可读：未接入时用户端据此给可执行提示，而不是报「数据源故障」。 */
    @GetMapping("/connector-access/{code}")
    public ApiResponse<ConnectorTenantAccessService.AccessView> status(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(accessService.view(tenantId(user), code));
    }

    /**
     * hub 回调：scfy 原生 server 每次 {@code tools/call} 前调用，判定租户是否准入并写审计。
     *
     * <p>返回体经 {@code ApiResponse} 包成 {@code {code, data:{ok,reason,...}}}；hub 侧按
     * {@code body["data"]} 读取（与 {@code builtin.py#_dispatch} 同款）。判定被拒时
     * {@code ok=false} + 中文 reason，hub 直接把它作为工具结果回给模型，<b>不发</b>非遗 GET。</p>
     */
    @GetMapping("/mcp/access/{code}/check")
    public ApiResponse<ConnectorTenantAccessService.CheckResult> check(
            @PathVariable String code,
            @RequestParam(required = false) String tool) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(accessService.check(user, code, tool));
    }

    @PostMapping("/admin/connector-access/{code}/enable")
    public ApiResponse<ConnectorTenantAccessService.AccessView> enable(@PathVariable String code) {
        AuthUser admin = AuthUserContext.require();
        return ApiResponse.ok(accessService.enable(admin, code));
    }

    @PostMapping("/admin/connector-access/{code}/disable")
    public ApiResponse<ConnectorTenantAccessService.AccessView> disable(@PathVariable String code) {
        AuthUser admin = AuthUserContext.require();
        return ApiResponse.ok(accessService.disable(admin, code));
    }

    @PutMapping("/admin/connector-access/{code}/config")
    public ApiResponse<ConnectorTenantAccessService.AccessView> configure(
            @PathVariable String code,
            @RequestBody(required = false) ConfigureBody body) {
        AuthUser admin = AuthUserContext.require();
        List<Long> scope = body == null ? null : body.scopeInstitutions();
        Map<String, Object> config = body == null ? null : body.config();
        return ApiResponse.ok(accessService.configure(admin, code, scope, config));
    }

    private static Long tenantId(AuthUser u) {
        return u.getTenantId() == null ? 0L : u.getTenantId();
    }

    /**
     * 配置请求体。{@code scopeInstitutions=null} 表示不修改，传空数组表示清空白名单（全租户）；
     * {@code config=null} 表示不修改，传空对象表示清空租户级配置。
     */
    public record ConfigureBody(List<Long> scopeInstitutions, Map<String, Object> config) {
    }
}
