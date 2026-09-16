package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.PermissionGrant;
import cn.aioa.org.mapper.ApprovalTaskMapper;
import cn.aioa.org.mapper.PermissionGrantMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 权限申请与审批（V36 需求①）。
 *
 * <p><b>全链路</b>：用户申请 → 本地存档（{@code permission_grant} PENDING，落所属单位）
 * → 部门审批 → 租户管理员发放 → 授权生效（{@code AuthUser.permissions} 实时可见）。</p>
 *
 * <p><b>为什么授权生效要单独一张表</b>：{@code AuthUser.permissions} 必须有一个
 * 「真实、可审计、能回收」的来源。写进 JWT 会导致授权收回需要重新登录；
 * 写在内存里重启即失效。落到表里 → {@code DbPermissionResolver} 每请求实时读取，
 * 「审批通过立即生效、回收立即失效」才成立。</p>
 *
 * <p><b>与 ApprovalCallback 的关系</b>：本类既是提交方也是终态回调方。
 * 通过 {@code ApprovalFlowService} 的 {@code ObjectProvider<ApprovalCallback>} 被反向调用，
 * 故<b>不能</b>在构造函数里注入 {@code ApprovalFlowService}（会形成构造器循环依赖），
 * 改用 {@code ObjectProvider} 惰性取用。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PermissionGrantService implements ApprovalCallback {

    public static final String BIZ_TYPE = "PERMISSION_GRANT";

    /** 同一用户同一权限的在途上限（防止刷单）。 */
    private static final int MAX_PENDING_PER_USER = 5;
    /** 默认授权有效期（天）；null 表示永久。 */
    private static final int DEFAULT_VALID_DAYS = 365;

    private final PermissionGrantMapper grantMapper;
    private final ApprovalTaskMapper taskMapper;
    private final OrgGuard guard;
    private final AuditRecorder audit;
    private final JdbcTemplate jdbc;
    /** 惰性取用，避免与 ApprovalFlowService 形成构造器循环依赖。 */
    private final org.springframework.beans.factory.ObjectProvider<ApprovalFlowService> flowService;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    // ================================================================== 申请

    public record ApplyReq(String permissionCode, String targetWorkerType, String reason,
                           Integer validDays,
                           // ↓ 二期新增（追加在末尾；缺省 / false / null = 一期行为）
                           Boolean applyAsDepartment, Long departmentId) {
    }

    /**
     * 提交权限申请：本地存档 + 拉起多级审批。
     *
     * <p>「本地存档」先落库再提交审批，且在同一事务内 —— 若审批提交失败，
     * 存档一并回滚，不会留下「有申请单没有审批单」的孤儿数据。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> apply(Long tenantId, AuthUser actor, ApplyReq req) {
        if (actor == null || actor.getUserId() == null) {
            throw BizException.forbidden("未登录");
        }
        String code = req == null ? null : trim(req.permissionCode());
        if (code == null) {
            throw BizException.badRequest("permissionCode 不能为空");
        }
        if (!PermissionCatalog.applicable(code)) {
            throw BizException.badRequest("未知或无需申请的权限码：" + code
                    + "；可申请权限：" + String.join("、", PermissionCatalog.applicablePermissions()));
        }
        long uid = actor.getUserId();

        // 二期（E-02/E-03）：以部门名义申请的分支。
        // 缺省（不传 / null / false）→ 完全走一期路径，逐字等价（A2-4）。
        boolean asDept = Boolean.TRUE.equals(req.applyAsDepartment());
        String applicantType = asDept ? ApprovalFlowService.APPLICANT_DEPARTMENT
                : ApprovalFlowService.APPLICANT_USER;
        Long subjectDeptId = null;
        if (asDept) {
            if (req.departmentId() == null || req.departmentId() <= 0) {
                throw BizException.badRequest("部门申请必须指定部门");
            }
            // 闸门：跨机构/跨租户/平台账号 → 404；同机构非本部门正职 → 403；越权一律**不落库**（E-05/A2-3）
            guard.requireDeptLeader(req.departmentId());
            subjectDeptId = req.departmentId();
        }

        if (PermissionCatalog.holds(actor, code)) {
            throw BizException.badRequest("你已持有权限「" + PermissionCatalog.nameOf(code) + "」，无需申请");
        }

        // 幂等分账（E-08）：
        //   个人申请按 (user_id, permission_code, applicant_type='USER')
        //   部门申请按 (department_id, permission_code, applicant_type='DEPARTMENT')
        // 两把键互不冲突 —— 负责人的个人申请不因部门申请被拦，反之亦然。
        LambdaQueryWrapper<PermissionGrant> idem = new LambdaQueryWrapper<PermissionGrant>()
                .eq(PermissionGrant::getPermissionCode, code)
                .eq(PermissionGrant::getApplicantType, applicantType)
                .isNull(PermissionGrant::getDeletedAt);
        if (asDept) {
            idem.eq(PermissionGrant::getDepartmentId, subjectDeptId);
        } else {
            idem.eq(PermissionGrant::getUserId, uid);
        }
        List<PermissionGrant> exist = grantMapper.selectList(idem.orderByDesc(PermissionGrant::getId));
        // 个人路径用「你」，部门路径用「该部门」—— 个人路径文案与一期逐字一致（缺省兼容）。
        String subject = asDept ? "该部门" : "你";
        for (PermissionGrant g : exist) {
            if (PermissionGrant.STATUS_PENDING.equals(g.getStatus())) {
                throw BizException.badRequest(subject + "已有一条「" + PermissionCatalog.nameOf(code)
                        + "」的待审申请（单号 #" + g.getOrderId() + "），请勿重复提交");
            }
            if (g.usable()) {
                throw BizException.badRequest(subject + "已持有权限「" + PermissionCatalog.nameOf(code) + "」，无需申请");
            }
        }
        long pendingCount = exist.stream().filter(g -> PermissionGrant.STATUS_PENDING.equals(g.getStatus())).count();
        if (pendingCount >= MAX_PENDING_PER_USER) {
            throw BizException.badRequest("待审申请过多（" + pendingCount + "），请等待处理后再提交");
        }

        long tid = tenantId == null ? (actor.getTenantId() == null ? 0L : actor.getTenantId()) : tenantId;
        Long institutionId = guard.resolveInstitutionId(uid);
        Long departmentId = departmentIdOf(uid);
        String applicantName = AuditRecorder.displayName(actor);

        // ① 本地存档：落所属单位 + 所属部门，状态 PENDING
        PermissionGrant g = new PermissionGrant();
        g.setTenantId(tid);
        g.setInstitutionId(institutionId == null ? 0L : institutionId);
        // 部门申请：主体部门取申请指定的部门（= 提交人所属部门）；个人申请仍取提交人所属部门。
        g.setDepartmentId(asDept ? subjectDeptId : (departmentId == null ? 0L : departmentId));
        g.setUserId(uid);
        g.setApplicantName(applicantName);
        g.setApplicantType(applicantType);
        g.setPermissionCode(code);
        g.setTargetWorkerType(req.targetWorkerType() == null || req.targetWorkerType().isBlank()
                ? PermissionCatalog.workerTypeOf(code) : req.targetWorkerType().trim());
        g.setReason(trim(req.reason()));
        g.setStatus(PermissionGrant.STATUS_PENDING);
        g.setCreatedBy(uid);
        g.setCreatedAt(LocalDateTime.now());
        g.setUpdatedAt(LocalDateTime.now());
        grantMapper.insert(g);

        // ② 拉起多级审批（PERMISSION_GRANT：部门负责人 → 租户管理员）
        ApprovalFlowService flow = flowService.getObject();
        if (flow == null) {
            throw BizException.badRequest("审批引擎未就绪，暂时无法提交申请");
        }
        Map<String, Object> submitted = flow.submit(tid, actor,
                new ApprovalFlowService.SubmitReq(
                        BIZ_TYPE,
                        "权限申请：" + PermissionCatalog.nameOf(code),
                        buildContent(g, actor),
                        buildFormData(g),
                        g.getInstitutionId(),
                        g.getDepartmentId(),
                        null,
                        uid,
                        applicantName,
                        null,
                        applicantType,
                        subjectDeptId));
        Long orderId = asLong(submitted.get("orderId"));
        g.setOrderId(orderId);
        g.setUpdatedAt(LocalDateTime.now());
        grantMapper.updateById(g);

        audit.record(tid, g.getInstitutionId(), actor, "PERMISSION_GRANT_APPLY", "PERMISSION_GRANT", g.getId(),
                "申请权限「" + PermissionCatalog.nameOf(code) + "」"
                        + (g.getReason() == null ? "" : "（理由：" + g.getReason() + "）"),
                null, Map.of("grantId", g.getId(), "orderId", orderId, "permissionCode", code));

        Map<String, Object> out = new LinkedHashMap<>(submitted);
        out.put("grantId", g.getId());
        out.put("permissionCode", code);
        out.put("permissionName", PermissionCatalog.nameOf(code));
        out.put("institutionId", g.getInstitutionId());
        out.put("departmentId", g.getDepartmentId());
        out.put("reason", g.getReason());
        // 二期主体字段（§5.1）：个人申请为 "USER" / null，部门申请为 "DEPARTMENT" / 部门 id
        out.put("applicantType", applicantType);
        out.put("applicantDepartmentId", subjectDeptId);
        return out;
    }

    private static String buildContent(PermissionGrant g, AuthUser actor) {
        StringBuilder sb = new StringBuilder();
        sb.append("申请人：").append(g.getApplicantName());
        if (g.getTargetWorkerType() != null) {
            sb.append("；用途：创建「").append(g.getTargetWorkerType()).append("」类型数字员工");
        }
        sb.append("；权限：").append(PermissionCatalog.nameOf(g.getPermissionCode()))
                .append("（").append(g.getPermissionCode()).append("）");
        sb.append("；说明：本权限允许角色为 ")
                .append(PermissionCatalog.rolesText(g.getPermissionCode()));
        if (g.getReason() != null) {
            sb.append("；申请理由：").append(g.getReason());
        }
        return sb.toString();
    }

    private static String buildFormData(PermissionGrant g) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(Map.of(
                    "grantId", g.getId(),
                    "permissionCode", g.getPermissionCode(),
                    "permissionName", PermissionCatalog.nameOf(g.getPermissionCode()),
                    "targetWorkerType", g.getTargetWorkerType() == null ? "" : g.getTargetWorkerType(),
                    "institutionId", g.getInstitutionId(),
                    "departmentId", g.getDepartmentId(),
                    "reason", g.getReason() == null ? "" : g.getReason()));
        } catch (Exception e) {
            return null;
        }
    }

    // ================================================================== 查询

    /** 我的权限申请（含流转路径）—— 用户端「我的申请」与申请页共用。 */
    public List<Map<String, Object>> mine(AuthUser actor) {
        ApprovalFlowService flow = flowService.getObject();
        return grantMapper.selectList(new LambdaQueryWrapper<PermissionGrant>()
                        .eq(PermissionGrant::getUserId, actor.getUserId())
                        .isNull(PermissionGrant::getDeletedAt)
                        .orderByDesc(PermissionGrant::getId))
                .stream().map(g -> withTimeline(toView(g), g.getOrderId(), flow)).toList();
    }

    /**
     * 给授权视图补上流转路径。
     *
     * <p>流转路径属于审批单（{@code approval_task}）而非授权单，所以必须回查。
     * 不补的话，用户端「我的申请」只能显示一个状态标签，
     * 用户无从知道「卡在谁那里」—— 需求①的「返回结果」就没兑现。</p>
     */
    private Map<String, Object> withTimeline(Map<String, Object> view, Long orderId, ApprovalFlowService flow) {
        if (orderId == null || flow == null) {
            return view;
        }
        try {
            List<Map<String, Object>> tl = flow.timeline(orderId);
            view.put("timeline", tl);
            for (Map<String, Object> node : tl) {
                if ("PENDING".equals(node.get("status"))) {
                    view.put("currentSeq", node.get("seq"));
                    view.put("currentApproverName", node.get("approverName"));
                    view.put("currentApproverType", node.get("approverType"));
                    break;
                }
            }
        } catch (Exception e) {
            log.warn("attach timeline failed: orderId={} err={}", orderId, e.getMessage());
        }
        return view;
    }

    /** 我当前持有的权限（含来源：角色内置 / 授权发放），供权限目录页展示。 */
    public List<Map<String, Object>> holdings(AuthUser actor) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (String code : PermissionCatalog.applicablePermissions()) {
            // 必须用「仅角色」判定：用 holds（角色∪授权）会把申请来的授权也算成角色内置，
            // 前端就会把「可回收的授权」误显示为「不可变的角色权限」。
            boolean byRole = PermissionCatalog.holdsByRole(actor, code);
            List<PermissionGrant> grants = grantMapper.selectList(new LambdaQueryWrapper<PermissionGrant>()
                    .eq(PermissionGrant::getUserId, actor.getUserId())
                    .eq(PermissionGrant::getPermissionCode, code)
                    .isNull(PermissionGrant::getDeletedAt)
                    .orderByDesc(PermissionGrant::getId));
            PermissionGrant active = grants.stream().filter(PermissionGrant::usable).findFirst().orElse(null);
            if (!byRole && active == null) {
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("permissionCode", code);
            m.put("permissionName", PermissionCatalog.nameOf(code));
            m.put("requiredRoles", PermissionCatalog.rolesText(code));
            m.put("byRole", byRole);
            m.put("byGrant", active != null);
            m.put("grantId", active == null ? null : active.getId());
            m.put("grantedAt", active == null || active.getGrantedAt() == null
                    ? null : active.getGrantedAt().toString());
            m.put("expireAt", active == null || active.getExpireAt() == null
                    ? null : active.getExpireAt().toString());
            out.add(m);
        }
        return out;
    }

    /** 权限目录：可申请项 + 我是否持有（H5 申请页与「创建数字员工」403 后的引导共用）。 */
    public Map<String, Object> catalog(AuthUser actor) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (String code : PermissionCatalog.applicablePermissions()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("permissionCode", code);
            m.put("permissionName", PermissionCatalog.nameOf(code));
            m.put("requiredRoles", PermissionCatalog.rolesText(code));
            m.put("workerType", PermissionCatalog.workerTypeOf(code));
            List<PermissionGrant> grants = grantMapper.selectList(new LambdaQueryWrapper<PermissionGrant>()
                    .eq(PermissionGrant::getUserId, actor.getUserId())
                    .eq(PermissionGrant::getPermissionCode, code)
                    .isNull(PermissionGrant::getDeletedAt)
                    .orderByDesc(PermissionGrant::getId));
            PermissionGrant pending = grants.stream()
                    .filter(g -> PermissionGrant.STATUS_PENDING.equals(g.getStatus())).findFirst().orElse(null);
            m.put("held", PermissionCatalog.holds(actor, code));
            m.put("pending", pending != null);
            m.put("pendingOrderId", pending == null ? null : pending.getOrderId());
            m.put("applicable", !PermissionCatalog.holds(actor, code) && pending == null);
            items.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        // 「创建数字员工」的准入也一并给出，便于 H5 判断是否要引导申请
        out.put("canCreateWorker", PermissionCatalog.holds(actor, PermissionCatalog.WORKER_CREATE));
        out.put("institutionId", guard.resolveInstitutionId(actor.getUserId()));
        // 二期 H5「以部门名义申请」开关的数据源（N-3：扩展 catalog，零新增端点）。
        // 口径与 OrgGuard.requireDeptLeader 同源（duty_code='DEPT_PRINCIPAL'，回落 leader_user_id）。
        List<OrgDepartment> led = guard.ledDepartments(actor.getUserId());
        List<Map<String, Object>> ledItems = new ArrayList<>(led.size());
        for (OrgDepartment d : led) {
            Map<String, Object> dm = new LinkedHashMap<>();
            dm.put("id", d.getId());
            dm.put("name", d.getName());
            ledItems.add(dm);
        }
        out.put("canApplyAsDepartment", !led.isEmpty());
        out.put("ledDepartments", ledItems);
        return out;
    }

    /** 待审 / 在途授权清单（租户管理员 / 企业管理员按单位维度查阅）。 */
    public Map<String, Object> pending(Long tenantId, AuthUser actor, Long institutionId) {
        LambdaQueryWrapper<PermissionGrant> w = new LambdaQueryWrapper<PermissionGrant>()
                .eq(PermissionGrant::getTenantId, tenantId)
                .isNull(PermissionGrant::getDeletedAt)
                .orderByDesc(PermissionGrant::getId);
        if (institutionId != null && institutionId > 0) {
            w.eq(PermissionGrant::getInstitutionId, institutionId);
        }
        List<Map<String, Object>> items = grantMapper.selectList(w).stream().map(this::toView).toList();
        Map<String, Object> byStatus = new LinkedHashMap<>();
        for (Map<String, Object> m : items) {
            byStatus.merge(String.valueOf(m.get("status")), 1, (a, b) -> (Integer) a + (Integer) b);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        out.put("stats", byStatus);
        out.put("tenantId", tenantId);
        out.put("institutionId", institutionId);
        return out;
    }

    /** 实时解析用户已生效的权限码（供 {@code DbPermissionResolver} 使用）。 */
    public List<String> activePermissionsOf(Long userId) {
        if (userId == null) {
            return List.of();
        }
        List<PermissionGrant> rows = grantMapper.selectList(new LambdaQueryWrapper<PermissionGrant>()
                .eq(PermissionGrant::getUserId, userId)
                .eq(PermissionGrant::getStatus, PermissionGrant.STATUS_ACTIVE)
                .isNull(PermissionGrant::getDeletedAt)
                .and(w -> w.isNull(PermissionGrant::getExpireAt)
                        .or().gt(PermissionGrant::getExpireAt, LocalDateTime.now())));
        List<String> out = new ArrayList<>();
        for (PermissionGrant g : rows) {
            if (g.getPermissionCode() != null && !out.contains(g.getPermissionCode())) {
                out.add(g.getPermissionCode());
            }
        }
        return out;
    }

    // ================================================================== 回收

    /** 回收授权：本人可撤销自己的，租户管理员可回收本租户的。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> revoke(Long grantId, AuthUser actor) {
        PermissionGrant g = grantMapper.selectById(grantId);
        if (g == null || g.getDeletedAt() != null) {
            throw BizException.notFound("授权单不存在：" + grantId);
        }
        boolean self = actor.getUserId() != null && actor.getUserId().equals(g.getUserId());
        boolean tenantAdmin = OrgGuard.hasRole(actor, OrgGuard.ROLE_TENANT_ADMIN)
                || OrgGuard.hasRole(actor, OrgGuard.ROLE_ADMIN);
        if (!self && !tenantAdmin) {
            throw BizException.forbidden("仅本人或租户管理员可回收该授权");
        }
        if (!tenantAdmin && actor.getTenantId() != null
                && g.getTenantId() != null && !actor.getTenantId().equals(g.getTenantId())) {
            throw BizException.notFound("授权单不存在：" + grantId);
        }
        if (PermissionGrant.STATUS_REVOKED.equals(g.getStatus())) {
            throw BizException.badRequest("该授权已回收");
        }
        if (PermissionGrant.STATUS_PENDING.equals(g.getStatus())) {
            throw BizException.badRequest("待审中的申请无法回收，请等待审批结果或联系审批人驳回");
        }
        String before = g.getStatus();
        g.setStatus(PermissionGrant.STATUS_REVOKED);
        g.setRevokedAt(LocalDateTime.now());
        g.setUpdatedAt(LocalDateTime.now());
        grantMapper.updateById(g);
        audit.record(g.getTenantId(), g.getInstitutionId(), actor, "PERMISSION_GRANT_REVOKE",
                "PERMISSION_GRANT", g.getId(),
                "回收权限「" + PermissionCatalog.nameOf(g.getPermissionCode()) + "」",
                Map.of("status", before), Map.of("status", g.getStatus()));
        return Map.of("grantId", g.getId(), "status", g.getStatus(),
                "permissionCode", g.getPermissionCode());
    }

    // ================================================================== 审批终态回调

    @Override
    public void onApproved(Map<String, Object> order) {
        Long grantId = resolveGrantId(order);
        if (grantId == null) {
            log.warn("PERMISSION_GRANT onApproved: 找不到 grantId, orderId={}", order.get("id"));
            return;
        }
        PermissionGrant g = grantMapper.selectById(grantId);
        if (g == null) {
            log.warn("PERMISSION_GRANT onApproved: 授权单不存在 {}", grantId);
            return;
        }
        if (!PermissionGrant.STATUS_PENDING.equals(g.getStatus())) {
            log.warn("PERMISSION_GRANT onApproved: 授权单非待审态 {} -> {}", grantId, g.getStatus());
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        g.setStatus(PermissionGrant.STATUS_ACTIVE);
        // 终审人 = 该单据最后一个已通过节点的审批人（approval_order.approver 只有姓名，取不到 userId）
        g.setGrantedBy(lastApproverId(g.getOrderId()));
        g.setGrantedAt(now);
        g.setExpireAt(now.plusDays(DEFAULT_VALID_DAYS));
        g.setUpdatedAt(now);
        grantMapper.updateById(g);
        audit.record(g.getTenantId(), g.getInstitutionId(), null, "PERMISSION_GRANT_APPROVE",
                "PERMISSION_GRANT", g.getId(),
                "权限「" + PermissionCatalog.nameOf(g.getPermissionCode()) + "」审批通过并发放给「"
                        + g.getApplicantName() + "」",
                null, Map.of("grantId", g.getId(), "userId", g.getUserId(),
                        "permissionCode", g.getPermissionCode(), "expireAt", String.valueOf(g.getExpireAt())));
        log.info("permission granted: userId={} code={} institution={} expireAt={}",
                g.getUserId(), g.getPermissionCode(), g.getInstitutionId(), g.getExpireAt());
    }

    @Override
    public void onRejected(Map<String, Object> order) {
        Long grantId = resolveGrantId(order);
        if (grantId == null) {
            return;
        }
        PermissionGrant g = grantMapper.selectById(grantId);
        if (g == null || !PermissionGrant.STATUS_PENDING.equals(g.getStatus())) {
            return;
        }
        // 驳回人/时间/意见都从「刚被驳回的那个节点」取：
        // 回调触发时 approval_order 的 decision_note 尚未反映本次决策（order 是决策前读的快照），
        // 依赖它会把意见记成 null —— 实测「驳回后审核记录看不到意见」即源于此。
        ApprovalTask rejected = lastTask(g.getOrderId(), ApprovalTask.REJECTED);
        LocalDateTime now = LocalDateTime.now();
        g.setStatus(PermissionGrant.STATUS_REJECTED);
        g.setAuditNote(rejected == null ? null : rejected.getNote());
        // granted_by / granted_at 在语义上是「终态处理人 / 处理时间」：
        // 通过 = 发放人，驳回 = 驳回人。需求④要求审核记录必须能回答「谁处理的」，
        // 驳回同样是一次处理，不能留空。
        g.setGrantedBy(rejected == null ? null : rejected.getApproverId());
        g.setGrantedAt(rejected != null && rejected.getDecidedAt() != null ? rejected.getDecidedAt() : now);
        g.setUpdatedAt(now);
        grantMapper.updateById(g);
        audit.record(g.getTenantId(), g.getInstitutionId(), null, "PERMISSION_GRANT_REJECT",
                "PERMISSION_GRANT", g.getId(),
                "权限「" + PermissionCatalog.nameOf(g.getPermissionCode()) + "」申请被驳回"
                        + (g.getAuditNote() == null ? "" : "，意见：" + g.getAuditNote()),
                null, Map.of("grantId", g.getId(),
                        "note", String.valueOf(g.getAuditNote()),
                        "rejectedBy", String.valueOf(g.getGrantedBy())));
    }

    /** 终审人：该单据最后一个「已通过」节点的审批人。 */
    private Long lastApproverId(Long orderId) {
        ApprovalTask t = lastTask(orderId, ApprovalTask.APPROVED);
        return t == null ? null : t.getApproverId();
    }

    /** 该单据最后一个处于指定状态的节点（按 seq 倒序取第一条）。 */
    private ApprovalTask lastTask(Long orderId, String status) {
        if (orderId == null) {
            return null;
        }
        List<ApprovalTask> rows = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getStatus, status)
                .orderByDesc(ApprovalTask::getSeq)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 从审批单反查授权单：优先 form_data.grantId，退回 bizType 匹配的单据。 */
    private Long resolveGrantId(Map<String, Object> order) {
        Object fd = order.get("formData");
        if (fd == null) {
            fd = order.get("form_data");
        }
        if (fd != null) {
            String s = String.valueOf(fd);
            try {
                com.fasterxml.jackson.databind.JsonNode n =
                        new com.fasterxml.jackson.databind.ObjectMapper().readTree(s);
                if (n.hasNonNull("grantId")) {
                    return n.get("grantId").asLong();
                }
            } catch (Exception ignored) {
                // 回退到下面按 orderId 反查
            }
        }
        Long orderId = asLong(order.get("id"));
        if (orderId == null) {
            return null;
        }
        List<PermissionGrant> rows = grantMapper.selectList(new LambdaQueryWrapper<PermissionGrant>()
                .eq(PermissionGrant::getOrderId, orderId)
                .isNull(PermissionGrant::getDeletedAt)
                .orderByDesc(PermissionGrant::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0).getId();
    }

    // ================================================================== 内部

    private Map<String, Object> toView(PermissionGrant g) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", g.getId());
        m.put("tenantId", g.getTenantId());
        m.put("institutionId", g.getInstitutionId());
        m.put("departmentId", g.getDepartmentId());
        m.put("userId", g.getUserId());
        m.put("applicantName", g.getApplicantName());
        // 二期主体（P-1/§5.5）：个人 → USER / null；部门 → DEPARTMENT / 部门 id + 部门名。
        String at = g.getApplicantType() == null ? ApprovalFlowService.APPLICANT_USER : g.getApplicantType();
        boolean dept = ApprovalFlowService.APPLICANT_DEPARTMENT.equals(at);
        m.put("applicantType", at);
        m.put("applicantDepartmentId", dept ? g.getDepartmentId() : null);
        m.put("applicantDepartmentName", dept ? deptNameOf(g.getDepartmentId()) : null);
        m.put("permissionCode", g.getPermissionCode());
        m.put("permissionName", PermissionCatalog.nameOf(g.getPermissionCode()));
        m.put("targetWorkerType", g.getTargetWorkerType());
        m.put("reason", g.getReason());
        m.put("status", g.getStatus());
        m.put("orderId", g.getOrderId());
        m.put("auditNote", g.getAuditNote());
        m.put("grantedBy", g.getGrantedBy());
        m.put("grantedAt", g.getGrantedAt() == null ? null : g.getGrantedAt().toString());
        m.put("expireAt", g.getExpireAt() == null ? null : g.getExpireAt().toString());
        m.put("revokedAt", g.getRevokedAt() == null ? null : g.getRevokedAt().toString());
        m.put("createdAt", g.getCreatedAt() == null ? null : g.getCreatedAt().toString());
        m.put("usable", g.usable());
        return m;
    }

    private Long departmentIdOf(Long userId) {
        try {
            List<Long> rows = jdbc.queryForList(
                    "SELECT department_id FROM org_member WHERE user_id = ? AND status = 'ACTIVE' "
                            + "AND deleted_at IS NULL ORDER BY id LIMIT 1", Long.class, userId);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    /** 部门名（部门申请单据展示用）；查不到返回 null，绝不阻断渲染。 */
    private String deptNameOf(Long departmentId) {
        if (departmentId == null || departmentId <= 0) {
            return null;
        }
        try {
            List<String> rows = jdbc.queryForList(
                    "SELECT name FROM org_department WHERE id = ? AND deleted_at IS NULL LIMIT 1",
                    String.class, departmentId);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    private static String trim(String s) {
        if (s == null) {
            return null;
        }
        String t = s.trim();
        return t.isEmpty() ? null : t;
    }

    private static Long asLong(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(v));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
