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
 * 「修改审批流配置」工具（2026-11-05）。
 *
 * <p>需求原话：「用户可以直接给 AI 对话，修改审批流配置，但需要参数够了才配置，不够就继续询问。」</p>
 *
 * <p><b>参数够不够，由服务端判定，不靠模型自觉</b>。缺什么就回一份 {@code missing} 清单
 * 加一句可以直接转述给用户的 {@code question}，模型照着继续问；等参数真的齐了才落库。
 * 这样做的好处是可验证：任何一次写操作都能在库里找到「改前 / 改后 / 版本号」，
 * 而不是「模型觉得够了」。</p>
 *
 * <p><b>为什么还要一道 {@code confirm}</b>：流程配置影响之后每一张单据，属于「有外部影响」
 * 的写操作。模型先 {@code request_confirm} 让用户点确认，再把 {@code confirm=true} 带回来；
 * 少了这一步，工具自己会把「将要改成什么」摆出来并要求确认 —— 不依赖模型记不记得住。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class UpdateApprovalFlowToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "update_approval_flow";

    private final ApprovalFlowToolSupport support;
    private final cn.aios.org.service.ApprovalFlowService flowService;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "修改一条审批流的审批节点（整体替换 steps）。"
                + "调用前必须先 get_approval_flow 拿到原节点，再在它基础上修改；"
                + "参数不齐时本工具**不会修改**，而是返回 missing 清单与要问用户的问题，请照着继续询问。"
                + "写之前需要用户明确同意：先 request_confirm 让用户点「确认」，"
                + "用户同意后再带 confirm=true 调用本工具。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"defId\":{\"type\":\"integer\",\"description\":\"要改的审批流 id\"},"
                + "\"steps\":{\"type\":\"array\",\"description\":\"完整的节点数组（不是增量）。"
                + "每项形如 {\\\"seq\\\":1,\\\"approver_type\\\":\\\"DEPT_LEADER\\\",\\\"mode\\\":\\\"single\\\","
                + "\\\"threshold_days\\\":3,\\\"cc\\\":[\\\"ORG_ADMIN\\\"]}；"
                + "approver_type 可选 DEPT_LEADER/ORG_ADMIN/TENANT_ADMIN/PLATFORM_ADMIN/SPECIFIC/"
                + "APPLICANT_SUPERIOR/DEPT_DUTY/UNIT_DUTY，SPECIFIC 必须带 approver_id\","
                + "\"items\":{\"type\":\"object\"}},"
                + "\"reason\":{\"type\":\"string\",\"description\":\"变更原因，写进审计\"},"
                + "\"confirm\":{\"type\":\"boolean\",\"description\":\"用户已确认后才传 true\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            String perm = support.permissionProblem(user);
            if (perm != null) {
                return Map.of("ok", false, "error", perm);
            }
            args = args == null ? Map.of() : args;

            // ---------- ① 定位改哪一条 ----------
            Long defId = parseLong(args.get("defId"));
            ApprovalFlowDef def = support.defById(user, defId);
            if (defId == null || def == null) {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("missing", List.of("defId"));
                data.put("question", "要修改哪一条审批流？请从候选里选一个（也可以直接说流程名称）。");
                List<Map<String, Object>> cands = new ArrayList<>();
                for (ApprovalFlowDef d : support.defs(user, null)) {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("defId", d.getId());
                    m.put("name", d.getName());
                    m.put("bizType", d.getBizType());
                    m.put("institution", support.institutionName(d.getInstitutionId()));
                    m.put("stepsText", support.brief(d).get("stepsText"));
                    cands.add(m);
                }
                data.put("candidates", cands);
                return Map.of("ok", false, "error", "缺少 defId", "data", data);
            }

            // ---------- ② 节点参数够不够 ----------
            Object steps = args.get("steps");
            List<String> problems = support.problems(steps);
            if (!problems.isEmpty()) {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("missing", problems.size() == 1 && problems.get(0).startsWith("steps 必须")
                        ? List.of("steps") : List.of("steps[校验未通过]"));
                data.put("invalid", problems);
                data.put("question", "这条流程现在是这样：" + support.describeSteps(
                        support.parseSteps(def.getStepsJson())) + "。"
                        + "你想把哪一级改成谁来审？把「第几级 + 审批人类型」告诉我就行"
                        + "（可选：" + String.join(" / ", ApprovalFlowToolSupport.APPROVER_LABELS.keySet()) + "）。");
                data.put("current", support.detail(def));
                data.put("allowedApproverTypes", ApprovalFlowToolSupport.APPROVER_LABELS);
                data.put("allowedModes", ApprovalFlowToolSupport.MODE_LABELS);
                return Map.of("ok", false, "error", "参数不够，未做修改", "data", data);
            }

            // ---------- ③ 用户确认 ----------
            String before = support.describeSteps(support.parseSteps(def.getStepsJson()));
            @SuppressWarnings("unchecked")
            String after = support.describeSteps((List<Map<String, Object>>) steps);
            if (!Boolean.TRUE.equals(args.get("confirm"))) {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("needConfirm", true);
                data.put("question", "即将把「" + def.getName() + "」从【" + before + "】改成【" + after
                        + "】。请先让用户确认（request_confirm），用户点「确认」后再带 confirm=true 调用本工具。");
                data.put("beforeText", before);
                data.put("afterText", after);
                data.put("defId", def.getId());
                return Map.of("ok", false, "error", "等待用户确认，未做修改", "data", data);
            }

            // ---------- ④ 落库（服务层自带 validateSteps + 版本快照 + 审计） ----------
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("id", def.getId());
            body.put("bizType", def.getBizType());
            body.put("steps", steps);
            if (args.get("reason") != null && !String.valueOf(args.get("reason")).isBlank()) {
                body.put("remark", String.valueOf(args.get("reason")).trim());
            }
            ApprovalFlowDef saved = flowService.saveDef(support.tenantOf(user), user, body);

            Map<String, Object> data = new LinkedHashMap<>(support.detail(saved));
            data.put("beforeText", before);
            data.put("afterText", support.describeSteps(support.parseSteps(saved.getStepsJson())));
            data.put("message", "已更新「" + saved.getName() + "」：" + before + " → "
                    + data.get("afterText") + "（已留版本快照，可回溯）");
            return Map.of("ok", true, "data", data);
        } catch (cn.aios.common.exception.BizException e) {
            // 业务校验失败：把服务端那句人话原样交给模型，不要包一层「系统错误」
            return Map.of("ok", false, "error", e.getMessage());
        } catch (Exception e) {
            log.warn("update_approval_flow failed: {}", e.getMessage(), e);
            return Map.of("ok", false, "error", "修改审批流失败：" + e.getMessage());
        }
    }

    private static Long parseLong(Object raw) {
        if (raw == null || String.valueOf(raw).isBlank()) {
            return null;
        }
        try {
            return Long.parseLong(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
