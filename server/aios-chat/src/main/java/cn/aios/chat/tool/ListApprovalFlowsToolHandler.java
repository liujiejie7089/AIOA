package cn.aios.chat.tool;

import cn.aios.org.entity.ApprovalFlowDef;
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
 * 「查审批流配置」工具（2026-11-05）。
 *
 * <p>用户在管理端对 AI 说「看一下请假流程现在几级」「哪个机构的审批流还是默认的」，
 * 以前只能回答「请到审批流配置页面查看」。现在它能真查：返回每条流程的名称、业务类型、
 * 所属机构、级数与中文节点串（第1级 部门负责人 → 第2级 企业管理员）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ListApprovalFlowsToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "list_approval_flows";

    private final ApprovalFlowToolSupport support;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "查询本租户的全部审批流配置（请假 / 额度扩容 / 机构删除等），返回每条流程的 defId、名称、"
                + "业务类型、所属机构、状态、审批级数与中文节点串。"
                + "用户问「现在审批流是怎么配的」「有几个流程」「哪个流程还是默认配置」时调用。"
                + "要修改流程前，先用本工具拿到 defId，再用 get_approval_flow 看完整节点。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"bizType\":{\"type\":\"string\",\"description\":\"可选。按业务类型过滤，如 LEAVE / QUOTA_EXPAND\"},"
                + "\"institutionId\":{\"type\":\"integer\",\"description\":\"可选。只看某个机构的流程；不传=全部\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            String perm = support.permissionProblem(user);
            if (perm != null) {
                return Map.of("ok", false, "error", perm);
            }
            Long instId = null;
            Object rawInst = args == null ? null : args.get("institutionId");
            if (rawInst != null && !String.valueOf(rawInst).isBlank()) {
                try {
                    instId = Long.parseLong(String.valueOf(rawInst).trim());
                } catch (NumberFormatException ignore) {
                    instId = null;
                }
            }
            String bizType = args == null || args.get("bizType") == null
                    ? "" : String.valueOf(args.get("bizType")).trim().toUpperCase();

            List<ApprovalFlowDef> defs = support.defs(user, instId);
            List<Map<String, Object>> rows = new ArrayList<>();
            for (ApprovalFlowDef d : defs) {
                if (!bizType.isEmpty() && !bizType.equalsIgnoreCase(d.getBizType())) {
                    continue;
                }
                rows.add(support.brief(d));
            }
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("count", rows.size());
            data.put("flows", rows);
            data.put("institutions", support.institutions(user));
            data.put("note", rows.isEmpty()
                    ? "本租户还没有单独配置审批流（运行期按「企业管理员」单节点兜底）"
                    : "节点串里的「第N级」就是实际审批顺序；要改哪条请把 defId 告诉我");
            return Map.of("ok", true, "data", data);
        } catch (Exception e) {
            log.warn("list_approval_flows failed: {}", e.getMessage());
            return Map.of("ok", false, "error", "查询审批流失败：" + e.getMessage());
        }
    }
}
