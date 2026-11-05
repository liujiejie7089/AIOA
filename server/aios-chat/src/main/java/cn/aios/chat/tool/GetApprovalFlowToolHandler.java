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
 * 「看一条审批流的完整配置」工具（2026-11-05）。
 *
 * <p>和 list 分开的理由：列清单只要摘要，改配置必须看到**原始节点对象**
 * （approver_type / mode / threshold_days / when / cc），否则模型会照着自己脑补的结构写回去，
 * 把用户没提到的那几级改坏。所以本工具直接回 steps 原文 + 最新版本号。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class GetApprovalFlowToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "get_approval_flow";

    private final ApprovalFlowToolSupport support;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "查看某一条审批流的完整配置：每一级审批人类型、会签/抢办模式、天数阈值、生效条件、抄送对象，"
                + "以及最新版本号。修改前必须先调用本工具，取得原节点数组后再在它基础上改。"
                + "不给 defId 时本工具会返回候选清单请你确认是哪一条。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"defId\":{\"type\":\"integer\",\"description\":\"审批流定义 id（从 list_approval_flows 拿）\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            String perm = support.permissionProblem(user);
            if (perm != null) {
                return Map.of("ok", false, "error", perm);
            }
            Long defId = null;
            Object raw = args == null ? null : args.get("defId");
            if (raw != null && !String.valueOf(raw).isBlank()) {
                try {
                    defId = Long.parseLong(String.valueOf(raw).trim());
                } catch (NumberFormatException ignore) {
                    defId = null;
                }
            }
            if (defId == null) {
                // 参数不足：不猜，把候选摊开让模型去问用户
                List<Map<String, Object>> rows = new ArrayList<>();
                for (ApprovalFlowDef d : support.defs(user, null)) {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("defId", d.getId());
                    m.put("name", d.getName());
                    m.put("bizType", d.getBizType());
                    m.put("institution", support.institutionName(d.getInstitutionId()));
                    rows.add(m);
                }
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("missing", List.of("defId"));
                data.put("question", "要查看哪一条审批流？请从下面的候选里选一个（或告诉我流程名称）。");
                data.put("candidates", rows);
                return Map.of("ok", false, "error", "缺少 defId", "data", data);
            }
            ApprovalFlowDef def = support.defById(user, defId);
            if (def == null) {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("missing", List.of("defId"));
                data.put("question", "没有找到 defId=" + defId + " 的审批流（可能属于别的机构或已删除）。要不要先列一下现有流程？");
                return Map.of("ok", false, "error", "审批流不存在", "data", data);
            }
            return Map.of("ok", true, "data", support.detail(def));
        } catch (Exception e) {
            log.warn("get_approval_flow failed: {}", e.getMessage());
            return Map.of("ok", false, "error", "读取审批流失败：" + e.getMessage());
        }
    }
}
