package cn.aios.chat.tool;

import cn.aios.org.entity.OrgMember;
import cn.aios.org.mapper.OrgMemberMapper;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 「可选处理人」工具（2026-11-03：OA 审批的「指定交给谁」）。
 *
 * <p>为什么不直接复用通讯录（企微 {@code contact_search}）：<b>能审批的人</b>与
 * <b>能聊天的人</b>是两个集合 —— 前者必须本机构在职，且审批引擎要按 {@code user_id}
 * 建任务。企微通讯录里可能混着外部联系人、离职未清理的人；拿那些 id 去建审批任务，
 * 会生成一条永远没人处理的待办（引擎只管建任务，不管这人还在不在职）。</p>
 *
 * <p>因此本工具是审批域自己的候选人源：口径 = 本机构 {@code org_member} 在职成员，
 * 排除申请人本人（自己批自己无意义），返回 {@code userId} 供
 * {@code submit_leave_request.assigneeUserId} 直接使用。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApprovalHandlerToolHandler implements ExternalToolHandler {

    public static final String TOOL = "list_approval_handlers";

    /** 候选上限：字段卡的可检索候选框只用于挑人，返回全量没有意义还拖慢渲染。 */
    private static final int MAX_HANDLERS = 60;

    private final OrgMemberMapper memberMapper;

    @Override
    public String name() {
        return TOOL;
    }

    @Override
    public String description() {
        return "查询「可以把审批交给谁」——本机构在职成员（含姓名 / 职务 / 部门）。"
                + "当用户要发起请假等审批、并说「交给某某处理」时，先用本工具查候选，"
                + "再让用户在候选里选；**不要凭空编造 userId**。返回值里的 userId 就是"
                + "submit_leave_request 的 assigneeUserId。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"keyword\":{\"type\":\"string\",\"description\":\"按姓名/职务模糊筛选，可空\"},"
                + "\"limit\":{\"type\":\"integer\",\"description\":\"最多返回多少个候选，默认 30，最大 60\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        Long institutionId = user.getInstitutionId();
        if (institutionId == null || institutionId <= 0L) {
            // 未绑定机构不是「没查到人」，而是环境不满足：说清原因，模型才不会反复重试
            return Map.of("ok", false,
                    "error", "当前账号未绑定机构（org_member），无法确定可审批人员范围，请先在组织管理中登记");
        }
        int limit = clamp(intOf(args == null ? null : args.get("limit"), 30), 1, MAX_HANDLERS);
        String kw = str(args == null ? null : args.get("keyword"));

        LambdaQueryWrapper<OrgMember> w = new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .ne(OrgMember::getUserId, user.getUserId())
                .orderByAsc(OrgMember::getDepartmentId)
                .orderByAsc(OrgMember::getId)
                .last("limit " + MAX_HANDLERS);
        if (kw != null && !kw.isBlank()) {
            w.and(q -> q.like(OrgMember::getName, kw).or().like(OrgMember::getJobTitle, kw)
                    .or().like(OrgMember::getDutyCode, kw));
        }

        List<OrgMember> rows = memberMapper.selectList(w);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (OrgMember m : rows) {
            if (m.getUserId() == null) {
                continue;   // 没有账号的成员建不了任务，不能进候选
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("userId", m.getUserId());
            row.put("name", m.getName() == null ? ("用户#" + m.getUserId()) : m.getName());
            row.put("jobTitle", m.getJobTitle());
            row.put("dutyCode", m.getDutyCode());
            row.put("departmentId", m.getDepartmentId());
            out.add(row);
            if (out.size() >= limit) {
                break;
            }
        }
        log.info("list_approval_handlers: inst={} keyword={} => {} 人", institutionId, kw, out.size());
        return Map.of("ok", true, "data", out);
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o).trim();
    }

    private static int intOf(Object o, int dft) {
        if (o instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(o).trim());
        } catch (RuntimeException e) {
            return dft;
        }
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
