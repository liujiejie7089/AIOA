package cn.aios.resource.connector.mail;

import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.mcp.spi.McpBuiltinHandler;
import cn.aios.security.AuthUser;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Set;

/**
 * qq_mail 内建 MCP 服务器（BUILTIN）的 6 个工具实现入口。
 *
 * <p>实现 {@link McpBuiltinHandler}：{@code serverCode()} 返回 {@code "qq_mail"}；
 * {@code supports(tool)} 覆盖 6 个工具名；{@code call} 按契约分派到 {@link MailService}。
 * 参数名严格对齐 §10.3：folder 默认 INBOX、limit 默认 10 上限 30、unreadOnly 默认 false、
 * uid 整数、query/to/subject/body/cc/draftId/requestId 按契约。返回可直接 JSON 化的 Map/List。</p>
 *
 * <p>身份仅来自 {@link AuthUser}（网关用调用方 token 解析），绝不从入参接受 tenantId/userId。</p>
 */
@Component
public class MailMcpHandler implements McpBuiltinHandler {

    private static final Set<String> TOOLS = Set.of(
            "list_folders", "list_messages", "read_message",
            "search_messages", "create_draft", "send_draft");

    private final MailService mailService;

    public MailMcpHandler(MailService mailService) {
        this.mailService = mailService;
    }

    @Override
    public String serverCode() {
        return "qq_mail";
    }

    @Override
    public boolean supports(String tool) {
        return TOOLS.contains(tool);
    }

    @Override
    public Object call(String tool, Map<String, Object> args, AuthUser user) {
        args = args == null ? Map.of() : args;
        switch (tool) {
            case "list_folders":
                return mailService.listFolders(user);
            case "list_messages": {
                String folder = getString(args, "folder", "INBOX");
                int limit = clamp(getInt(args, "limit", 10), 1, 30);
                boolean unreadOnly = getBool(args, "unreadOnly", false);
                return mailService.listMessages(user, folder, limit, unreadOnly);
            }
            case "read_message": {
                long uid = getLong(args, "uid", 0);
                if (uid <= 0) throw new BizException("uid 无效");
                String folder = getString(args, "folder", "INBOX");
                return mailService.readMessage(user, uid, folder);
            }
            case "search_messages": {
                String query = getString(args, "query", "");
                String folder = getString(args, "folder", "INBOX");
                int limit = clamp(getInt(args, "limit", 10), 1, 30);
                return mailService.searchMessages(user, query, folder, limit);
            }
            case "create_draft": {
                String to = getString(args, "to", "");
                String subject = getString(args, "subject", "");
                String body = getString(args, "body", "");
                String cc = getString(args, "cc", "");
                return mailService.createDraft(user, to, subject, body, cc);
            }
            case "send_draft": {
                long draftId = getLong(args, "draftId", 0);
                if (draftId <= 0) throw new BizException("draftId 无效");
                String requestId = getString(args, "requestId", "");
                return mailService.sendDraft(user, draftId, requestId);
            }
            default:
                throw new BizException("未知工具：" + tool);
        }
    }

    private static String getString(Map<String, Object> args, String k, String def) {
        Object v = args.get(k);
        return v == null ? def : String.valueOf(v);
    }

    private static int getInt(Map<String, Object> args, String k, int def) {
        Object v = args.get(k);
        if (v == null) return def;
        if (v instanceof Number n) return n.intValue();
        try { return Integer.parseInt(String.valueOf(v)); } catch (Exception e) { return def; }
    }

    private static long getLong(Map<String, Object> args, String k, long def) {
        Object v = args.get(k);
        if (v == null) return def;
        if (v instanceof Number n) return n.longValue();
        try { return Long.parseLong(String.valueOf(v)); } catch (Exception e) { return def; }
    }

    private static boolean getBool(Map<String, Object> args, String k, boolean def) {
        Object v = args.get(k);
        if (v == null) return def;
        if (v instanceof Boolean b) return b;
        return Boolean.parseBoolean(String.valueOf(v));
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
