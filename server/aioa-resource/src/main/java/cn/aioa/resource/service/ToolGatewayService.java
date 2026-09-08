package cn.aioa.resource.service;

import cn.aioa.resource.entity.ApprovalOrder;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.entity.TenantQuota;
import cn.aioa.security.AuthUser;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 业务工具网关（智能体调用业务系统的唯一入口）。
 *
 * 设计（对应技术方案「工具调用按权限码白名单放行」）：
 *  - 工具清单以 OpenAI function-calling 格式输出，供 Agent 注入模型 system/tools；
 *  - 执行以「当前登录用户」身份进行（Agent 回调时透传用户 token），
 *    工具权限 = 用户权限，越权数据天然不可达；
 *  - 每个工具声明 permissionCode 与所需角色，执行前校验；
 *  - 将来接入外部业务系统，只需在 {@link #invoke} 增加适配器，Agent 侧零改动。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolGatewayService {

    private static final int MAX_ROWS = 10;
    private static final String ROLE_ADMIN = "ROLE_ADMIN";

    private final ApprovalService approvalService;
    private final KbService kbService;
    private final BillingService billingService;

    /** 单个工具定义：name / description / parameters(JSON Schema) / requiredRoles。 */
    public record ToolDef(String name, String description, String parametersJson, Set<String> requiredRoles) {
    }

    /** 工具注册表（白名单）：新增业务工具在此加一行 + invoke 一个分支。 */
    private static final List<ToolDef> REGISTRY = List.of(
            new ToolDef("list_my_approvals",
                    "查询当前用户提交的审批单列表（含状态与审批意见）",
                    "{\"type\":\"object\",\"properties\":{},\"required\":[]}",
                    Set.of()),
            new ToolDef("list_todo_approvals",
                    "查询本租户待审批的审批单（仅租户管理员可用）",
                    "{\"type\":\"object\",\"properties\":{},\"required\":[]}",
                    Set.of(ROLE_ADMIN)),
            new ToolDef("search_kb_documents",
                    "按关键词检索当前用户可用的知识库文档（个人 + 本租户共享）",
                    "{\"type\":\"object\",\"properties\":{\"keyword\":{\"type\":\"string\",\"description\":\"检索关键词\"}},\"required\":[\"keyword\"]}",
                    Set.of()),
            new ToolDef("get_my_quota",
                    "查询当前用户的词元额度（总量/已用/剩余/使用百分比）",
                    "{\"type\":\"object\",\"properties\":{},\"required\":[]}",
                    Set.of())
    );

    /** 工具清单（OpenAI function 格式，供模型 tools 参数直接使用）。 */
    public List<Map<String, Object>> listTools() {
        ObjectMapper mapper = new ObjectMapper();
        List<Map<String, Object>> out = new ArrayList<>();
        for (ToolDef def : REGISTRY) {
            Map<String, Object> parameters;
            try {
                parameters = mapper.readValue(def.parametersJson(),
                        new TypeReference<Map<String, Object>>() {
                        });
            } catch (Exception e) {
                parameters = Map.of("type", "object", "properties", Map.of());
            }
            Map<String, Object> fn = new LinkedHashMap<>();
            fn.put("name", def.name());
            fn.put("description", def.description());
            fn.put("parameters", parameters);
            Map<String, Object> tool = new LinkedHashMap<>();
            tool.put("type", "function");
            tool.put("function", fn);
            out.add(tool);
        }
        return out;
    }

    /** 执行工具：以当前登录用户身份；返回 {ok, data|error}，业务失败不抛异常（错误交给模型组织回答）。 */
    public Map<String, Object> invoke(String name, Map<String, Object> args, AuthUser user) {
        ToolDef def = REGISTRY.stream().filter(t -> t.name().equals(name)).findFirst().orElse(null);
        if (def == null) {
            return Map.of("ok", false, "error", "未知工具：" + name);
        }
        if (!def.requiredRoles().isEmpty()
                && (user.getRoles() == null || !user.getRoles().containsAll(def.requiredRoles()))) {
            return Map.of("ok", false, "error", "该工具需要租户管理员角色");
        }
        try {
            Object data = switch (name) {
                case "list_my_approvals" -> myApprovals(user);
                case "list_todo_approvals" -> todoApprovals(user);
                case "search_kb_documents" -> searchKb(user, args);
                case "get_my_quota" -> myQuota(user);
                default -> null;
            };
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("ok", true);
            out.put("data", data);
            return out;
        } catch (Exception e) {
            log.warn("tool {} invoke failed: {}", name, e.getMessage());
            return Map.of("ok", false, "error", String.valueOf(e.getMessage()));
        }
    }

    private List<Map<String, Object>> myApprovals(AuthUser user) {
        return approvalService.listMine(user.getTenantId() == null ? 0L : user.getTenantId(), user.getUserId())
                .stream().limit(MAX_ROWS).map(this::approvalRow).toList();
    }

    private List<Map<String, Object>> todoApprovals(AuthUser user) {
        return approvalService.listTodo(user.getTenantId() == null ? 0L : user.getTenantId())
                .stream().limit(MAX_ROWS).map(this::approvalRow).toList();
    }

    private Map<String, Object> approvalRow(ApprovalOrder o) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", o.getId());
        row.put("bizType", o.getBizType());
        row.put("title", o.getTitle());
        row.put("status", o.getStatus());
        row.put("decisionNote", o.getDecisionNote());
        row.put("decidedAt", o.getDecidedAt() == null ? null : o.getDecidedAt().toString());
        return row;
    }

    private List<Map<String, Object>> searchKb(AuthUser user, Map<String, Object> args) {
        String keyword = String.valueOf(args == null ? null : args.get("keyword"));
        if (keyword == null || keyword.isBlank() || "null".equals(keyword)) {
            throw new IllegalArgumentException("keyword 不能为空");
        }
        List<Long> scopeUsers = BillingService.scopeUsers(user.getUserId());
        List<KbDocument> docs = kbService.search(user.getTenantId() == null ? 0L : user.getTenantId(),
                scopeUsers, keyword, MAX_ROWS);
        return docs.stream().map(d -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", d.getId());
            row.put("docName", d.getDocName());
            row.put("state", d.getState());
            row.put("sizeBytes", d.getSizeBytes());
            row.put("createdAt", d.getCreatedAt() == null ? null : d.getCreatedAt().toString());
            return row;
        }).toList();
    }

    private Map<String, Object> myQuota(AuthUser user) {
        TenantQuota q = billingService.getOrCreate(user.getTenantId() == null ? 0L : user.getTenantId(), user.getUserId());
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("quota", q.getQuotaTokens());
        row.put("used", q.getUsedTokens());
        row.put("left", Math.max(0, q.getQuotaTokens() - q.getUsedTokens()));
        return row;
    }
}
