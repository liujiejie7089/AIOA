package cn.aioa.chat.tool;

import cn.aioa.org.service.PermissionGrantService;
import cn.aioa.resource.support.ExternalToolHandler;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 「申请权限」工具（V36 需求①：<b>用户通过 AI 提交申请</b>）。
 *
 * <p>注册到业务工具网关后，用户对 AI 说「我没有权限创建审批类数字员工，帮我申请一下」，
 * 模型即可调用本工具建单 —— 无需用户自己找菜单。</p>
 *
 * <p><b>与 HTTP 入口的关系</b>：本工具最终调用 {@link PermissionGrantService#apply}，
 * 与 {@code POST /api/v1/org/permissions/apply} 完全同一条校验链（幂等、已持有拒绝、
 * 未知权限码拒绝）。AI 只是另一个入口，不构成旁路。</p>
 *
 * <p><b>为什么同时提供 {@code list_my_permission_grants}</b>：模型需要能回答
 * 「我申请的那条到哪一步了」。只给提交不给查询，会让用户被迫回到页面确认，
 * 「通过 AI 完成闭环」就断了半截。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PermissionGrantToolHandler implements ExternalToolHandler {

    public static final String TOOL_APPLY = "apply_permission";
    public static final String TOOL_LIST = "list_my_permission_grants";

    private final PermissionGrantService grantService;

    @Override
    public String name() {
        // 一个 handler 只对应一个工具名；查询工具由 listTool 单独实现，见 {@link #describeExtra()}
        return TOOL_APPLY;
    }

    @Override
    public String description() {
        return "为当前用户申请一个自己尚未持有的权限码（如 approval:leave，用于创建请假审批类数字员工）。"
                + "流程：本地存档 → 部门负责人审批 → 租户管理员发放，通过后立即生效。"
                + "可申请权限：" + String.join("、", PermissionCatalog.applicablePermissions());
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"permissionCode\":{\"type\":\"string\",\"description\":\"要申请的权限码，例如 approval:leave；"
                + "可申请项：" + String.join(" / ", PermissionCatalog.applicablePermissions()) + "\"},"
                + "\"targetWorkerType\":{\"type\":\"string\",\"description\":\"用途：要创建的数字员工类型，"
                + "如 LEAVE_APPROVER（可空）\"},"
                + "\"reason\":{\"type\":\"string\",\"description\":\"申请理由，会展示给审批人\"}"
                + "},\"required\":[\"permissionCode\"]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            String code = args == null ? null : str(args.get("permissionCode"));
            PermissionGrantService.ApplyReq req = new PermissionGrantService.ApplyReq(
                    code,
                    args == null ? null : str(args.get("targetWorkerType")),
                    args == null ? null : str(args.get("reason")),
                    null,
                    // 二期：AI 工具不支持部门申请，保持个人申请链路（缺省 = 一期行为）
                    null, null);
            Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
            Map<String, Object> r = grantService.apply(tenantId, user, req);
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("grantId", r.get("grantId"));
            data.put("orderId", r.get("orderId"));
            data.put("status", r.get("status"));
            data.put("permissionCode", r.get("permissionCode"));
            data.put("permissionName", r.get("permissionName"));
            data.put("currentApproverName", r.get("currentApproverName"));
            data.put("institutionId", r.get("institutionId"));
            data.put("timeline", r.get("timeline"));
            data.put("message", "申请已提交，当前流转到「"
                    + (r.get("currentApproverName") == null ? "审批人" : r.get("currentApproverName"))
                    + "」，通过后权限自动生效");
            return Map.of("ok", true, "data", data);
        } catch (Exception e) {
            return Map.of("ok", false, "error", String.valueOf(e.getMessage()));
        }
    }

    private static String str(Object v) {
        if (v == null) {
            return null;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() || "null".equals(s) ? null : s;
    }
}
