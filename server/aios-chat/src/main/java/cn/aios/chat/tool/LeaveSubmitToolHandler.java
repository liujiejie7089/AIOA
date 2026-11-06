package cn.aios.chat.tool;

import cn.aios.org.service.LeaveService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 「发起请假」工具（2026-11-03：OA 审批流程发起）。
 *
 * <p><b>与页面入口同链</b>：最终调用 {@link LeaveService#submit}，与
 * {@code POST /api/v1/workflow/leave/requests} 完全同一条校验链（余额、假种有效期、
 * 提前天数、证明材料、在途占用）。AI 只是另一个入口，不构成旁路 ——
 * 这也是为什么这里不做任何「AI 版宽松校验」。</p>
 *
 * <p><b>指定处理人</b>：{@code assigneeUserId} 非空时，审批引擎会把它插为第 1 级节点：</p>
 * <ul>
 *   <li>后台没配审批流 ⇒ 他就是唯一节点，处理完直接终态；</li>
 *   <li>后台配了审批流 ⇒ 他批完自动按流定义流转下一节点。</li>
 * </ul>
 * <p>取值必须来自 {@code list_approval_handlers}（审批域口径：本机构在职成员），
 * 不能拿通讯录里的外部联系人 id 顶替。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LeaveSubmitToolHandler implements ExternalToolHandler {

    public static final String TOOL = "submit_leave_request";

    private final LeaveService leaveService;

    @Override
    public String name() {
        return TOOL;
    }

    @Override
    public String description() {
        return "为当前用户发起请假申请（会自动展开审批流）。调用前必须已经收齐："
                + "假种码、开始日期、结束日期、事由；若用户说「交给某某处理」或点名了多个负责人，"
                + "还要先调 list_approval_handlers 拿到 userId（多个用 assigneeUserIds 数组，顺序即审批顺序）。"
                + "**不要在信息不全时调用本工具** —— 缺项应通过 ask_user 的 fields 一次性问全。"
                + "成功返回 orderId / leaveRequestId / currentApproverName（当前流转到谁）/ status，"
                + "以及 handlers（处理人信息）与 dataFlow（数据流：每级节点、状态、当前级）。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"leaveTypeCode\":{\"type\":\"string\",\"description\":\"假种码，来自 GET /api/v1/workflow/leave/types，如 annual/personal/sick\"},"
                + "\"startDate\":{\"type\":\"string\",\"description\":\"开始日期 YYYY-MM-DD\"},"
                + "\"endDate\":{\"type\":\"string\",\"description\":\"结束日期 YYYY-MM-DD\"},"
                + "\"reason\":{\"type\":\"string\",\"description\":\"请假事由，会展示给审批人\"},"
                + "\"assigneeUserId\":{\"type\":\"integer\",\"description\":\"指定处理人的 userId（来自 list_approval_handlers）；"
                + "为空则按后台审批流默认规则找人\"},"
                // 八期：多选负责人（按数组顺序依次审批）。与 assigneeUserId 互斥，优先用本字段。
                + "\"assigneeUserIds\":{\"type\":\"array\",\"items\":{\"type\":\"integer\"},"
                + "\"description\":\"指定多个负责人时用本字段（userId 数组，顺序即审批顺序）；"
                + "单个时用 assigneeUserId 亦可。为空则按后台审批流默认规则找人\"},"
                + "\"proofFileId\":{\"type\":\"integer\",\"description\":\"证明材料文件 id（假种要求证明时必填）\"},"
                + "\"userId\":{\"type\":\"integer\",\"description\":\"代他人提交时的目标员工 userId，一般不要填\"}"
                + "},\"required\":[\"leaveTypeCode\",\"startDate\",\"endDate\"]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        Map<String, Object> body = new LinkedHashMap<>();
        if (args != null) {
            body.putAll(args);
        }
        try {
            Map<String, Object> data = leaveService.submit(user, body);
            log.info("submit_leave_request: user={} assignee={} => order={} status={}",
                    user.getUserId(), body.get("assigneeUserId"),
                    data.get("orderId"), data.get("status"));
            // 直接给出「下一步找谁」：用户最关心的就是这句，不该让模型从 timeline 里自己推
            Map<String, Object> out = new LinkedHashMap<>(data);
            out.put("nextStep", data.get("currentApproverName") == null
                    ? "已提交，等待审批人处理"
                    : "当前流转至 " + data.get("currentApproverName"));
            return Map.of("ok", true, "data", out);
        } catch (Exception e) {
            // 业务失败（余额不足 / 假种停用 / 日期非法…）一律不抛：交给模型组织成人话回答。
            log.info("submit_leave_request rejected: {}", e.getMessage());
            return Map.of("ok", false, "error", String.valueOf(e.getMessage()));
        }
    }
}
