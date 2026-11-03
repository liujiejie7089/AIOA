package cn.aios.chat.tool;

import cn.aios.org.mapper.OrgStatMapper;
import cn.aios.org.service.ApprovalFlowService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 「审批结果 / 进度」工具（2026-11-03）。
 *
 * <p>补的是<b>闭环的另一半</b>：只给「提交」不给「查结果」，用户被指定人批完之后
 * 仍然得回页面自己找，AI 就成了半个入口。有了本工具，用户问「我那单批了吗」
 * 或「交给张三代批的假批完了吗」，模型可以直接答。</p>
 *
 * <p><b>越权口径</b>：只允许「申请人本人」与「该单的实际审批人（含知会）」查看。
 * 不能因为知道一个 orderId 就能看别人的单 —— 审批单带事由、天数等个人信息。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApprovalResultToolHandler implements ExternalToolHandler {

    public static final String TOOL = "get_approval_result";

    private final OrgStatMapper statMapper;
    private final ApprovalFlowService flowService;

    @Override
    public String name() {
        return TOOL;
    }

    @Override
    public String description() {
        return "查询某个审批单的当前状态与流转进度（谁批了、谁在等、结论如何）。"
                + "orderId 来自 submit_leave_request 的返回值。用于回答「我那单批了吗 / 到谁了」。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"orderId\":{\"type\":\"integer\",\"description\":\"审批单 id（submit_leave_request 返回的 orderId）\"}"
                + "},\"required\":[\"orderId\"]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        Long orderId = lng(args == null ? null : args.get("orderId"));
        if (orderId == null || orderId <= 0L) {
            return Map.of("ok", false, "error", "orderId 必填");
        }
        Map<String, Object> order = statMapper.selectApprovalOrder(orderId);
        if (order == null) {
            return Map.of("ok", false, "error", "审批单不存在：" + orderId);
        }
        Long applicantId = lng(order.get("applicantId"));
        Long tenantId = lng(order.get("tenantId"));
        if (tenantId != null && user.getTenantId() != null && !Objects.equals(tenantId, user.getTenantId())) {
            return Map.of("ok", false, "error", "无权查看该审批单（跨租户）");
        }

        List<Map<String, Object>> timeline;
        try {
            timeline = flowService.timeline(orderId);
        } catch (Exception e) {
            timeline = List.of();
        }
        boolean isApplicant = applicantId != null && applicantId.equals(user.getUserId());
        boolean isApprover = timeline.stream().anyMatch(t -> user.getUserId() != null
                && user.getUserId().equals(lng(t.get("approverId"))));
        if (!isApplicant && !isApprover) {
            return Map.of("ok", false, "error", "无权查看该审批单：只有申请人本人与审批人可以查询");
        }

        // 当前节点 = **seq 最小**的那组 PENDING。不能把全部 PENDING 都算成"当前"：
        // 多级流的后续节点即使已经建出任务（状态 PENDING），在轮到它之前也处理不了
        // （引擎的 isCurrentNode 会拒绝）。若一并列出，AI 会跟用户说"在等王振华和刘敏"，
        // 而实际上刘敏那一步要等王振华批完才生效 —— 属于会误导用户催错人的错误。
        int minSeq = Integer.MAX_VALUE;
        for (Map<String, Object> t : timeline) {
            if ("PENDING".equals(String.valueOf(t.get("status")))) {
                Integer s = t.get("seq") instanceof Number n ? n.intValue() : null;
                if (s != null && s < minSeq) {
                    minSeq = s;
                }
            }
        }
        List<Map<String, Object>> pending = new ArrayList<>();
        for (Map<String, Object> t : timeline) {
            if (!"PENDING".equals(String.valueOf(t.get("status")))) {
                continue;
            }
            Integer s = t.get("seq") instanceof Number n ? n.intValue() : null;
            if (s != null && s == minSeq) {
                pending.add(t);
            }
        }
        List<String> pendingNames = pending.stream()
                .map(t -> String.valueOf(t.get("approverName")))
                .distinct().toList();
        // 后续还有几级：让用户知道"这单不是批一次就完"
        final int curSeq = minSeq;
        long laterLevels = timeline.stream()
                .filter(t -> "PENDING".equals(String.valueOf(t.get("status"))))
                .map(t -> t.get("seq") instanceof Number n ? n.intValue() : -1)
                .filter(s -> s > curSeq)
                .distinct().count();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("orderId", orderId);
        out.put("title", order.get("title"));
        out.put("bizType", order.get("bizType"));
        out.put("status", order.get("status"));
        out.put("statusText", statusText(String.valueOf(order.get("status"))));
        out.put("decidedAt", order.get("decidedAt") == null ? null : String.valueOf(order.get("decidedAt")));
        out.put("decisionNote", order.get("decisionNote"));
        out.put("currentApprovers", pendingNames);
        out.put("currentStep", pendingNames.isEmpty() ? "已结束"
                : "等待 " + String.join("、", pendingNames) + " 处理");
        // 只报「还有几级」，不把后续审批人名字提前暴露：那一级还没轮到，
        // 报了反而让用户去催一个此刻无权处理的人。
        out.put("laterLevels", laterLevels);
        // 精简时间线：模型不需要 taskId/nodeMode 这些实现细节，只要「谁、什么状态、什么时候」
        List<Map<String, Object>> brief = new ArrayList<>();
        for (Map<String, Object> t : timeline) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("seq", t.get("seq"));
            row.put("approver", t.get("approverName"));
            row.put("status", t.get("status"));
            row.put("note", t.get("note"));
            row.put("decidedAt", t.get("decidedAt"));
            brief.add(row);
        }
        out.put("timeline", brief);
        return Map.of("ok", true, "data", out);
    }

    private static String statusText(String s) {
        return switch (s == null ? "" : s) {
            case "PENDING" -> "审批中";
            case "APPROVED" -> "已通过";
            case "REJECTED" -> "已驳回";
            case "CANCELED", "CANCELLED" -> "已撤销";
            default -> s;
        };
    }

    private static Long lng(Object o) {
        if (o instanceof Number n) {
            return n.longValue();
        }
        try {
            return o == null ? null : Long.parseLong(String.valueOf(o).trim());
        } catch (RuntimeException e) {
            return null;
        }
    }
}
