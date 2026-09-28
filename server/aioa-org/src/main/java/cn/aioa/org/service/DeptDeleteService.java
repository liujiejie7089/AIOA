package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 部门删除（需求：级联前置校验 + 上一级审核）。
 *
 * <p>这是四层里唯一原本就<b>已有</b>级联前置校验的一层（{@code OrgTreeService.deleteDept} 早已拒绝
 * 「还有子部门 / 还有员工」的删除），但它缺的是<b>审核闸门</b> —— 原先是直接删。
 * 需求原文是「<b>任何</b>一层级的首次删除操作都需要经过上一级审核后方可执行」，
 * 若只给机构与租户加审核而把部门留着直删，就是明显的半成品：越往下越松，
 * 而部门恰恰是日常最常被删的一层。</p>
 *
 * <p><b>判定只在一处</b>：能否删除委托给 {@link OrgTreeService#deptBlockedReason}，
 * 本类不自带第二份判定 —— 否则迟早出现「申请时说能删、执行时说不能删」（铁律 #1）。</p>
 *
 * <p><b>审批人</b>：{@code APPLICANT_SUPERIOR} + {@code levels=1}，即「申请人的上一级」。
 * 部门删除的申请人可能是部门负责人 / 机构管理员 / 租户管理员，
 * 引擎的 {@code superiorLadder} 会按申请人自身所处梯级向上取一级
 * （部门负责人 → 机构管理员；机构管理员 → 租户管理员；租户管理员 → 平台管理员），
 * 不必为每种申请人在流程定义里各配一条。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DeptDeleteService implements ApprovalCallback {

    public static final String BIZ_TYPE = "DEPT_DELETE";

    private final OrgTreeService treeService;
    private final OrgDepartmentMapper deptMapper;
    private final OrgGuard guard;
    private final AuditRecorder audit;
    private final JdbcTemplate jdbc;
    /** 惰性取用，避免与 {@link ApprovalFlowService} 形成构造器循环依赖。 */
    private final ObjectProvider<ApprovalFlowService> flowService;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    /** 提交删除申请：前置校验 → 落审批单 → 等上一级批准。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> apply(Long requestedInstitutionId, Long departmentId, String reason,
                                     AuthUser actor) {
        // 作用域判定的唯一入口：机构成员硬绑定本机构、租户管理员限本租户、越界一律 404
        Long institutionId = guard.resolveScopeInstitution(requestedInstitutionId);
        OrgDepartment d = deptMapper.selectById(departmentId);
        if (d == null || !institutionId.equals(d.getInstitutionId())) {
            throw BizException.notFound("部门不存在或不属于本机构：" + departmentId);
        }
        String blocked = treeService.deptBlockedReason(institutionId, departmentId);
        if (blocked != null) {
            throw BizException.badRequest(blocked);
        }
        // 同一部门只允许一条在途申请（否则两张单先后批准，第二张会对已删对象操作）
        Long pending = jdbc.queryForObject(
                "SELECT COUNT(*) FROM approval_order WHERE biz_type = ? AND status = 'PENDING' "
                        + "AND deleted_at IS NULL AND form_data = ?",
                Long.class, BIZ_TYPE, formData(departmentId, institutionId));
        if (pending != null && pending > 0) {
            throw BizException.badRequest("该部门已有一条待审批的删除申请，请等待审批结果");
        }

        ApprovalFlowService flow = flowService.getObject();
        if (flow == null) {
            throw BizException.badRequest("审批引擎未就绪，暂时无法提交申请");
        }
        Map<String, Object> submitted = flow.submit(d.getTenantId(), actor,
                new ApprovalFlowService.SubmitReq(
                        BIZ_TYPE,
                        "部门删除：" + d.getName(),
                        "申请删除部门「" + d.getName() + "」"
                                + (reason == null || reason.isBlank() ? "" : "；理由：" + reason),
                        formData(departmentId, institutionId),
                        institutionId,
                        departmentId,
                        null,
                        actor.getUserId(),
                        AuditRecorder.displayName(actor),
                        null,
                        "USER",
                        null));

        audit.record(d.getTenantId(), institutionId, actor, "DEPT_DELETE_APPLY", "ORG_DEPARTMENT",
                departmentId,
                "申请删除部门「" + d.getName() + "」"
                        + (reason == null || reason.isBlank() ? "" : "（理由：" + reason + "）"),
                null, Map.of("departmentId", departmentId, "orderId", String.valueOf(submitted.get("orderId"))));

        Map<String, Object> out = new LinkedHashMap<>(submitted);
        out.put("departmentId", departmentId);
        out.put("departmentName", d.getName());
        out.put("institutionId", institutionId);
        out.put("pendingApproval", true);
        out.put("hint", "已提交，需经上一级审核；批准后才会真正删除");
        return out;
    }

    /**
     * 审批通过：<b>重新</b>校验前置条件后删除。
     *
     * <p>重校验不是多余动作：申请与批准之间可能隔了很久，期间完全可能有人往这个部门里
     * 加了子部门或员工。只信申请那一刻的结论，就会出现「批准的是空部门、删的是有人的部门」，
     * 把子部门与员工变成孤儿（{@code pitfalls} #2：不可逆动作绝不静默成功）。</p>
     *
     * <p>执行仍委托 {@link OrgTreeService#deleteDept}（那里才是删除的唯一实现点，
     * 含它自己的重校验与审计留痕）—— 本类只负责「过了审批闸门之后再放行」。</p>
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        Long departmentId = idOf(order, "departmentId");
        Long institutionId = idOf(order, "institutionId");
        if (departmentId == null || institutionId == null) {
            throw BizException.badRequest("部门删除审批通过，但审批单里缺少部门/机构标识"
                    + "（form_data 缺 departmentId 或 institutionId），拒绝静默跳过：orderId=" + order.get("id"));
        }
        OrgDepartment d = deptMapper.selectById(departmentId);
        if (d == null) {
            throw BizException.badRequest("待删除的部门已不存在（可能已被删除）：" + departmentId);
        }
        String blocked = treeService.deptBlockedReason(institutionId, departmentId);
        if (blocked != null) {
            throw BizException.badRequest("审批期间该部门已不再满足删除条件，本次不执行删除：" + blocked);
        }
        // actor 传 null：审批动作没有「当前登录的企业用户」，删改留痕由 deleteDept 内部记，
        // 操作者身份由审批单（applicant + 各节点审批人）承载。
        treeService.deleteDept(institutionId, departmentId, null);
        audit.record(d.getTenantId(), institutionId, null, "DEPT_DELETE_APPROVE", "ORG_DEPARTMENT",
                departmentId,
                "部门删除审核通过并执行删除：「" + d.getName() + "」",
                null, Map.of("orderId", String.valueOf(order.get("id"))));
        log.info("department deleted by approval: id={} name={} orderId={}",
                departmentId, d.getName(), order.get("id"));
    }

    /** 审批驳回：部门<b>保持原状</b>（不软删、不置灰），可再次申请。 */
    @Override
    public void onRejected(Map<String, Object> order) {
        log.info("department delete rejected, department kept as-is: departmentId={} orderId={}",
                idOf(order, "departmentId"), order.get("id"));
    }

    // ------------------------------------------------------------------ helpers

    private static String formData(Long departmentId, Long institutionId) {
        return "{\"departmentId\":" + departmentId + ",\"institutionId\":" + institutionId + "}";
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
