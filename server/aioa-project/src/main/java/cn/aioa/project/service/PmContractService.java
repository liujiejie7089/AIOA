package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.project.entity.PmContract;
import cn.aioa.project.entity.PmContractPayment;
import cn.aioa.project.entity.PmExpense;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.mapper.PmContractMapper;
import cn.aioa.project.mapper.PmContractPaymentMapper;
import cn.aioa.project.mapper.PmExpenseMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 项目合同服务（PM 批次 4，V73）。设计依据 {@code docs/40 §6.3/BR-09}。
 *
 * <p>用户关键词「合同（采购，收款）」→ {@link PmContract#getDirection()}：
 * OUT 采购付款 / IN 收款；分类 {@link PmContract#getCategory()}。</p>
 *
 * <p><b>BR-09（单一事实源）</b>：{@link #confirmPayment} 在**同一事务**内
 * ① 把收付款置 {@code CONFIRMED} 并写实收/实付；② 自动生成一条 {@code pm_expense}
 * （{@code contract_payment_id} 溯源）。禁止两边各记一遍。已确认的收付款**不可删**，
 * 只能 {@link #reversePayment}（红冲：置 REVERSED + 追加反向流水）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmContractService {

    private final PmContractMapper contractMapper;
    private final PmContractPaymentMapper paymentMapper;
    private final PmExpenseMapper expenseMapper;
    private final PmProjectService projectService;
    private final PmExpenseService expenseService;

    // ======================================================================
    // 合同
    // ======================================================================

    public Map<String, Object> list(AuthUser user, Long projectId, String direction) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        LambdaQueryWrapper<PmContract> w = new LambdaQueryWrapper<PmContract>()
                .eq(PmContract::getTenantId, p.getTenantId())
                .eq(PmContract::getProjectId, projectId)
                .orderByDesc(PmContract::getId);
        if (direction != null && !direction.isBlank()) {
            w.eq(PmContract::getDirection, direction);
        }
        List<Map<String, Object>> items = new ArrayList<>();
        contractMapper.selectList(w).forEach(c -> items.add(contractView(c)));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("canManage", canWrite(user, p));
        out.put("items", items);
        out.put("total", items.size());
        out.put("statuses", statusOptions());
        out.put("directions", directionOptions());
        return out;
    }

    @Transactional
    public Map<String, Object> create(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();

        String no = PmExpenseService.str(body.get("contractNo"));
        if (no.isEmpty()) {
            throw BizException.badRequest("合同编号不能为空");
        }
        String name = PmExpenseService.str(body.get("name"));
        if (name.isEmpty()) {
            throw BizException.badRequest("合同名称不能为空");
        }
        String direction = PmExpenseService.str(body.get("direction"));
        if (!PmContract.DIR_IN.equals(direction) && !PmContract.DIR_OUT.equals(direction)) {
            throw BizException.badRequest("合同方向必须为 IN（收款）或 OUT（采购付款）");
        }
        // 软删行从唯一键消失 ⇒ 插入前先查活行（V71 约定）
        Long dup = contractMapper.selectCount(new LambdaQueryWrapper<PmContract>()
                .eq(PmContract::getTenantId, tenantId)
                .eq(PmContract::getContractNo, no));
        if (dup != null && dup > 0) {
            throw new BizException(409, "合同编号已存在：" + no);
        }

        PmContract c = new PmContract();
        c.setTenantId(tenantId);
        c.setProjectId(projectId);
        c.setContractNo(no);
        c.setName(name);
        c.setDirection(direction);
        c.setCategory(categoryOrDefault(PmExpenseService.str(body.get("category")), direction));
        c.setPartyName(PmExpenseService.str(body.get("partyName")));
        c.setAmount(orZero(PmExpenseService.decimal(body.get("amount"))));
        c.setStatus(PmContract.ST_DRAFT);
        c.setSignedAt(date(body.get("signedAt")));
        c.setStartDate(date(body.get("startDate")));
        c.setEndDate(date(body.get("endDate")));
        c.setFileId(PmExpenseService.asLong(body.get("fileId")));
        c.setCreatedBy(user.getUserId());
        c.setCreatedAt(LocalDateTime.now());
        contractMapper.insert(c);
        return contractView(c);
    }

    @Transactional
    public Map<String, Object> update(AuthUser user, Long projectId, Long contractId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmContract c = requireContract(p, projectId, contractId);
        if (PmContract.ST_CLOSED.equals(c.getStatus()) || PmContract.ST_TERMINATED.equals(c.getStatus())) {
            throw new BizException(409, "合同已结/已终止，不可修改");
        }
        if (body.containsKey("name")) {
            String n = PmExpenseService.str(body.get("name"));
            if (n.isEmpty()) {
                throw BizException.badRequest("合同名称不能为空");
            }
            c.setName(n);
        }
        if (body.containsKey("partyName")) {
            c.setPartyName(PmExpenseService.str(body.get("partyName")));
        }
        if (body.containsKey("amount")) {
            c.setAmount(orZero(PmExpenseService.decimal(body.get("amount"))));
        }
        if (body.containsKey("category")) {
            c.setCategory(categoryOrDefault(PmExpenseService.str(body.get("category")), c.getDirection()));
        }
        if (body.containsKey("signedAt")) {
            c.setSignedAt(date(body.get("signedAt")));
        }
        if (body.containsKey("startDate")) {
            c.setStartDate(date(body.get("startDate")));
        }
        if (body.containsKey("endDate")) {
            c.setEndDate(date(body.get("endDate")));
        }
        if (body.containsKey("fileId")) {
            c.setFileId(PmExpenseService.asLong(body.get("fileId")));
        }
        c.setUpdatedAt(LocalDateTime.now());
        contractMapper.updateById(c);
        return contractView(c);
    }

    @Transactional
    public Map<String, Object> changeStatus(AuthUser user, Long projectId, Long contractId, String status) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmContract c = requireContract(p, projectId, contractId);
        boolean ok = PmContract.ST_DRAFT.equals(status) || PmContract.ST_PENDING.equals(status)
                || PmContract.ST_SIGNED.equals(status) || PmContract.ST_EXECUTING.equals(status)
                || PmContract.ST_CLOSED.equals(status) || PmContract.ST_TERMINATED.equals(status);
        if (!ok) {
            throw BizException.badRequest("未知合同状态：" + status);
        }
        if (PmContract.ST_CLOSED.equals(c.getStatus()) || PmContract.ST_TERMINATED.equals(c.getStatus())) {
            throw new BizException(409, "合同已结/已终止，状态不可再改");
        }
        c.setStatus(status);
        c.setUpdatedAt(LocalDateTime.now());
        contractMapper.updateById(c);
        return contractView(c);
    }

    // ======================================================================
    // 收付款明细（BR-09）
    // ======================================================================

    public Map<String, Object> payments(AuthUser user, Long projectId, Long contractId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        PmContract c = requireContract(p, projectId, contractId);
        return paymentsPayload(p, c);
    }

    private Map<String, Object> paymentsPayload(PmProject p, PmContract c) {
        List<PmContractPayment> rows = paymentMapper.selectList(new LambdaQueryWrapper<PmContractPayment>()
                .eq(PmContractPayment::getTenantId, p.getTenantId())
                .eq(PmContractPayment::getContractId, c.getId())
                .orderByAsc(PmContractPayment::getSeq));
        List<Map<String, Object>> items = new ArrayList<>();
        rows.forEach(x -> items.add(paymentView(x)));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("contract", contractView(c));
        out.put("items", items);
        out.put("total", items.size());
        return out;
    }

    /** 新增一期收付款计划。 */
    @Transactional
    public Map<String, Object> addPayment(AuthUser user, Long projectId, Long contractId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmContract c = requireContract(p, projectId, contractId);

        Long maxSeq = null;
        for (PmContractPayment x : paymentMapper.selectList(new LambdaQueryWrapper<PmContractPayment>()
                .eq(PmContractPayment::getContractId, c.getId()))) {
            if (maxSeq == null || x.getSeq() > maxSeq) {
                maxSeq = (long) x.getSeq();
            }
        }
        PmContractPayment pay = new PmContractPayment();
        pay.setTenantId(p.getTenantId());
        pay.setContractId(c.getId());
        pay.setSeq(maxSeq == null ? 1 : (int) (maxSeq + 1));
        pay.setPlanAmount(orZero(PmExpenseService.decimal(body.get("planAmount"))));
        pay.setPlanDate(date(body.get("planDate")));
        pay.setActualAmount(BigDecimal.ZERO);
        pay.setStatus(PmContractPayment.ST_PLANNED);
        pay.setMilestoneId(PmExpenseService.asLong(body.get("milestoneId")));
        pay.setCreatedAt(LocalDateTime.now());
        paymentMapper.insert(pay);
        return paymentMap(p, c);
    }

    /**
     * 确认实收/实付 —— <b>BR-09</b>：同事务内置 CONFIRMED + 自动生成一条 pm_expense。
     *
     * <p>本方法不做 {@code selectById} 之外的「信息不全就静默成功」——金额/日期缺一律抛错判失败
     * （铁律 2：不可逆动作绝不静默成功）。</p>
     */
    @Transactional
    public Map<String, Object> confirmPayment(AuthUser user, Long projectId, Long contractId, Long paymentId,
                                              Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmContract c = requireContract(p, projectId, contractId);
        PmContractPayment pay = requirePayment(p, c, paymentId);
        if (!PmContractPayment.ST_PLANNED.equals(pay.getStatus())) {
            throw new BizException(409, "该期收付款当前状态为 " + pay.getStatus() + "，只能确认「计划」中的期次");
        }
        BigDecimal actual = PmExpenseService.decimal(body.get("actualAmount"));
        if (actual == null) {
            // 不填则默认按计划金额确认（明确取值，不静默）
            actual = pay.getPlanAmount();
        }
        if (actual.signum() < 0) {
            throw BizException.badRequest("实收/实付金额必须为非负数");
        }
        LocalDate actualDate = date(body.get("actualDate"));
        if (actualDate == null) {
            actualDate = LocalDate.now();
        }

        pay.setActualAmount(actual);
        pay.setActualDate(actualDate);
        pay.setStatus(PmContractPayment.ST_CONFIRMED);
        pay.setUpdatedAt(LocalDateTime.now());
        paymentMapper.updateById(pay);

        // BR-09：同一事务内生成经费流水（单一事实源）
        Map<String, Object> eb = new LinkedHashMap<>();
        eb.put("direction", PmContract.DIR_IN.equals(c.getDirection()) ? PmExpense.DIR_IN : PmExpense.DIR_OUT);
        eb.put("category", PmExpense.CAT_CONTRACT);
        eb.put("amount", actual);
        eb.put("occurredAt", actualDate.toString());
        eb.put("contractPaymentId", pay.getId());
        eb.put("remark", "合同《" + c.getName() + "》第 " + pay.getSeq() + " 期");
        expenseService.append(p.getTenantId(), projectId, eb, user.getUserId(), null, actual);

        log.info("合同收付款已确认 contractId={} paymentId={} amount={}", c.getId(), pay.getId(), actual);
        return paymentMap(p, c);
    }

    /** 红冲已确认的收付款：置 REVERSED + 追加反向经费流水；原收付款行不删。 */
    @Transactional
    public Map<String, Object> reversePayment(AuthUser user, Long projectId, Long contractId, Long paymentId,
                                              String reason) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmContract c = requireContract(p, projectId, contractId);
        PmContractPayment pay = requirePayment(p, c, paymentId);
        if (!PmContractPayment.ST_CONFIRMED.equals(pay.getStatus())) {
            throw new BizException(409, "只有「已确认」的收付款才能红冲");
        }
        pay.setStatus(PmContractPayment.ST_REVERSED);
        pay.setUpdatedAt(LocalDateTime.now());
        paymentMapper.updateById(pay);

        // 追加反向流水（原流水保留；红冲行 reversal_of 指向原流水）。
        // 语义与 PmExpenseService.reverse 保持一致：同方向 + 负金额（红字冲销），
        // 这样确认时自动入的账，红冲后能从同一方向桶原额退掉（见该类注释与判据 F5f）。
        List<PmExpense> linked = expenseMapper.selectList(new LambdaQueryWrapper<PmExpense>()
                .eq(PmExpense::getTenantId, p.getTenantId())
                .eq(PmExpense::getContractPaymentId, pay.getId()));
        for (PmExpense e : linked) {
            if (e.getReversalOf() != null) {
                continue;
            }
            Map<String, Object> rb = new LinkedHashMap<>();
            rb.put("direction", e.getDirection());
            rb.put("category", e.getCategory());
            rb.put("occurredAt", LocalDate.now().toString());
            rb.put("remark", "红冲合同《" + c.getName() + "》第 " + pay.getSeq() + " 期"
                    + (reason == null || reason.isBlank() ? "" : "：" + reason));
            expenseService.append(p.getTenantId(), projectId, rb, user.getUserId(), e.getId(), e.getAmount().negate());
        }
        log.info("合同收付款已红冲 contractId={} paymentId={}", c.getId(), pay.getId());
        return paymentMap(p, c);
    }

    // ======================================================================
    // 内部
    // ======================================================================

    private Map<String, Object> paymentMap(PmProject p, PmContract c) {
        return paymentsPayload(p, c);
    }

    private PmContract requireContract(PmProject p, Long projectId, Long contractId) {
        PmContract c = contractMapper.selectById(contractId);
        if (c == null || !Objects.equals(c.getTenantId(), p.getTenantId())
                || !Objects.equals(c.getProjectId(), projectId)) {
            throw BizException.notFound("合同不存在");
        }
        return c;
    }

    private PmContractPayment requirePayment(PmProject p, PmContract c, Long paymentId) {
        PmContractPayment pay = paymentMapper.selectById(paymentId);
        if (pay == null || !Objects.equals(pay.getTenantId(), p.getTenantId())
                || !Objects.equals(pay.getContractId(), c.getId())) {
            throw BizException.notFound("收付款期次不存在");
        }
        return pay;
    }

    private Map<String, Object> contractView(PmContract c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", c.getId());
        m.put("projectId", c.getProjectId());
        m.put("contractNo", c.getContractNo());
        m.put("name", c.getName());
        m.put("direction", c.getDirection());
        m.put("directionLabel", PmContract.DIR_IN.equals(c.getDirection()) ? "收款合同" : "采购付款合同");
        m.put("category", c.getCategory());
        m.put("partyName", c.getPartyName());
        m.put("amount", c.getAmount());
        m.put("status", c.getStatus());
        m.put("statusLabel", statusLabel(c.getStatus()));
        m.put("signedAt", c.getSignedAt());
        m.put("startDate", c.getStartDate());
        m.put("endDate", c.getEndDate());
        m.put("fileId", c.getFileId());
        m.put("createdAt", c.getCreatedAt());
        return m;
    }

    private Map<String, Object> paymentView(PmContractPayment x) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", x.getId());
        m.put("contractId", x.getContractId());
        m.put("seq", x.getSeq());
        m.put("planAmount", x.getPlanAmount());
        m.put("planDate", x.getPlanDate());
        m.put("actualAmount", x.getActualAmount());
        m.put("actualDate", x.getActualDate());
        m.put("status", x.getStatus());
        m.put("statusLabel", paymentStatusLabel(x.getStatus()));
        m.put("milestoneId", x.getMilestoneId());
        return m;
    }

    private String statusLabel(String s) {
        if (s == null) {
            return null;
        }
        return switch (s) {
            case PmContract.ST_DRAFT -> "草稿";
            case PmContract.ST_PENDING -> "审批中";
            case PmContract.ST_SIGNED -> "已签";
            case PmContract.ST_EXECUTING -> "履行中";
            case PmContract.ST_CLOSED -> "已结";
            case PmContract.ST_TERMINATED -> "已终止";
            default -> s;
        };
    }

    private String paymentStatusLabel(String s) {
        if (s == null) {
            return null;
        }
        return switch (s) {
            case PmContractPayment.ST_PLANNED -> "计划";
            case PmContractPayment.ST_CONFIRMED -> "已确认";
            case PmContractPayment.ST_REVERSED -> "已红冲";
            default -> s;
        };
    }

    private List<Map<String, Object>> statusOptions() {
        List<Map<String, Object>> l = new ArrayList<>();
        l.add(Map.of("value", PmContract.ST_DRAFT, "label", "草稿"));
        l.add(Map.of("value", PmContract.ST_PENDING, "label", "审批中"));
        l.add(Map.of("value", PmContract.ST_SIGNED, "label", "已签"));
        l.add(Map.of("value", PmContract.ST_EXECUTING, "label", "履行中"));
        l.add(Map.of("value", PmContract.ST_CLOSED, "label", "已结"));
        l.add(Map.of("value", PmContract.ST_TERMINATED, "label", "已终止"));
        return l;
    }

    private List<Map<String, Object>> directionOptions() {
        List<Map<String, Object>> l = new ArrayList<>();
        l.add(Map.of("value", PmContract.DIR_OUT, "label", "采购付款合同"));
        l.add(Map.of("value", PmContract.DIR_IN, "label", "收款合同"));
        return l;
    }

    private String categoryOrDefault(String category, String direction) {
        if (category != null && !category.isBlank()) {
            return category;
        }
        return PmContract.DIR_OUT.equals(direction) ? PmContract.CAT_PURCHASE : PmContract.CAT_SALES;
    }

    private boolean canWrite(AuthUser user, PmProject p) {
        return projectService.canManage(user, p)
                || PermissionCatalog.holds(user, PermissionCatalog.PM_CONTRACT_MANAGE);
    }

    private void requireWrite(AuthUser user, PmProject p) {
        if (!canWrite(user, p)) {
            throw BizException.forbidden("仅项目负责人/项目经理、机构管理员及以上可维护合同与收付款");
        }
    }

    private static BigDecimal orZero(BigDecimal v) {
        return v == null ? BigDecimal.ZERO : v;
    }

    private static LocalDate date(Object o) {
        if (o == null) {
            return null;
        }
        String s = String.valueOf(o).trim();
        if (s.isEmpty()) {
            return null;
        }
        return LocalDate.parse(s.length() > 10 ? s.substring(0, 10) : s);
    }
}
