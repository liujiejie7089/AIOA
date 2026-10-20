package cn.aios.resource.connector.mail;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.mapper.ConnectorConnectionMapper;
import cn.aios.resource.connector.mail.entity.ConnectorMailDraft;
import cn.aios.resource.connector.mail.mapper.ConnectorMailDraftMapper;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * 邮件业务层：凭据解析（AES-256-GCM 解密，仅当 CONNECTED）、IMAP 读、SMTP 发的落库与幂等编排。
 *
 * <p><b>纪律</b>：</p>
 * <ul>
 *   <li>读类工具直接转 {@link ImapClient}；</li>
 *   <li>{@code createDraft} 仅落库（status=DRAFT），<b>不发信</b>；</li>
 *   <li>{@code sendDraft} 按 {@code (tenant,user,requestId)} 幂等：已 SENT 直接返回首次结果；</li>
 *   <li>头注入防护：{@code to/cc/subject} 含换行字符一律拒绝（模型可控参数不得进 SMTP 头）；</li>
 *   <li>异常与日志绝不携带授权码 / 完整正文。</li>
 * </ul>
 */
@Service
@RequiredArgsConstructor
public class MailService {

    private static final String CONNECTOR_CODE = "qq_mail";
    private static final String STATUS_CONNECTED = "CONNECTED";
    private static final String STATUS_DRAFT = "DRAFT";
    private static final String STATUS_SENT = "SENT";
    private static final Pattern EMAIL = Pattern.compile("^[A-Za-z0-9+._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$");
    private static final int PREVIEW_LEN = 100;

    private final ConnectorConnectionMapper connectionMapper;
    private final ConnectorMailDraftMapper draftMapper;
    private final SecretCodec secretCodec;
    private final ImapClient imapClient;
    private final SmtpClient smtpClient;
    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final class Credential {
        final String email;
        final String authCode;

        Credential(String e, String a) {
            this.email = e;
            this.authCode = a;
        }
    }

    /** 查连接记录并解密凭据；未连接 / 解密失败抛中文 BizException。 */
    private Credential resolveCredential(AuthUser user) {
        ConnectorConnection c = connectionMapper.selectOne(new LambdaQueryWrapper<ConnectorConnection>()
                .eq(ConnectorConnection::getTenantId, user.getTenantId())
                .eq(ConnectorConnection::getUserId, user.getUserId())
                .eq(ConnectorConnection::getConnectorCode, CONNECTOR_CODE));
        if (c == null || !STATUS_CONNECTED.equals(c.getStatus())) {
            throw BizException.badRequest("QQ邮箱未连接：请先在连接器里完成授权");
        }
        try {
            JsonNode node = objectMapper.readTree(secretCodec.decrypt(c.getCredentialJson()));
            return new Credential(node.path("email").asText(), node.path("authCode").asText());
        } catch (Exception e) {
            throw BizException.badRequest("QQ邮箱凭据解密失败，请重新授权");
        }
    }

    public List<Map<String, Object>> listFolders(AuthUser user) {
        Credential cred = resolveCredential(user);
        return imapClient.listFolders(cred.email, cred.authCode);
    }

    public List<Map<String, Object>> listMessages(AuthUser user, String folder, int limit, boolean unreadOnly) {
        Credential cred = resolveCredential(user);
        return imapClient.listMessages(cred.email, cred.authCode, folder, limit, unreadOnly);
    }

    public Map<String, Object> readMessage(AuthUser user, long uid, String folder) {
        Credential cred = resolveCredential(user);
        return imapClient.readMessage(cred.email, cred.authCode, uid, folder);
    }

    public List<Map<String, Object>> searchMessages(AuthUser user, String query, String folder, int limit) {
        Credential cred = resolveCredential(user);
        return imapClient.searchMessages(cred.email, cred.authCode, query, folder, limit);
    }

    /** 仅落库，返回草稿标识，<b>不发信</b>。 */
    public Map<String, Object> createDraft(AuthUser user, String to, String subject, String body, String cc) {
        if (hasCrlf(to) || hasCrlf(cc) || hasCrlf(subject)) {
            throw BizException.badRequest("收件人 / 抄送 / 主题含非法换行字符");
        }
        if (to == null || to.isBlank()) throw BizException.badRequest("收件人不能为空");
        for (String a : splitEmails(to)) {
            if (!EMAIL.matcher(a).matches()) throw BizException.badRequest("收件人邮箱格式不正确：" + a);
        }
        if (cc != null && !cc.isBlank()) {
            for (String a : splitEmails(cc)) {
                if (!EMAIL.matcher(a).matches()) throw BizException.badRequest("抄送邮箱格式不正确：" + a);
            }
        }
        ConnectorMailDraft d = new ConnectorMailDraft();
        d.setTenantId(user.getTenantId());
        d.setUserId(user.getUserId());
        d.setToAddr(to);
        d.setCcAddr(cc);
        d.setSubject(subject);
        d.setBody(body);
        d.setStatus(STATUS_DRAFT);
        d.setRequestId(null);
        LocalDateTime now = LocalDateTime.now();
        d.setCreatedAt(now);
        d.setUpdatedAt(now);
        draftMapper.insert(d);
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("draftId", d.getId());
        r.put("to", to);
        r.put("subject", subject);
        r.put("preview", preview(body));
        r.put("status", STATUS_DRAFT);
        return r;
    }

    /** 幂等发送：同 (tenant,user,requestId) 已 SENT 直接返回首次结果；否则发信并落状态。 */
    public Map<String, Object> sendDraft(AuthUser user, long draftId, String requestId) {
        boolean fallback = (requestId == null || requestId.isBlank());
        if (fallback) requestId = "draft:" + draftId;

        ConnectorMailDraft existing = draftMapper.selectOne(new LambdaQueryWrapper<ConnectorMailDraft>()
                .eq(ConnectorMailDraft::getTenantId, user.getTenantId())
                .eq(ConnectorMailDraft::getUserId, user.getUserId())
                .eq(ConnectorMailDraft::getRequestId, requestId)
                .eq(ConnectorMailDraft::getStatus, STATUS_SENT));
        if (existing != null) {
            Map<String, Object> r = draftResult(existing);
            r.put("idempotent", true);
            r.put("requestId", requestId);
            return r;
        }

        ConnectorMailDraft d = draftMapper.selectById(draftId);
        if (d == null || !Objects.equals(d.getUserId(), user.getUserId())
                || !Objects.equals(d.getTenantId(), user.getTenantId())) {
            throw BizException.notFound("草稿不存在或无权操作");
        }
        if (!STATUS_DRAFT.equals(d.getStatus())) {
            throw BizException.badRequest("该草稿状态不可发送：" + d.getStatus());
        }
        if (hasCrlf(d.getToAddr()) || hasCrlf(d.getCcAddr()) || hasCrlf(d.getSubject())) {
            throw BizException.badRequest("草稿含非法换行字符，无法发送");
        }
        Credential cred = resolveCredential(user);
        try {
            String messageId = smtpClient.send(cred.email, cred.authCode,
                    d.getToAddr(), d.getCcAddr(), d.getSubject(), d.getBody());
            d.setStatus(STATUS_SENT);
            d.setSentAt(LocalDateTime.now());
            d.setMessageId(messageId);
            d.setRequestId(requestId);
            d.setLastError(null);
            d.setUpdatedAt(LocalDateTime.now());
            draftMapper.updateById(d);
            Map<String, Object> r = draftResult(d);
            r.put("idempotent", false);
            if (fallback) r.put("note", "requestId 未提供，已用 draftId 兜底，幂等键=" + requestId);
            return r;
        } catch (MailException e) {
            d.setStatus("FAILED");
            d.setLastError(truncate(e.getMessage()));
            d.setRequestId(requestId);
            d.setUpdatedAt(LocalDateTime.now());
            draftMapper.updateById(d);
            throw new BizException("发送失败：" + truncate(e.getMessage()));
        }
    }

    private Map<String, Object> draftResult(ConnectorMailDraft d) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("draftId", d.getId());
        r.put("to", d.getToAddr());
        r.put("subject", d.getSubject());
        r.put("status", d.getStatus());
        r.put("messageId", d.getMessageId());
        r.put("sentAt", d.getSentAt() == null ? null : d.getSentAt().toString());
        return r;
    }

    private String preview(String body) {
        if (body == null) return "";
        String p = body.replaceAll("\\s+", " ").trim();
        return p.length() <= PREVIEW_LEN ? p : p.substring(0, PREVIEW_LEN);
    }

    private boolean hasCrlf(String s) {
        return s != null && (s.contains("\r") || s.contains("\n"));
    }

    private List<String> splitEmails(String s) {
        List<String> out = new ArrayList<>();
        for (String a : s.split("[,;\\s]+")) {
            if (!a.isBlank()) out.add(a.trim());
        }
        return out;
    }

    private String truncate(String s) {
        if (s == null) return "";
        return s.length() <= 1024 ? s : s.substring(0, 1024);
    }
}
