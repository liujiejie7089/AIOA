package cn.aios.chat.tool;

import cn.aios.resource.service.ModelCredentialService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 「我的模型账号与共享」工具（2026-11-05）。
 *
 * <p><b>为什么必须有这个工具</b>：用户问「我把额度共享给谁了」「我现在能用谁的账号」，
 * 在这之前模型只能从对话历史里猜，或者干脆回答「请到页面查看」。而这类问题恰恰是
 * 「数字人该知道系统内部发生了什么」的典型：答案就在库里，只是模型看不见。</p>
 *
 * <p><b>不回传任何密钥</b>：以 {@code CredentialView} / {@code ShareView} 为唯一数据源，
 * 那里只有掩码（{@code sk-****3f9a}）与用量，没有明文 Key，也没有 baseUrl 之外的调优参数。</p>
 *
 * <p><b>三条口径分开列</b>：自己持有 / 公司提供 / 别人共享给我。
 * 合并成一张表会让模型把「公司账号」说成「你的账号」，用户真去删就删不动（权限不在他手里）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class MyModelAccountsToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "my_model_accounts";

    private final ModelCredentialService credentialService;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "查询当前用户的模型账号与共享关系：自己注册的账号、公司提供的账号、别人共享给我的账号，"
                + "以及我共享给同事的授权（含对方姓名、已用/上限词元、状态、到期时间）。"
                + "用户问「我有哪些模型账号」「我共享给谁了」「谁共享给我」「额度还剩多少」时调用。"
                + "不要凭记忆回答这类问题。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            Map<String, Object> acc = credentialService.myAccounts(user);
            List<ModelCredentialService.ShareView> byMe = credentialService.myInvites(user);
            List<ModelCredentialService.ShareView> toMe = credentialService.invitesToMe(user);

            List<Map<String, Object>> mine = brief(acc.get("mine"));
            List<Map<String, Object>> company = brief(acc.get("company"));
            List<Map<String, Object>> shared = brief(acc.get("shared"));

            List<Map<String, Object>> outByMe = new ArrayList<>();
            for (ModelCredentialService.ShareView s : byMe) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("shareId", s.id());
                row.put("credential", s.credentialName());
                row.put("provider", s.providerKey());
                row.put("colleague", s.granteeName());
                row.put("status", statusLabel(s.status()));
                row.put("usedTokens", s.usedTokens());
                row.put("quotaTokens", s.quotaTokens() == null || s.quotaTokens() == 0 ? "不限" : s.quotaTokens());
                row.put("expiresAt", s.expiresAt() == null ? "长期" : s.expiresAt().toLocalDate().toString());
                outByMe.add(row);
            }
            List<Map<String, Object>> inToMe = new ArrayList<>();
            for (ModelCredentialService.ShareView s : toMe) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("shareId", s.id());
                row.put("credential", s.credentialName());
                row.put("provider", s.providerKey());
                row.put("owner", s.ownerName());
                row.put("status", statusLabel(s.status()));
                row.put("usedTokens", s.usedTokens());
                row.put("quotaTokens", s.quotaTokens() == null || s.quotaTokens() == 0 ? "不限" : s.quotaTokens());
                row.put("expiresAt", s.expiresAt() == null ? "长期" : s.expiresAt().toLocalDate().toString());
                inToMe.add(row);
            }

            Map<String, Object> data = new LinkedHashMap<>();
            data.put("mine", mine);
            data.put("company", company);
            data.put("sharedToMe", shared.stream().map(c -> {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", c.get("name"));
                row.put("provider", c.get("provider"));
                row.put("model", c.get("model"));
                return row;
            }).toList());
            data.put("sharesGrantedByMe", outByMe);
            data.put("sharesGrantedToMe", inToMe);
            data.put("summary", summarize(mine, company, shared, outByMe, inToMe));
            return Map.of("ok", true, "data", data);
        } catch (Exception e) {
            log.warn("my_model_accounts failed: {}", e.getMessage());
            return Map.of("ok", false, "error", "查询模型账号失败：" + e.getMessage());
        }
    }

    /** CredentialView（record）→ 只保留模型该看到的字段，避免把调优参数整包塞进上下文。 */
    private static List<Map<String, Object>> brief(Object raw) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (!(raw instanceof List<?> list)) {
            return out;
        }
        for (Object o : list) {
            if (!(o instanceof ModelCredentialService.CredentialView v)) {
                continue;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", v.id());
            row.put("name", v.name());
            row.put("provider", v.providerKey());
            row.put("model", v.modelName());
            row.put("keyHint", v.keyHint());
            row.put("enabled", v.enabled());
            row.put("shareEnabled", v.shareEnabled());
            row.put("sharedToCount", v.shareCount());
            out.add(row);
        }
        return out;
    }

    private static String summarize(List<Map<String, Object>> mine, List<Map<String, Object>> company,
                                    List<Map<String, Object>> shared,
                                    List<Map<String, Object>> byMe, List<Map<String, Object>> toMe) {
        StringBuilder sb = new StringBuilder();
        sb.append("你自己注册了 ").append(mine.size()).append(" 个模型账号");
        if (!company.isEmpty()) {
            sb.append("，公司提供 ").append(company.size()).append(" 个");
        }
        sb.append("。");
        if (!shared.isEmpty()) {
            sb.append("有 ").append(shared.size()).append(" 个账号被同事共享给你可用（").append(joinNames(shared, "name")).append("）。");
        }
        if (!byMe.isEmpty()) {
            sb.append("你共享出去 ").append(byMe.size()).append(" 条：").append(joinShares(byMe, "colleague")).append("。");
        }
        if (!toMe.isEmpty()) {
            sb.append("你被邀请 ").append(toMe.size()).append(" 条：").append(joinShares(toMe, "owner")).append("。");
        }
        return sb.toString();
    }

    private static String joinNames(List<Map<String, Object>> rows, String key) {
        List<String> xs = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            xs.add(String.valueOf(r.get(key)));
        }
        return String.join("、", xs);
    }

    private static String joinShares(List<Map<String, Object>> rows, String whoKey) {
        List<String> xs = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            xs.add(r.get("credential") + " → " + r.get(whoKey) + "（" + r.get("status") + "，已用 "
                    + r.get("usedTokens") + " / 上限 " + r.get("quotaTokens") + "）");
        }
        return String.join("；", xs);
    }

    private static String statusLabel(String status) {
        if (status == null) {
            return "未知";
        }
        return switch (status) {
            case "ACTIVE" -> "生效中";
            case "PENDING" -> "待对方接受";
            case "REVOKED" -> "已撤销";
            case "EXPIRED" -> "已过期";
            default -> status;
        };
    }
}
