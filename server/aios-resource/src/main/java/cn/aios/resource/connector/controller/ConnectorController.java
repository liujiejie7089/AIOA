package cn.aios.resource.connector.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.service.ConnectorCatalogService;
import cn.aios.resource.connector.service.ConnectorConnectionService;
import cn.aios.resource.connector.service.WeComCliGateway;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 连接器用户端接口（docs/58 §4）。前缀 /api/v1/connectors。
 *
 * <pre>
 *   GET    /api/v1/connectors                           目录 + 我的状态 + 就绪度
 *   GET    /api/v1/connectors/{code}                    详情（mode / fields / helpText / helpUrl）
 *   POST   /api/v1/connectors/{code}/connect/start      CREDENTIAL→fields；QR→mode=QR
 *   POST   /api/v1/connectors/{code}/connect/credential 提交凭据（真实校验后落库）
 *   POST   /api/v1/connectors/{code}/qr                 发起扫码（QR，返回二维码 data URL）
 *   GET    /api/v1/connectors/{code}/qr-status          轮询扫码是否完成（QR）
 *   POST   /api/v1/connectors/{code}/qr-bind            扫码完成后确认绑定（QR）
 *   POST   /api/v1/connectors/{code}/verify             重新检测
 *   POST   /api/v1/connectors/{code}/disconnect         断开
 * </pre>
 *
 * <p><b>2026-10-30 删除了 OAUTH2 分支与 OAuth 回跳端点</b>：唯一使用 OAUTH2 的
 * {@code wechat_work}（自建应用网页授权）已下线，{@code WeComOAuthService} 一并物理删除
 * （docs/64 §9.7）。现在只剩两种授权形态：CREDENTIAL（用户填授权码）与 QR（扫码）。
 * 将来若要接第三个 OAuth 连接器，请新建一个通用的 OAuth 服务，不要复活企微那套。</p>
 *
 * <p><b>QR 为什么是三个端点而不是一个</b>：扫码是先出图、人再去扫、扫码结果在服务端异步完成，
 * 天然是三段式。{@code connect/start} 只回 {@code mode=QR} 用来选弹层，真正的二维码单独取，
 * 这样「弹层里点了取消」不会在 hub 侧留下一个没人扫的 {@code auth init} 进程 ——
 * 进程只在用户真的看到二维码之后才起。</p>
 */
@RestController
@RequestMapping("/api/v1/connectors")
@RequiredArgsConstructor
public class ConnectorController {

    private final ConnectorCatalogService catalogService;
    private final ConnectorConnectionService connectionService;
    private final WeComCliGateway weComCliGateway;

    @GetMapping
    public ApiResponse<List<ConnectorCatalogService.ConnectorItem>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(catalogService.list(user.getTenantId(), user.getUserId()));
    }

    @GetMapping("/{code}")
    public ApiResponse<ConnectorCatalogService.ConnectorDetail> detail(@PathVariable String code) {
        AuthUserContext.require();
        return ApiResponse.ok(catalogService.detail(code, AuthUserContext.tenantIdOrDefault()));
    }

    @PostMapping("/{code}/connect/start")
    public ApiResponse<ConnectorCatalogService.ConnectorStart> start(@PathVariable String code) {
        AuthUserContext.require();
        ConnectorDef def = catalogService.requireDef(code);
        if (ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            return ApiResponse.ok(new ConnectorCatalogService.ConnectorStart(
                    "CREDENTIAL", null, catalogService.credentialFields(code)));
        }
        if (ConnectorDef.AUTH_MODE_QR.equals(def.getAuthMode())) {
            // QR 没有可跳转的授权地址：前端据 mode 打开二维码弹层，再调 /qr 取图。
            return ApiResponse.ok(new ConnectorCatalogService.ConnectorStart("QR", null, List.of()));
        }
        // 没有第三种授权形态了（OAUTH2 随 wechat_work 一起下线）。宁可明确报错，
        // 也不要静默回一个前端无法处理的空 mode。
        throw BizException.badRequest("该连接器暂不支持网页授权，请联系管理员：" + code);
    }

    /**
     * QR：发起扫码，返回 {@code {qr:"data:image/png;base64,...", expiresIn, hint}}。
     *
     * <p>会阻塞到二维码 PNG 落盘（hub 侧上限 20s），所以前端必须显示「正在生成二维码」。
     * 未绑定时调用它会真的在 hub 侧起一个 {@code wecom-cli auth init} 进程等扫码，
     * 因此这个端点只能由用户点击触发，不能放进轮询.</p>
     */
    @PostMapping("/{code}/qr")
    public ApiResponse<Map<String, Object>> qr(@PathVariable String code, HttpServletRequest request) {
        AuthUserContext.require();
        requireQrMode(code);
        return ApiResponse.ok(weComCliGateway.qr(authorization(request)));
    }

    /**
     * QR：轮询扫码结果（{@code authorized=false} 表示**这一次**还没扫完）。只读，可安全轮询。
     *
     * <p>必须走 {@code qr-status} 而不是 {@code status}：后者含开发态的共享授权兜底，
     * 会让「用户还没扫码」在第一次轮询时就返回 authorized=true，前端随即自动 /qr-bind，
     * 落库成 CONNECTED —— 现象是二维码刚出现就自己"扫完了"。见 {@link WeComCliGateway#qrStatus}。</p>
     */
    @GetMapping("/{code}/qr-status")
    public ApiResponse<Map<String, Object>> qrStatus(@PathVariable String code, HttpServletRequest request) {
        AuthUserContext.require();
        requireQrMode(code);
        return ApiResponse.ok(weComCliGateway.qrStatus(authorization(request)));
    }

    /**
     * QR：扫码完成后确认绑定。
     *
     * <p><b>连接态由 Java 自己落库</b>，不依赖 hub 用服务令牌回写 {@code connector_connection}。
     * 理由：hub 的回写要 {@code AIOS_SERVICE_TOKEN_SECRET}，开发环境常常没配；那种情况下
     * 「扫码成功、界面却显示未连接、数字人也拿不到工具」—— 用户完全无法自查。
     * 这里 hub 已经确认 {@code bound=true}（它读的是 CLI 的真实授权状态，不是自述），
     * Java 直接据此写 CONNECTED 是可信的，且不新增跨进程依赖。</p>
     */
    @PostMapping("/{code}/qr-bind")
    public ApiResponse<Map<String, Object>> qrBind(@PathVariable String code, HttpServletRequest request) {
        AuthUser user = AuthUserContext.require();
        requireQrMode(code);
        Map<String, Object> res = weComCliGateway.bind(authorization(request));
        if (!Boolean.TRUE.equals(res.get("bound"))) {
            // hub 说没绑上：绝不写 CONNECTED（否则 manifest 会给模型一个必然报错的工具）
            throw BizException.badRequest(
                    String.valueOf(res.getOrDefault("message", "企业微信尚未完成扫码授权")));
        }
        String label = blankToNull(res.get("accountLabel"));
        connectionService.upsertConnectedByUser(user.getTenantId(), user.getUserId(), code,
                label, Map.of("binding", "cli-qr"));
        return ApiResponse.ok(Map.of(
                "status", "CONNECTED",
                "accountLabel", label == null ? "" : label,
                "sharedProfile", Boolean.TRUE.equals(res.get("sharedProfile"))));
    }

    @PostMapping("/{code}/connect/credential")
    public ApiResponse<ConnectorConnectionService.ConnectResult> connectCredential(
            @PathVariable String code, @RequestBody CredentialBody body) {
        AuthUser user = AuthUserContext.require();
        Map<String, String> values = (body == null || body.values() == null) ? Map.of() : body.values();
        return ApiResponse.ok(connectionService.connectWithCredential(user, code, values));
    }

    @PostMapping("/{code}/verify")
    public ApiResponse<ConnectorConnectionService.VerifyResult> verify(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(connectionService.verify(user, code));
    }

    @PostMapping("/{code}/disconnect")
    public ApiResponse<Map<String, String>> disconnect(@PathVariable String code,
                                                       HttpServletRequest request) {
        AuthUser user = AuthUserContext.require();
        ConnectorDef def = catalogService.requireDef(code);
        if (ConnectorDef.AUTH_MODE_QR.equals(def.getAuthMode())) {
            // 顺序要紧：先让 hub 真的删掉该用户的配置目录，再改库。
            // 反过来的话库里已显示 NEED_AUTH，而对方企微凭据还躺在磁盘上 —— 用户以为解绑了。
            // hub 抛错就整体失败（宁可让用户重试，也不能「假装解绑」）。
            weComCliGateway.disconnect(authorization(request));
        }
        connectionService.disconnect(user, code);
        return ApiResponse.ok(Map.of("status", "NEED_AUTH"));
    }

    /**
     * QR 端点只能用在 {@code auth_mode=QR} 的连接器上。
     *
     * <p>存在的理由：{@code /{code}/qr} 在 hub 侧会真的起一个等扫码的子进程。若放任任意 code
     * 打进来，就等于给了一个「用别人的连接器身份去启动扫码」的入口 —— 直接按目录拒绝。</p>
     */
    private void requireQrMode(String code) {
        ConnectorDef def = catalogService.requireDef(code);
        if (!ConnectorDef.AUTH_MODE_QR.equals(def.getAuthMode())) {
            throw BizException.badRequest("该连接器不支持扫码授权：" + code);
        }
    }

    /** 原样转发调用者凭据：hub 用它回调 /api/v1/auth/me 判定「这是谁的扫码」。 */
    private static String authorization(HttpServletRequest request) {
        String auth = request.getHeader("Authorization");
        return (auth == null || auth.isBlank()) ? null : auth;
    }

    private static String blankToNull(Object v) {
        if (v == null) {
            return null;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() ? null : s;
    }

    public record CredentialBody(Map<String, String> values) {
    }
}
