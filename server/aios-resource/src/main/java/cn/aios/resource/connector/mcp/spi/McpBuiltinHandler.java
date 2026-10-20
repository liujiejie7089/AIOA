package cn.aios.resource.connector.mcp.spi;

import cn.aios.security.AuthUser;

import java.util.Map;

/**
 * 内置 MCP 服务器（BUILTIN）的工具实现契约。
 *
 * <p><b>为什么需要这个接口</b>：MCP 的传输层（Streamable HTTP 网关）与工具清单都在
 * {@code connector.mcp} 包里，而具体能力分属不同业务包（邮件在 {@code connector.mail}，
 * 企业微信在 {@code connector.wecom}）。用 Spring 的 Bean 集合注入把它们解耦：
 * 加一个内置服务器 = 加一个 {@code @Component implements McpBuiltinHandler} + V97 里加一行种子，
 * 不改 MCP 桥接代码。</p>
 *
 * <p><b>安全边界</b>：实现方拿到的 {@link AuthUser} 是<b>调用者本人</b>（网关用调用方 token
 * 解析出来的），因此工具内部一律用 {@code user.getTenantId()/getUserId()} 取凭据，
 * <b>禁止</b>从入参接受 tenantId / userId —— 那会变成越权入口。</p>
 *
 * <p><b>失败语义</b>：工具失败请抛 {@code BizException}（用户可读中文原因）或返回
 * {@code Map.of("ok", false, "error", "…")}；由 {@code McpBuiltinBridge} 统一收敛成
 * MCP 的 {@code CallToolResult.isError}，<b>不要</b>返回空 Map 假装成功。</p>
 */
public interface McpBuiltinHandler {

    /**
     * 归属的服务器 code，与 {@code mcp_server.code} 一致（如 {@code qq_mail}）。
     */
    String serverCode();

    /**
     * 是否实现该工具（工具名与 {@code mcp_server_tool.name} 一致）。
     */
    boolean supports(String tool);

    /**
     * 执行工具。
     *
     * @param tool  工具名（不含前缀）
     * @param args  模型给出的参数（可能为 null）
     * @param user  调用者（唯一可信身份来源）
     * @return 工具结果；建议为可直接 JSON 序列化的 Map / List / 标量
     */
    Object call(String tool, Map<String, Object> args, AuthUser user);
}
