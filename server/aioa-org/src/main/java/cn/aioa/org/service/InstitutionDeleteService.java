package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 机构删除（需求：级联前置校验 + 上一级审核）。
 *
 * <p><b>为什么要走审批，而不是像部门删除那样直接删</b>：用户需求原文 ——「任何一层级的首次删除操作
 * 都需要经过上一级审核后方可执行」。机构属四层（员工 → 部门 → 机构 → 租户）的第三层，
 * 其「上一级」= 租户管理员。故这里不提供「直接删除」端点：<b>申请</b>先落一条审批单，
 * <b>批准后</b>才真正删除。</p>
 *
 * <p><b>前置校验为什么要在<b>两处</b>各做一次</b>：申请时校验是为了「不让用户白填一张注定被拒的单」；
 * 审批通过时<b>必须再校验一次</b>——申请与批准之间可能隔了很久，期间完全可能有人往这个机构里
 * 加了部门或员工。只信申请时那一刻的结论，就会出现「批准的是空机构、删的是有人的机构」，
 * 连带把员工与部门的归属抹掉（{@code pitfalls} #2：不可逆动作绝不静默成功）。
 * 因此审批通过时若校验不过，<b>抛错让审批决策回滚</b>，而不是静默跳过删除。</p>
 *
 * <p><b>申请入口的层级限制</b>：申请人必须是<b>租户内</b>账号（{@code tenantId != 0}）。
 * 因为流程节点是「申请人的上一级」（{@link ApprovalFlowService} 的 {@code APPLICANT_SUPERIOR}），
 * 而平台管理员已在四层最顶端、没有上一级 —— 若放行，梯级会从部门负责人起算，
 * 把审批人<b>静默指错</b>（详见 {@code superiorLadder}）。平台管理员在本需求里的角色是
 * <b>审批人</b>（审租户删除），不是机构删除的发起人。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InstitutionDeleteService implements ApprovalCallback {

    public static final String BIZ_TYPE = "INSTITUTION_DELETE";
    /** 审计动作码。 */
    private static final String AUDIT_TYPE = "ORG_INSTITUTION";

    private final OrgInstitutionMapper institutionMapper;
    private final OrgDepartmentMapper deptMapper;
    private final OrgMemberMapper memberMapper;
    private final OrgGuard guard;
    private final AuditRecorder audit;
    private final JdbcTemplate jdbc;
    /** 惰性取用，避免与 {@link ApprovalFlowService} 形成构造器循环依赖（同 PermissionGrantService）。 */
    private final ObjectProvider<ApprovalFlowService> flowService;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    /**
     * 级联前置校验：能删返回 {@code null}；不能删返回<b>精确到停在那一级</b>的原因。
     *
     * <p>文案必须说清「还差什么」，否则用户只知道失败、不知道下一步该做什么。</p>
     */
    public String blockedReason(Long institutionId) {
        long depts = deptMapper.selectCount(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId));
        if (depts > 0) {
            return "该机构下仍有 " + depts + " 个部门，请先删除全部部门";
        }
        long members = memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId));
        if (members > 0) {
            return "该机构下仍有 " + members + " 名员工，请先移除全部员工（员工需先在「组织与员工」中删除）";
        }
        return null;
    }

    /** 提交删除申请：前置校验 → 落审批单 → 等上一级（租户管理员）批准。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> apply(Long requestedInstitutionId, String reason, AuthUser actor) {
        if (actor.getTenantId() == null || actor.getTenantId() == 0L) {
            throw BizException.forbidden("平台管理员不能发起「删除机构」：本流程的审批人是"
                    + "「申请人的上一级（租户管理员）」，而平台管理员已在组织层级最顶端、没有上一级。"
                    + "请由该租户内的账号发起");
        }
        // 作用域判定的唯一入口：机构成员硬绑定本机构、租户管理员限本租户、越界一律 404
        Long institutionId = guard.resolveScopeInstitution(requestedInstitutionId);
        OrgInstitution inst = institutionMapper.selectById(institutionId);
        if (inst == null) {
            throw BizException.notFound("机构不存在：" + institutionId);
        }
        String blocked = blockedReason(institutionId);
        if (blocked != null) {
            throw BizException.badRequest(blocked);
        }
        // 同一机构只允许一条在途申请（否则两张单先后批准，第二张会对已删对象操作）
        Long pending = jdbc.queryForObject(
                "SELECT COUNT(*) FROM approval_order WHERE biz_type = ? AND status = 'PENDING' "
                        + "AND deleted_at IS NULL AND form_data = ?",
                Long.class, BIZ_TYPE, formData(institutionId));
        if (pending != null && pending > 0) {
            throw BizException.badRequest("该机构已有一条待审批的删除申请，请等待审批结果");
        }

        ApprovalFlowService flow = flowService.getObject();
        if (flow == null) {
            throw BizException.badRequest("审批引擎未就绪，暂时无法提交申请");
        }
        Map<String, Object> submitted = flow.submit(inst.getTenantId(), actor,
                new ApprovalFlowService.SubmitReq(
                        BIZ_TYPE,
                        "机构删除：" + inst.getName(),
                        "申请删除机构「" + inst.getName() + "」（编码 " + inst.getCode() + "）"
                                + (reason == null || reason.isBlank() ? "" : "；理由：" + reason),
                        formData(institutionId),
                        institutionId,
                        null,
                        null,
                        actor.getUserId(),
                        AuditRecorder.displayName(actor),
                        null,
                        "USER",
                        null));

        audit.record(inst.getTenantId(), institutionId, actor, "INSTITUTION_DELETE_APPLY", AUDIT_TYPE,
                institutionId,
                "申请删除机构「" + inst.getName() + "」"
                        + (reason == null || reason.isBlank() ? "" : "（理由：" + reason + "）"),
                null, Map.of("institutionId", institutionId, "orderId", String.valueOf(submitted.get("orderId"))));

        Map<String, Object> out = new LinkedHashMap<>(submitted);
        out.put("institutionId", institutionId);
        out.put("institutionName", inst.getName());
        out.put("pendingApproval", true);
        out.put("hint", "已提交，需经上一级（租户管理员）审核；批准后才会真正删除");
        return out;
    }

    /** 审批通过：<b>重新</b>校验前置条件后删除。校验不过 ⇒ 抛错让审批决策回滚。 */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        Long institutionId = idOf(order, "institutionId");
        if (institutionId == null) {
            throw BizException.badRequest("机构删除审批通过，但审批单里没有机构标识（form_data 缺 institutionId），"
                    + "拒绝静默跳过：orderId=" + order.get("id"));
        }
        OrgInstitution inst = institutionMapper.selectById(institutionId);
        if (inst == null) {
            throw BizException.badRequest("待删除的机构已不存在（可能已被删除）：" + institutionId);
        }
        String blocked = blockedReason(institutionId);
        if (blocked != null) {
            throw BizException.badRequest("审批期间该机构已不再满足删除条件，本次不执行删除：" + blocked);
        }
        institutionMapper.deleteById(institutionId);
        audit.record(inst.getTenantId(), institutionId, null, "INSTITUTION_DELETE_APPROVE", AUDIT_TYPE,
                institutionId,
                "机构删除审核通过并执行删除：「" + inst.getName() + "」",
                inst, Map.of("orderId", String.valueOf(order.get("id"))));
        log.info("institution deleted by approval: id={} name={} orderId={}",
                institutionId, inst.getName(), order.get("id"));
    }

    /**
     * 审批驳回：对象<b>保持原状</b>（不软删、不置灰），用户可再次申请。
     *
     * <p>这里<b>故意不写库</b>：申请时也没有改动机构本身（只落了审批单），所以驳回后
     * 无需「回滚」任何字段。若在此处把机构置灰，就会造出「被驳回 = 机构不可用」的错觉，
     * 与需求「未获批准前对象保持原状」相悖。</p>
     */
    @Override
    public void onRejected(Map<String, Object> order) {
        log.info("institution delete rejected, institution kept as-is: institutionId={} orderId={}",
                idOf(order, "institutionId"), order.get("id"));
    }

    // ------------------------------------------------------------------ helpers

    private static String formData(Long institutionId) {
        return "{\"institutionId\":" + institutionId + "}";
    }

    /** 从审批单反查业务对象 id（{@code form_data} 的 JSON 串）。 */
    private static Long idOf(Map<String, Object> order, String key) {
        Object fd = order.get("formData");
        if (fd == null) {
            fd = order.get("form_data");
        }
        if (fd == null) {
            return null;
        }
        try {
            com.fasterxml.jackson.databind.JsonNode n =
                    new com.fasterxml.jackson.databind.ObjectMapper().readTree(String.valueOf(fd));
            com.fasterxml.jackson.databind.JsonNode v = n.get(key);
            return v == null || v.isNull() ? null : v.asLong();
        } catch (Exception e) {
            log.warn("解析审批单 form_data 失败：{}", fd, e);
            return null;
        }
    }
}
