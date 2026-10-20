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
        c.setStatus(ConnectorConnection.STATUS_NEED_AUTH);
        c.setCredentialJson(null);
        c.setAccountLabel(null);
        c.setLastError(null);
        c.setDisconnectedAt(LocalDateTime.now());
        connectionMapper.updateById(c);
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
        try {
            com.fasterxml.jackson.databind.node.ObjectNode n = objectMapper.createObjectNode();
            n.put(k1, v1);
            n.put(k2, v2);
            return objectMapper.writeValueAsString(n);
        } catch (Exception e) {
            throw new IllegalStateException("构造凭据 JSON 失败", e);
        }
    }

    public record ConnectResult(String status, String accountLabel) {
    }

    public record VerifyResult(String status, String lastError) {
    }
}
