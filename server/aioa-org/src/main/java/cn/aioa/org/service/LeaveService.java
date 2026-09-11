package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.LeaveBalance;
import cn.aioa.org.entity.LeaveRequest;
import cn.aioa.org.entity.LeaveType;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.LeaveBalanceMapper;
import cn.aioa.org.mapper.LeaveRequestMapper;
import cn.aioa.org.mapper.LeaveTypeMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 请假流程升级（假种 / 余额 / 校验 / 扣减）+ 多级审批联动。
 *
 * <p>提交前全量校验（任一不过即拒绝并返回具体原因）：
 * 机构正常、假种启用、单次不超最长连续天数、满足提前申请天数、需证明则必须带证明、
 * 可用余额（total - used - pending）≥ 申请天数。
 * 审批通过扣减 used_days、释放 pending_days；驳回仅释放 pending_days。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class LeaveService implements ApprovalCallback {

    public static final String BIZ_TYPE = "LEAVE";

    private final LeaveTypeMapper typeMapper;
    private final LeaveBalanceMapper balanceMapper;
    private final LeaveRequestMapper requestMapper;
    private final OrgInstitutionMapper institutionMapper;
    private final OrgMemberMapper memberMapper;
    private final ApprovalFlowService flowService;
    private final AuditRecorder audit;
    private final ObjectMapper objectMapper;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    // ================================================================== 假种

    public List<LeaveType> listTypes(Long tenantId) {
        return typeMapper.selectList(new LambdaQueryWrapper<LeaveType>()
                .eq(LeaveType::getTenantId, tenantId)
                .orderByAsc(LeaveType::getSort)
                .orderByAsc(LeaveType::getId));
    }

    @Transactional(rollbackFor = Exception.class)
    public LeaveType saveType(Long tenantId, AuthUser actor, Map<String, Object> body) {
        Long id = body.get("id") instanceof Number n ? n.longValue() : null;
        if (id != null) {
            LeaveType t = typeMapper.selectById(id);
            if (t == null || !t.getTenantId().equals(tenantId)) {
                throw BizException.notFound("假种不存在：" + id);
            }
            if (body.get("name") != null) {
                t.setName(String.valueOf(body.get("name")));
            }
            if (body.get("unit") != null) {
                t.setUnit(String.valueOf(body.get("unit")));
            }
            if (body.containsKey("quotaDaysPerYear")) {
                t.setQuotaDaysPerYear(Vals.dec(body, "quotaDaysPerYear", t.getQuotaDaysPerYear()));
            }
            if (body.containsKey("needProof")) {
                t.setNeedProof(Vals.bool(body, "needProof", false));
            }
            if (body.containsKey("advanceDays")) {
                t.setAdvanceDays(Vals.integer(body, "advanceDays", 0));
            }
            if (body.containsKey("maxConsecutiveDays")) {
                t.setMaxConsecutiveDays(Vals.dec(body, "maxConsecutiveDays", t.getMaxConsecutiveDays()));
            }
            if (body.containsKey("paid")) {
                t.setPaid(Vals.bool(body, "paid", true));
            }
            if (body.containsKey("sort")) {
                t.setSort(Vals.integer(body, "sort", 0));
            }
            if (body.get("status") != null) {
                t.setStatus(String.valueOf(body.get("status")));
            }
            t.setUpdatedAt(LocalDateTime.now());
            typeMapper.updateById(t);
            audit.record(tenantId, 0L, actor, "LEAVE_TYPE_UPDATE", "LEAVE_TYPE", id,
                    "编辑假种「" + t.getName() + "」", null, t);
            return t;
        }
        LeaveType t = new LeaveType();
        t.setTenantId(tenantId);
        t.setCode(Vals.require(body, "code", "假种编码"));
        if (typeMapper.selectCount(new LambdaQueryWrapper<LeaveType>()
                .eq(LeaveType::getTenantId, tenantId).eq(LeaveType::getCode, t.getCode())) > 0) {
            throw BizException.badRequest("假种编码已存在：" + t.getCode());
        }
        t.setName(Vals.require(body, "name", "假种名称"));
        t.setUnit(Vals.str(body, "unit", "DAY"));
        t.setQuotaDaysPerYear(Vals.dec(body, "quotaDaysPerYear", BigDecimal.ZERO));
        t.setNeedProof(Vals.bool(body, "needProof", false));
        t.setAdvanceDays(Vals.integer(body, "advanceDays", 0));
        t.setMaxConsecutiveDays(Vals.dec(body, "maxConsecutiveDays", BigDecimal.ZERO));
        t.setPaid(Vals.bool(body, "paid", true));
        t.setSort(Vals.integer(body, "sort", 0));
        t.setStatus("ENABLED");
        t.setCreatedAt(LocalDateTime.now());
        t.setCreatedBy(actor.getUserId());
        typeMapper.insert(t);
        audit.record(tenantId, 0L, actor, "LEAVE_TYPE_CREATE", "LEAVE_TYPE", t.getId(),
                "新增假种「" + t.getName() + "」", null, t);
        return t;
    }

    // ================================================================== 余额

    public List<Map<String, Object>> balance(Long tenantId, Long institutionId, Long userId, Integer year) {
        int y = year == null ? LocalDate.now().getYear() : year;
        List<LeaveBalance> rows = balanceMapper.selectList(new LambdaQueryWrapper<LeaveBalance>()
                .eq(LeaveBalance::getTenantId, tenantId)
                .eq(LeaveBalance::getUserId, userId)
                .eq(LeaveBalance::getYear, y));
        Map<String, LeaveType> types = new LinkedHashMap<>();
        for (LeaveType t : listTypes(tenantId)) {
            types.put(t.getCode(), t);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (LeaveBalance b : rows) {
            LeaveType t = types.get(b.getLeaveTypeCode());
            out.add(balanceView(b, t));
        }
        return out;
    }

    private Map<String, Object> balanceView(LeaveBalance b, LeaveType t) {
        Map<String, Object> m = new LinkedHashMap<>();
        BigDecimal total = nzb(b.getTotalDays());
        BigDecimal used = nzb(b.getUsedDays());
        BigDecimal pending = nzb(b.getPendingDays());
        m.put("id", b.getId());
        m.put("leaveTypeCode", b.getLeaveTypeCode());
        m.put("leaveTypeName", t == null ? b.getLeaveTypeCode() : t.getName());
        m.put("unit", t == null ? "DAY" : t.getUnit());
        m.put("year", b.getYear());
        m.put("totalDays", total);
        m.put("usedDays", used);
        m.put("pendingDays", pending);
        m.put("availableDays", total.subtract(used).subtract(pending));
        // 年度额度为 0 的假种（如无薪事假）不占额度：可用天数无意义，前端应展示「不占额度」
        m.put("quotaTracked", t != null && nzb(t.getQuotaDaysPerYear()).signum() > 0);
        return m;
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> upsertBalance(Long tenantId, Long institutionId, AuthUser actor,
                                             Map<String, Object> body) {
        Long userId = Vals.lngObj(body, "userId");
        if (userId == null) {
            throw BizException.badRequest("userId 不能为空");
        }
        String code = Vals.require(body, "leaveTypeCode", "假种编码");
        int year = Vals.integer(body, "year", LocalDate.now().getYear());
        LeaveBalance b = findBalance(tenantId, userId, code, year);
        boolean isNew = b == null;
        if (isNew) {
            b = new LeaveBalance();
            b.setTenantId(tenantId);
            b.setInstitutionId(institutionId == null ? 0L : institutionId);
            b.setUserId(userId);
            b.setLeaveTypeCode(code);
            b.setYear(year);
            b.setUsedDays(BigDecimal.ZERO);
            b.setPendingDays(BigDecimal.ZERO);
            b.setCreatedAt(LocalDateTime.now());
            b.setCreatedBy(actor == null ? 0L : actor.getUserId());
        }
        b.setTotalDays(Vals.dec(body, "totalDays", nzb(b.getTotalDays())));
        b.setUpdatedAt(LocalDateTime.now());
        if (isNew) {
            balanceMapper.insert(b);
        } else {
            balanceMapper.updateById(b);
        }
        audit.record(tenantId, institutionId, actor, isNew ? "LEAVE_BALANCE_CREATE" : "LEAVE_BALANCE_UPDATE",
                "LEAVE_BALANCE", b.getId(), "设置 " + year + " 年度「" + code + "」额度为 "
                        + b.getTotalDays() + " 天（用户 #" + userId + "）", null, b);
        return balanceView(b, null);
    }

    private LeaveBalance findBalance(Long tenantId, Long userId, String code, int year) {
        List<LeaveBalance> rows = balanceMapper.selectList(new LambdaQueryWrapper<LeaveBalance>()
                .eq(LeaveBalance::getTenantId, tenantId)
                .eq(LeaveBalance::getUserId, userId)
                .eq(LeaveBalance::getLeaveTypeCode, code)
                .eq(LeaveBalance::getYear, year)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    // ================================================================== 提交请假

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> submit(AuthUser actor, Map<String, Object> body) {
        Long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();
        Long userId = Vals.lngObj(body, "userId") == null ? actor.getUserId() : Vals.lngObj(body, "userId");
        boolean asProxy = !userId.equals(actor.getUserId());

        OrgMember member = memberMapper.selectOne(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getUserId, userId)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .last("limit 1"));
        if (member == null) {
            throw BizException.badRequest("该账号未绑定机构，无法发起请假（请先在组织管理中登记员工）");
        }
        Long institutionId = Vals.lngObj(body, "institutionId") == null
                ? member.getInstitutionId() : Vals.lngObj(body, "institutionId");
        if (!institutionId.equals(member.getInstitutionId())) {
            throw BizException.forbidden("只能为本人所属机构（#" + member.getInstitutionId() + "）发起请假");
        }
        OrgInstitution inst = institutionMapper.selectById(institutionId);
        if (inst == null || OrgInstitution.STATUS_CLOSED.equals(inst.getStatus())) {
            throw BizException.badRequest("机构不存在或已注销，无法发起请假");
        }
        if (OrgInstitution.STATUS_SUSPENDED.equals(inst.getStatus())) {
            throw BizException.badRequest("机构已停用，暂不可发起请假");
        }

        String code = Vals.require(body, "leaveTypeCode", "假种");
        LeaveType type = typeMapper.selectOne(new LambdaQueryWrapper<LeaveType>()
                .eq(LeaveType::getTenantId, tenantId)
                .eq(LeaveType::getCode, code)
                .last("limit 1"));
        if (type == null) {
            throw BizException.badRequest("假种不存在：" + code);
        }
        if (!"ENABLED".equalsIgnoreCase(String.valueOf(type.getStatus()))) {
            throw BizException.badRequest("假种「" + type.getName() + "」已停用，不可申请");
        }

        LocalDate start = Vals.date(body, "startDate");
        LocalDate end = Vals.date(body, "endDate");
        if (start == null || end == null) {
            throw BizException.badRequest("请选择开始与结束日期");
        }
        if (end.isBefore(start)) {
            throw BizException.badRequest("结束日期不能早于开始日期");
        }
        BigDecimal days = calcDays(type, start, end, Vals.dec(body, "days", null));
        if (days.signum() <= 0) {
            throw BizException.badRequest("申请天数为 0（所选区间可能全部为休息日）");
        }
        if (nzb(type.getMaxConsecutiveDays()).signum() > 0
                && days.compareTo(nzb(type.getMaxConsecutiveDays())) > 0) {
            throw BizException.badRequest("单次「" + type.getName() + "」最长 "
                    + type.getMaxConsecutiveDays() + " 天，本次申请 " + days + " 天（FR 请假校验）");
        }
        int advance = type.getAdvanceDays() == null ? 0 : type.getAdvanceDays();
        if (advance > 0 && start.isBefore(LocalDate.now().plusDays(advance))) {
            throw BizException.badRequest("「" + type.getName() + "」需提前 " + advance
                    + " 天申请（最早可申请 " + LocalDate.now().plusDays(advance) + "）");
        }
        Long proofFileId = Vals.lngObj(body, "proofFileId");
        if (Boolean.TRUE.equals(type.getNeedProof()) && proofFileId == null) {
            throw BizException.badRequest("「" + type.getName() + "」必须上传证明材料");
        }

        int year = start.getYear();
        LeaveBalance balance = findBalance(tenantId, userId, code, year);
        if (balance == null) {
            // 首次申请自动按假种年度额度开通余额
            balance = new LeaveBalance();
            balance.setTenantId(tenantId);
            balance.setInstitutionId(institutionId);
            balance.setUserId(userId);
            balance.setLeaveTypeCode(code);
            balance.setYear(year);
            balance.setTotalDays(nzb(type.getQuotaDaysPerYear()));
            balance.setUsedDays(BigDecimal.ZERO);
            balance.setPendingDays(BigDecimal.ZERO);
            balance.setCreatedAt(LocalDateTime.now());
            balance.setCreatedBy(actor.getUserId());
            balanceMapper.insert(balance);
        }
        // 年度额度为 0 的假种（如无薪事假）不占额度、不做余额校验，仅走审批；
        // 若对其也累加 pending，会出现 availableAfterPending 为负数这类自相矛盾的口径。
        boolean quotaTracked = nzb(type.getQuotaDaysPerYear()).signum() > 0;
        BigDecimal available = nzb(balance.getTotalDays())
                .subtract(nzb(balance.getUsedDays())).subtract(nzb(balance.getPendingDays()));
        if (quotaTracked && available.compareTo(days) < 0) {
            throw BizException.badRequest("「" + type.getName() + "」可用余额不足：可用 " + available
                    + " 天，本次申请 " + days + " 天（可用 = 额度 - 已用 - 在途）");
        }

        // 落请假单
        LeaveRequest req = new LeaveRequest();
        req.setTenantId(tenantId);
        req.setInstitutionId(institutionId);
        req.setDepartmentId(member.getDepartmentId() == null ? 0L : member.getDepartmentId());
        req.setUserId(userId);
        req.setApplicantName(member.getName() == null ? AuditRecorder.displayName(actor) : member.getName());
        req.setLeaveTypeCode(code);
        req.setStartDate(start);
        req.setEndDate(end);
        req.setDays(days);
        req.setReason(Vals.str(body, "reason"));
        req.setProofFileId(proofFileId);
        req.setStatus(LeaveRequest.PENDING);
        req.setCreatedAt(LocalDateTime.now());
        req.setCreatedBy(actor.getUserId());
        requestMapper.insert(req);

        // 占用在途额度（不占额度的假种跳过，避免产生负数可用天数）
        if (quotaTracked) {
            balance.setPendingDays(nzb(balance.getPendingDays()).add(days));
            balance.setUpdatedAt(LocalDateTime.now());
            balanceMapper.updateById(balance);
        }

        // 展开多级审批
        String formData = toJson(Map.of(
                "leaveRequestId", req.getId(),
                "leaveTypeCode", code,
                "leaveTypeName", type.getName(),
                "startDate", start.toString(),
                "endDate", end.toString(),
                "days", days,
                "reason", req.getReason() == null ? "" : req.getReason()));
        Map<String, Object> flow = flowService.submit(tenantId, actor,
                new ApprovalFlowService.SubmitReq(BIZ_TYPE,
                        req.getApplicantName() + " 的" + type.getName() + "申请（" + days + " 天）",
                        "起止：" + start + " ~ " + end + "；事由：" + (req.getReason() == null ? "未填写" : req.getReason()),
                        formData, institutionId, req.getDepartmentId(), days.doubleValue(),
                        userId, req.getApplicantName(), null));
        Long orderId = ((Number) flow.get("orderId")).longValue();
        req.setOrderId(orderId);
        req.setUpdatedAt(LocalDateTime.now());
        requestMapper.updateById(req);

        audit.record(tenantId, institutionId, actor,
                asProxy ? "LEAVE_SUBMIT_PROXY" : "LEAVE_SUBMIT", "LEAVE_REQUEST", req.getId(),
                (asProxy ? "代" + req.getApplicantName() + " 提交" : "提交") + type.getName()
                        + "申请 " + days + " 天（" + start + " ~ " + end + "），"
                        + (quotaTracked ? "在途占用 " + days + " 天" : "该假种不占额度"),
                null, req);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("leaveRequestId", req.getId());
        out.put("orderId", orderId);
        out.put("status", LeaveRequest.PENDING);
        out.put("days", days);
        out.put("leaveTypeName", type.getName());
        // 不占额度的假种没有「申请后可用天数」的概念，返回 null 而不是负数
        out.put("quotaTracked", quotaTracked);
        out.put("availableAfterPending", quotaTracked ? available.subtract(days) : null);
        out.put("nodeCount", flow.get("nodeCount"));
        out.put("timeline", flow.get("timeline"));
        return out;
    }

    /** 天数计算：WORKDAY 只算工作日（周一~周五）；DAY 按自然日；显式传入 days 时以传入为准。 */
    private BigDecimal calcDays(LeaveType type, LocalDate start, LocalDate end, BigDecimal explicit) {
        if (explicit != null && explicit.signum() > 0) {
            return explicit.setScale(1, RoundingMode.HALF_UP);
        }
        long n = 0;
        boolean workday = "WORKDAY".equalsIgnoreCase(String.valueOf(type.getUnit()));
        for (LocalDate d = start; !d.isAfter(end); d = d.plusDays(1)) {
            if (workday) {
                DayOfWeek w = d.getDayOfWeek();
                if (w == DayOfWeek.SATURDAY || w == DayOfWeek.SUNDAY) {
                    continue;
                }
            }
            n++;
        }
        return BigDecimal.valueOf(n).setScale(1, RoundingMode.HALF_UP);
    }

    // ================================================================== 查询 / 撤销

    public List<Map<String, Object>> myRequests(Long tenantId, Long userId) {
        List<LeaveRequest> rows = requestMapper.selectList(new LambdaQueryWrapper<LeaveRequest>()
                .eq(LeaveRequest::getTenantId, tenantId)
                .eq(LeaveRequest::getUserId, userId)
                .orderByDesc(LeaveRequest::getId));
        return viewAll(rows);
    }

    public List<Map<String, Object>> institutionRequests(Long tenantId, Long institutionId, String status) {
        LambdaQueryWrapper<LeaveRequest> w = new LambdaQueryWrapper<LeaveRequest>()
                .eq(LeaveRequest::getTenantId, tenantId)
                .eq(LeaveRequest::getInstitutionId, institutionId);
        if (status != null && !status.isBlank()) {
            w.eq(LeaveRequest::getStatus, status);
        }
        return viewAll(requestMapper.selectList(w.orderByDesc(LeaveRequest::getId)
                .last("limit 300")));
    }

    private List<Map<String, Object>> viewAll(List<LeaveRequest> rows) {
        Map<String, LeaveType> types = new LinkedHashMap<>();
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (LeaveRequest r : rows) {
            if (!types.containsKey(r.getLeaveTypeCode()) && r.getTenantId() != null) {
                for (LeaveType t : listTypes(r.getTenantId())) {
                    types.put(t.getCode(), t);
                }
            }
            LeaveType t = types.get(r.getLeaveTypeCode());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", r.getId());
            m.put("institutionId", r.getInstitutionId());
            m.put("departmentId", r.getDepartmentId());
            m.put("userId", r.getUserId());
            m.put("applicantName", r.getApplicantName());
            m.put("orderId", r.getOrderId());
            m.put("leaveTypeCode", r.getLeaveTypeCode());
            m.put("leaveTypeName", t == null ? r.getLeaveTypeCode() : t.getName());
            m.put("startDate", r.getStartDate() == null ? null : r.getStartDate().toString());
            m.put("endDate", r.getEndDate() == null ? null : r.getEndDate().toString());
            m.put("days", r.getDays());
            m.put("reason", r.getReason());
            m.put("proofFileId", r.getProofFileId());
            m.put("status", r.getStatus());
            m.put("createdAt", r.getCreatedAt() == null ? null : r.getCreatedAt().toString());
            if (r.getOrderId() != null) {
                m.put("timeline", flowService.timeline(r.getOrderId()));
            }
            out.add(m);
        }
        return out;
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> cancel(Long requestId, AuthUser actor) {
        LeaveRequest r = requestMapper.selectById(requestId);
        if (r == null) {
            throw BizException.notFound("请假单不存在：" + requestId);
        }
        if (!r.getUserId().equals(actor.getUserId())) {
            throw BizException.forbidden("只能撤销本人的请假申请");
        }
        if (!LeaveRequest.PENDING.equals(r.getStatus())) {
            throw BizException.badRequest("当前状态（" + r.getStatus() + "）不可撤销");
        }
        releasePending(r);
        r.setStatus(LeaveRequest.CANCELED);
        r.setUpdatedAt(LocalDateTime.now());
        requestMapper.updateById(r);
        audit.record(r.getTenantId(), r.getInstitutionId(), actor, "LEAVE_CANCEL", "LEAVE_REQUEST", requestId,
                "撤销请假申请（释放在途 " + r.getDays() + " 天）", null, r);
        return Map.of("id", requestId, "status", LeaveRequest.CANCELED);
    }

    // ================================================================== 审批回调

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        LeaveRequest r = findByOrder(order);
        if (r == null || !LeaveRequest.PENDING.equals(r.getStatus())) {
            return;
        }
        LeaveBalance b = findBalance(r.getTenantId(), r.getUserId(), r.getLeaveTypeCode(),
                r.getStartDate().getYear());
        if (b != null) {
            BigDecimal days = nzb(r.getDays());
            b.setPendingDays(max0(nzb(b.getPendingDays()).subtract(days)));
            b.setUsedDays(nzb(b.getUsedDays()).add(days));
            b.setUpdatedAt(LocalDateTime.now());
            balanceMapper.updateById(b);
        }
        r.setStatus(LeaveRequest.APPROVED);
        r.setUpdatedAt(LocalDateTime.now());
        requestMapper.updateById(r);
        log.info("leave approved: requestId={} days={} orderId={}", r.getId(), r.getDays(), r.getOrderId());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onRejected(Map<String, Object> order) {
        LeaveRequest r = findByOrder(order);
        if (r == null || !LeaveRequest.PENDING.equals(r.getStatus())) {
            return;
        }
        releasePending(r);
        r.setStatus(LeaveRequest.REJECTED);
        r.setUpdatedAt(LocalDateTime.now());
        requestMapper.updateById(r);
        log.info("leave rejected: requestId={} orderId={}", r.getId(), r.getOrderId());
    }

    private void releasePending(LeaveRequest r) {
        LeaveBalance b = findBalance(r.getTenantId(), r.getUserId(), r.getLeaveTypeCode(),
                r.getStartDate().getYear());
        if (b != null) {
            b.setPendingDays(max0(nzb(b.getPendingDays()).subtract(nzb(r.getDays()))));
            b.setUpdatedAt(LocalDateTime.now());
            balanceMapper.updateById(b);
        }
    }

    private LeaveRequest findByOrder(Map<String, Object> order) {
        Object id = order.get("id");
        if (!(id instanceof Number n)) {
            return null;
        }
        List<LeaveRequest> rows = requestMapper.selectList(new LambdaQueryWrapper<LeaveRequest>()
                .eq(LeaveRequest::getOrderId, n.longValue())
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 审批节点信息（供企业端审批页展示）。 */
    public List<ApprovalTask> tasksOfOrder(Long orderId) {
        return flowService.timeline(orderId).stream().map(m -> {
            ApprovalTask t = new ApprovalTask();
            t.setId(((Number) m.get("taskId")).longValue());
            t.setOrderId(orderId);
            t.setSeq((Integer) m.get("seq"));
            t.setApproverType((String) m.get("approverType"));
            t.setApproverName((String) m.get("approverName"));
            t.setStatus((String) m.get("status"));
            t.setNote((String) m.get("note"));
            return t;
        }).collect(java.util.stream.Collectors.toList());
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            throw BizException.badRequest("表单序列化失败：" + e.getMessage());
        }
    }

    static BigDecimal nzb(BigDecimal v) {
        return v == null ? BigDecimal.ZERO : v;
    }

    private static BigDecimal max0(BigDecimal v) {
        return v.signum() < 0 ? BigDecimal.ZERO : v;
    }
}
