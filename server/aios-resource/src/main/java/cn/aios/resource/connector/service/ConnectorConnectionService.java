package cn.aios.resource.connector.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.mapper.ConnectorConnectionMapper;
import cn.aios.resource.connector.support.QqMailProbe;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 连接状态机（docs/58 §3.4）。<b>状态只在这里判定</b>：CONNECTED 只在一次成功校验后写入，
 * 不存在「先标记已连接再后台校验」；校验失败置 UNVERIFIED 且保留 lastError。
 */
@Service
public class ConnectorConnectionService {

    private static final String EMAIL_RE = "^[A-Za-z0-9+._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$";
    private static final Pattern EMAIL = Pattern.compile(EMAIL_RE);

    private final ConnectorConnectionMapper connectionMapper;
    private final ConnectorCatalogService catalogService;
    private final SecretCodec secretCodec;
    private final QqMailProbe qqMailProbe;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ConnectorConnectionService(ConnectorConnectionMapper connectionMapper,
                                      ConnectorCatalogService catalogService,
                                      SecretCodec secretCodec,
                                      QqMailProbe qqMailProbe) {
        this.connectionMapper = connectionMapper;
        this.catalogService = catalogService;
        this.secretCodec = secretCodec;
        this.qqMailProbe = qqMailProbe;
    }

    /** 当前连接状态；无行 → NEED_AUTH。 */
    public String statusOf(Long tenantId, Long userId, String code) {
        ConnectorConnection c = find(tenantId, userId, code);
        return c == null ? ConnectorConnection.STATUS_NEED_AUTH : c.getStatus();
    }

    /** 提交 CREDENTIAL 凭据：真实 IMAP 校验，成功才落库。 */
    public ConnectResult connectWithCredential(AuthUser user, String code, Map<String, String> values) {
        ConnectorDef def = catalogService.requireDef(code);
        if (!ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            throw BizException.badRequest("该连接器不支持凭据连接方式");
        }
        String email = values == null ? null : values.get("email");
        String authCode = values == null ? null : values.get("authCode");
        if (email == null || !EMAIL.matcher(email).matches()) {
            throw BizException.badRequest("请输入合法的邮箱地址");
        }
        if (authCode == null || authCode.isBlank()) {
            throw BizException.badRequest("授权码不能为空");
        }

        // 真实校验：失败不写库，直接 400 带服务端原因
        String probeErr = qqMailProbe.verify(email, authCode);
        if (probeErr != null) {
            throw BizException.badRequest("QQ邮箱登录失败：" + probeErr);
        }

        // 成功：加密落库，状态 CONNECTED（仅在成功校验后写入）
        String credJson = secretCodec.encrypt(jsonOf("email", email, "authCode", authCode));
        LocalDateTime now = LocalDateTime.now();
        ConnectorConnection c = find(user.getTenantId(), user.getUserId(), code);
        boolean insert = c == null;
        if (insert) {
            c = new ConnectorConnection();
            c.setTenantId(user.getTenantId());
            c.setUserId(user.getUserId());
            c.setConnectorCode(code);
        }
        c.setStatus(ConnectorConnection.STATUS_CONNECTED);
        c.setAccountLabel(email);
        c.setCredentialJson(credJson);
        c.setConnectedAt(now);
        c.setLastCheckedAt(now);
        c.setLastError(null);
        c.setDisconnectedAt(null);
        if (insert) {
            connectionMapper.insert(c);
        } else {
            connectionMapper.updateById(c);
        }
        return new ConnectResult(ConnectorConnection.STATUS_CONNECTED, email);
    }

    /** 断开：置 NEED_AUTH + 清凭据（不物理删行，留痕）。 */
    public void disconnect(AuthUser user, String code) {
        ConnectorConnection c = find(user.getTenantId(), user.getUserId(), code);
        if (c == null) {
            return; // 本就没有连接，幂等
        }
        // 坑：updateById 走 NOT_NULL 字段策略，null 字段（accountLabel/credentialJson/lastError）
        // 会被静默跳过 ⇒ 断开后残留标签。必须 LambdaUpdateWrapper.set(...) 显式写 NULL。
        connectionMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ConnectorConnection>()
                        .eq(ConnectorConnection::getId, c.getId())
                        .set(ConnectorConnection::getStatus, ConnectorConnection.STATUS_NEED_AUTH)
                        .set(ConnectorConnection::getCredentialJson, null)
                        .set(ConnectorConnection::getAccountLabel, null)
                        .set(ConnectorConnection::getLastError, null)
                        .set(ConnectorConnection::getDisconnectedAt, LocalDateTime.now()));
    }

    /**
     * 关闭（停用）连接器：**只改状态，不清任何凭据**（2026-10-31 用户口径）。
     *
     * <p>为什么不能复用 {@link #disconnect}：disconnect 是**解绑**语义 —— 置 NEED_AUTH
     * 并把 credential_json / accountLabel 清空，于是再点「连接」必须重新填授权码或重新扫码。
     * 用户要的是「关闭」，关闭不该有破坏性：再开启必须原地恢复。</p>
     *
     * <p>关闭后是否还注入工具：不注入。所有闸门（{@code McpBuiltinBridge} /
     * {@code McpRegistryService} manifest / {@code MailService}）都只认 {@code CONNECTED}，
     * 新增的 {@code DISABLED} 自动被排除 —— 不需要在每处闸门再加判断。</p>
     *
     * <p>只允许从 CONNECTED / UNVERIFIED 转过来；NEED_AUTH（本来就没连）保持原状，
     * 避免把「未连接」伪装成「已关闭」。</p>
     */
    public String disable(AuthUser user, String code) {
        catalogService.requireDef(code); // 未知 code 直接拒绝
        ConnectorConnection c = find(user.getTenantId(), user.getUserId(), code);
        if (c == null) {
            return ConnectorConnection.STATUS_NEED_AUTH;
        }
        if (!ConnectorConnection.STATUS_CONNECTED.equals(c.getStatus())
                && !ConnectorConnection.STATUS_UNVERIFIED.equals(c.getStatus())) {
            return c.getStatus();
        }
        connectionMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ConnectorConnection>()
                        .eq(ConnectorConnection::getId, c.getId())
                        .set(ConnectorConnection::getStatus, ConnectorConnection.STATUS_DISABLED));
        return ConnectorConnection.STATUS_DISABLED;
    }

    /**
     * 开启（恢复）连接器：{@code DISABLED → CONNECTED}，**不触发任何认证**。
     *
     * <p>凭据自始至终没被关闭动作碰过（CREDENTIAL 在 credential_json，QR 在 mcp-hub 的
     * 本机凭据目录里都没动），所以这里只翻状态位即可 —— 这正是用户要的
     * 「连接器开启是不需要重新连接」。</p>
     *
     * <p>不是 DISABLED 的行原样返回：NEED_AUTH 仍然要用户去连接，
     * CONNECTED 重复点开启也无害（幂等）。</p>
     */
    public String enable(AuthUser user, String code) {
        catalogService.requireDef(code);
        ConnectorConnection c = find(user.getTenantId(), user.getUserId(), code);
        if (c == null) {
            return ConnectorConnection.STATUS_NEED_AUTH;
        }
        if (!ConnectorConnection.STATUS_DISABLED.equals(c.getStatus())) {
            return c.getStatus();
        }
        connectionMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ConnectorConnection>()
                        .eq(ConnectorConnection::getId, c.getId())
                        .set(ConnectorConnection::getStatus, ConnectorConnection.STATUS_CONNECTED));
        return ConnectorConnection.STATUS_CONNECTED;
    }

    /**
     * 内部通道：按显式 tenant/user 写入「已连接」（由 mcp-hub 在连接器授权成功后回调）。
     *
     * <p><b>为什么要这个方法</b>：连接态的真相源是这张表（manifest 闸门读它），
     * 而 OAuth 回调可能落在 mcp-hub（浏览器 302，手里没有用户 token），
     * 只能由 hub 用服务令牌把结果写回来。见 {@code /internal/v1/connectors/**} 与 docs/63 §9.2。</p>
     *
     * <p><b>为什么不用 AuthUser</b>：这条调用没有用户上下文，身份由服务令牌证明；
     * tenantId/userId 由 hub 从一次性 state 里取出（state 是我们自己签发的，绑定了 tenant+user）。</p>
     */
    public void upsertConnectedByUser(Long tenantId, Long userId, String code,
                                      String accountLabel, Map<String, String> credential) {
        ConnectorDef def = catalogService.requireDef(code); // 未知连接器直接拒绝，避免写脏行
        if (tenantId == null || tenantId < 0 || userId == null || userId <= 0) {
            throw BizException.badRequest("tenantId/userId 非法");
        }
        String label = (accountLabel == null || accountLabel.isBlank()) ? null : accountLabel;
        String credJson = (credential == null || credential.isEmpty())
                ? null : secretCodec.encrypt(jsonMap(credential));
        LocalDateTime now = LocalDateTime.now();
        ConnectorConnection c = find(tenantId, userId, code);
        if (c == null) {
            c = new ConnectorConnection();
            c.setTenantId(tenantId);
            c.setUserId(userId);
            c.setConnectorCode(code);
            c.setStatus(ConnectorConnection.STATUS_CONNECTED);
            c.setAccountLabel(label != null ? label : def.getName());
            c.setCredentialJson(credJson);
            c.setConnectedAt(now);
            c.setLastCheckedAt(now);
            c.setDisconnectedAt(null);
            connectionMapper.insert(c);
            return;
        }
        // 坑（同 disconnect）：updateById 走 NOT_NULL 策略，credentialJson 为 null 时会被静默跳过
        // ⇒ 「重新授权但这次没拿到密码」时旧凭据还留着。这里显式 set。
        connectionMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ConnectorConnection>()
                        .eq(ConnectorConnection::getId, c.getId())
                        .set(ConnectorConnection::getStatus, ConnectorConnection.STATUS_CONNECTED)
                        .set(ConnectorConnection::getAccountLabel, label != null ? label : def.getName())
                        .set(ConnectorConnection::getCredentialJson, credJson)
                        .set(ConnectorConnection::getConnectedAt, now)
                        .set(ConnectorConnection::getLastCheckedAt, now)
                        .set(ConnectorConnection::getLastError, null)
                        .set(ConnectorConnection::getDisconnectedAt, null));
    }

    /** 内部通道：按显式 tenant/user 断开（hub 侧 disconnect 后同步，幂等）。 */
    public void disconnectByUser(Long tenantId, Long userId, String code) {
        if (tenantId == null || userId == null) {
            throw BizException.badRequest("tenantId/userId 非法");
        }
        ConnectorConnection c = find(tenantId, userId, code);
        if (c == null) {
            return; // 幂等
        }
        connectionMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ConnectorConnection>()
                        .eq(ConnectorConnection::getId, c.getId())
                        .set(ConnectorConnection::getStatus, ConnectorConnection.STATUS_NEED_AUTH)
                        .set(ConnectorConnection::getCredentialJson, null)
                        .set(ConnectorConnection::getAccountLabel, null)
                        .set(ConnectorConnection::getLastError, null)
                        .set(ConnectorConnection::getDisconnectedAt, LocalDateTime.now()));
    }

    /** 重新检测：CREDENTIAL 用解密后的凭据再跑一次探针；OAUTH2 无刷新令牌，仅返回当前状态。 */
    public VerifyResult verify(AuthUser user, String code) {
        ConnectorConnection c = find(user.getTenantId(), user.getUserId(), code);
        if (c == null || !ConnectorConnection.STATUS_CONNECTED.equals(c.getStatus())) {
            throw BizException.badRequest("连接器未处于已连接状态，无法检测");
        }
        ConnectorDef def = catalogService.requireDef(code);
        if (!ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            return new VerifyResult(c.getStatus(), c.getLastError());
        }
        try {
            JsonNode node = objectMapper.readTree(secretCodec.decrypt(c.getCredentialJson()));
            String email = node.path("email").asText();
            String authCode = node.path("authCode").asText();
            String err = qqMailProbe.verify(email, authCode);
            if (err == null) {
                c.setStatus(ConnectorConnection.STATUS_CONNECTED);
                c.setLastCheckedAt(LocalDateTime.now());
                c.setLastError(null);
                connectionMapper.updateById(c);
                return new VerifyResult(ConnectorConnection.STATUS_CONNECTED, null);
            }
            c.setStatus(ConnectorConnection.STATUS_UNVERIFIED);
            c.setLastError(err);
            c.setLastCheckedAt(LocalDateTime.now());
            connectionMapper.updateById(c);
            return new VerifyResult(ConnectorConnection.STATUS_UNVERIFIED, err);
        } catch (Exception e) {
            throw new IllegalStateException("重新检测失败：凭据解密异常", e);
        }
    }

    private ConnectorConnection find(Long tenantId, Long userId, String code) {
        return connectionMapper.selectOne(new LambdaQueryWrapper<ConnectorConnection>()
                .eq(ConnectorConnection::getTenantId, tenantId)
                .eq(ConnectorConnection::getUserId, userId)
                .eq(ConnectorConnection::getConnectorCode, code));
    }

    private String jsonOf(String k1, String v1, String k2, String v2) {
        java.util.Map<String, String> m = new java.util.LinkedHashMap<>();
        m.put(k1, v1);
        m.put(k2, v2);
        return jsonMap(m);
    }

    /** 加密前把凭据打成 JSON（内部回写通道用，字段由调用方白名单决定）。 */
    private String jsonMap(Map<String, String> values) {
        try {
            return objectMapper.writeValueAsString(values);
        } catch (Exception e) {
            throw new IllegalStateException("构造凭据 JSON 失败", e);
        }
    }

    public record ConnectResult(String status, String accountLabel) {
    }

    public record VerifyResult(String status, String lastError) {
    }
}
