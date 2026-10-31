package cn.aios.resource.connector.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.mcp.service.McpRegistryService;
import cn.aios.resource.connector.service.ConnectorConnectionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 连接器连接态的内部回写通道（服务间调用，非用户接口）。前缀 {@code /internal/v1/connectors}。
 *
 * <p><b>为什么需要它</b>：连接态的真相源是 {@code connector_connection} ——
 * {@code /api/v1/mcp/manifest} 的闸门就是读这张表决定「这个用户能不能拿到该连接器的工具」。
 * 但连接器授权（OAuth）的回调可能落在 mcp-hub 上：那是一段浏览器 302，只有 {@code code/state}，
 * <b>手里没有用户 token</b>，所以 hub 无法用用户身份调 {@code /api/v1/connectors/**}。
 * 只能由 hub 用服务令牌（claim {@code svc=hub}）把结果写回来。</p>
 *
 * <p>此前 hub 只写自己的 SQLite，Java 这张表永远是 NEED_AUTH ⇒
 * 「用 MCP 的 connect 工具连上了，下一轮对话工具却消失了」（docs/63 §9.2）。</p>
 *
 * <p><b>安全边界</b>：</p>
 * <ul>
 *   <li>路径在 {@code /internal/**} 下 ⇒ 由 {@code ServiceTokenFilter} 强制校验服务令牌，
 *       无票/票非法一律 401；</li>
 *   <li>{@code tenantId/userId} 由调用方给出，但只能来自 hub 自己签发的一次性 state
 *       （state 签发时绑定了 tenant+user），hub 无法凭空指定他人 —— 除非它自己被攻破，
 *       那时任何服务令牌都能做更多事，不是本接口能兜住的；</li>
 *   <li>连接器 code 必须存在于 {@code connector_def}（{@code requireDef}），防止写脏行；</li>
 *   <li>不接收 {@code status} 以外的自由字段，凭据字段整包加密存，不回显。</li>
 * </ul>
 */
@Slf4j
@RestController
@RequestMapping("/internal/v1/connectors")
@RequiredArgsConstructor
public class InternalConnectorController {

    private final ConnectorConnectionService connectionService;
    private final McpRegistryService mcpRegistry;

    /**
     * 标记「该用户已在该连接器上完成授权」。
     *
     * <p>幂等 upsert：重复调用只刷新 connectedAt/凭据，不会产生第二行
     * （唯一键 tenant+user+code，见 V96）。</p>
     */
    @PostMapping("/{code}/connection")
    public ApiResponse<Map<String, Object>> upsert(@PathVariable String code,
                                                   @RequestBody ConnectionBody body) {
        if (body == null) {
            throw BizException.badRequest("请求体不能为空");
        }
        String status = body.status() == null ? ConnectorConnection.STATUS_CONNECTED : body.status();
        if (!ConnectorConnection.STATUS_CONNECTED.equals(status)) {
            throw BizException.badRequest("本接口只接受 status=CONNECTED（断开请调 .../connection/disconnect）");
        }
        connectionService.upsertConnectedByUser(body.tenantId(), body.userId(), code,
                body.accountLabel(), body.credential());
        // 连上 ≠ AI 能用：内置 MCP 服务器种子行是 trusted=0，而 manifest 与执行闸门都只认
        // trusted=1 ⇒ 用户扫码成功、面板显示「已连接」，AI 那边却回「没有可用的连接」
        // （2026-10-31 生产现场，企微）。这里在连接态落库后顺手把内置服务器过一遍信任闸门。
        // 失败**不阻断**连接态：连没连上 与 给不给 AI 用 是两件事，探测抖不该让授权白扫。
        try {
            McpRegistryService.TrustResult tr = mcpRegistry.trustBuiltinByConnector(code);
            if (!tr.ok()) {
                log.warn("连接器 {} 已置为 CONNECTED，但内置 MCP 服务器自动信任未通过：{}", code, tr.error());
            } else if (tr.error() != null) {
                log.warn("连接器 {} 已信任，但探测未通过（工具目录可能为空）：{}", code, tr.error());
            } else {
                log.info("连接器 {} 已信任，工具 {} 个", code, tr.toolCount());
            }
        } catch (Exception e) {
            log.warn("连接器 {} 自动信任异常（不影响连接态）：{}", code, e.toString());
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("status", ConnectorConnection.STATUS_CONNECTED);
        out.put("tenantId", body.tenantId());
        out.put("userId", body.userId());
        out.put("code", code);
        return ApiResponse.ok(out);
    }

    /** 标记「该用户已断开」（幂等；无行也返回 ok）。 */
    @PostMapping("/{code}/connection/disconnect")
    public ApiResponse<Map<String, Object>> disconnect(@PathVariable String code,
                                                      @RequestBody ConnectionBody body) {
        if (body == null) {
            throw BizException.badRequest("请求体不能为空");
        }
        connectionService.disconnectByUser(body.tenantId(), body.userId(), code);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("status", ConnectorConnection.STATUS_NEED_AUTH);
        out.put("tenantId", body.tenantId());
        out.put("userId", body.userId());
        out.put("code", code);
        return ApiResponse.ok(out);
    }

    /**
     * 回写请求体。
     *
     * @param credential 已由用户授权的身份字段（userid/name/biz_mail/...），整包加密后落库；
     *                   绝不能放密码类字段，本通道只承载「授权结果」。
     */
    public record ConnectionBody(Long tenantId,
                                 Long userId,
                                 String status,
                                 String accountLabel,
                                 Map<String, String> credential) {
    }
}
