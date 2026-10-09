package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.entity.PmExpense;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.mapper.PmExpenseMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 项目经费服务（PM 批次 4，V73）。设计依据 {@code docs/40 §6.3/BR-09} + {@code docs/43 §4}。
 *
 * <p><b>追加式账目（append-only）—— 这是用户关键词「不能修改」的落地</b>：
 * 本服务**没有 update / delete 端点**。写错只能 {@link #reverse}（红冲）——
 * 新增一条「同方向、负金额」的红字流水（{@code reversal_of} 指向被冲销行），原行永不改。
 * 判据（可断言）：对同一条流水调用红冲两次必须失败；红冲行本身不能被再冲销；
 * 红冲后该方向的累计额必须**按原额回退**（结余随之回升）。</p>
 *
 * <p>关键词落地：「成本记录 / 费用明细」= 一行一条流水；「人员费用」= {@code category=LABOR}；
 * 「各项目成本」= 按 {@code project_id} 聚合；「分摊」= {@code alloc_ratio}；
 * 「不固定 / 增长」= 多行随时间累积。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmExpenseService {

    private final PmExpenseMapper expenseMapper;
    private final PmProjectService projectService;
    private final OrgGuard guard;

    // ======================================================================
    // 读
    // ======================================================================

    /** 项目经费：明细 + 预算执行汇总（超支只警示不阻断，BR-16）。 */
    public Map<String, Object> list(AuthUser user, Long projectId, String direction, String category) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        LambdaQueryWrapper<PmExpense> w = new LambdaQueryWrapper<PmExpense>()
                .eq(PmExpense::getTenantId, p.getTenantId())
                .eq(PmExpense::getProjectId, projectId)
                .orderByDesc(PmExpense::getOccurredAt)
                .orderByDesc(PmExpense::getId);
        if (direction != null && !direction.isBlank()) {
            w.eq(PmExpense::getDirection, direction);
        }
        if (category != null && !category.isBlank()) {
            w.eq(PmExpense::getCategory, category);
        }
        List<PmExpense> rows = expenseMapper.selectList(w);

        // 汇总按**全部**流水算（不受筛选影响），否则「筛选后结余变了」会被误读成账目错误
        List<PmExpense> all = expenseMapper.selectList(new LambdaQueryWrapper<PmExpense>()
                .eq(PmExpense::getTenantId, p.getTenantId())
                .eq(PmExpense::getProjectId, projectId));
        BigDecimal income = BigDecimal.ZERO;
        BigDecimal spent = BigDecimal.ZERO;
        for (PmExpense e : all) {
            if (PmExpense.DIR_IN.equals(e.getDirection())) {
                income = income.add(e.getAmount());
            } else {
                spent = spent.add(e.getAmount());
            }
        }
        BigDecimal budget = p.getBudgetAmount() == null ? BigDecimal.ZERO : p.getBudgetAmount();
        BigDecimal balance = budget.subtract(spent);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("canManage", canWrite(user, p));
        List<Map<String, Object>> items = new ArrayList<>();
        rows.forEach(e -> items.add(view(e)));
        out.put("items", items);
        out.put("total", items.size());
        Map<String, Object> sum = new LinkedHashMap<>();
        sum.put("budgetAmount", budget);
        sum.put("totalIncome", income);
        sum.put("totalOutcome", spent);
        sum.put("balance", balance);
        // BR-16：超支不阻断录入，只出警示
        sum.put("overrun", balance.signum() < 0);
        sum.put("categories", categoryOptions());
        sum.put("directions", List.of(
                Map.of("value", PmExpense.DIR_IN, "label", "收入"),
                Map.of("value", PmExpense.DIR_OUT, "label", "支出")));
        out.put("summary", sum);
        return out;
    }

    private Map<String, Object> view(PmExpense e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", e.getId());
        m.put("projectId", e.getProjectId());
        m.put("direction", e.getDirection());
        m.put("directionLabel", PmExpense.DIR_IN.equals(e.getDirection()) ? "收入" : "支出");
        m.put("category", e.getCategory());
        m.put("categoryLabel", categoryLabel(e.getCategory()));
        m.put("amount", e.getAmount());
        m.put("allocRatio", e.getAllocRatio());
        m.put("occurredAt", e.getOccurredAt());
        m.put("contractPaymentId", e.getContractPaymentId());
        m.put("reversalOf", e.getReversalOf());
        m.put("isReversal", e.getReversalOf() != null);
        m.put("remark", e.getRemark());
        m.put("createdAt", e.getCreatedAt());
        return m;
    }

    // ======================================================================
    // 写：追加 / 红冲（无 update、无 delete）
    // ======================================================================

    /** 追加一条流水。 */
    @Transactional
    public Map<String, Object> create(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        return view(append(p.getTenantId(), projectId, body, user.getUserId(), null, null));
    }

    /**
     * 红冲：新增一条反向流水冲销 {@code expenseId}（原行不改）。
     *
     * <p>两条负向约束：① 不能冲销一条**红冲行本身**；② 同一条原行不能被**重复红冲**。</p>
     */
    @Transactional
    public Map<String, Object> reverse(AuthUser user, Long projectId, Long expenseId, String reason) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);

        PmExpense target = expenseMapper.selectById(expenseId);
        if (target == null || !Objects.equals(target.getTenantId(), p.getTenantId())
                || !Objects.equals(target.getProjectId(), projectId)) {
            throw BizException.notFound("流水不存在");
        }
        if (target.getReversalOf() != null) {
            throw BizException.badRequest("不能红冲一条红冲记录");
        }
        Long already = expenseMapper.selectCount(new LambdaQueryWrapper<PmExpense>()
                .eq(PmExpense::getTenantId, p.getTenantId())
                .eq(PmExpense::getReversalOf, expenseId));
        if (already != null && already > 0) {
            throw new BizException(409, "该流水已被红冲，不能重复红冲");
        }

        Map<String, Object> body = new LinkedHashMap<>();
        // ★红字冲销语义：红冲行**方向与原行相同**、**金额取负**。
        // 为什么不是「方向翻转、金额取正」：汇总的每个方向桶是「按方向累加金额」，
        // 若翻转方向，被冲销的 OUT 仍留在支出桶里（支出不减），而冲销额却混进收入桶
        // ⇒「结余 = 预算 − 支出」根本回不去，用户会看到「冲了但钱没回来」。
        // 同方向负数入桶后自然抵消，支出/收入/结余三者同时回退。
        body.put("direction", target.getDirection());
        body.put("category", target.getCategory());
        body.put("amount", target.getAmount());
        body.put("occurredAt", LocalDate.now());
        body.put("allocRatio", target.getAllocRatio());
        body.put("remark", "红冲 #" + expenseId + (reason == null || reason.isBlank() ? "" : "：" + reason));
        PmExpense r = append(p.getTenantId(), projectId, body, user.getUserId(), expenseId, target.getAmount().negate());
        return view(r);
    }

    /** 落一行流水；{@code reversalOf} 非空即为红冲行（此时允许负数金额）。包内可见：合同确认（BR-09）也用它。 */
    PmExpense append(Long tenantId, Long projectId, Map<String, Object> body, Long actorId,
                     Long reversalOf, BigDecimal amountOverride) {
        String direction = str(body.get("direction"));
        if (!PmExpense.DIR_IN.equals(direction) && !PmExpense.DIR_OUT.equals(direction)) {
            throw BizException.badRequest("方向必须为 IN（收入）或 OUT（支出）");
        }
        String category = str(body.get("category"));
        if (categoryLabel(category) == null) {
            throw BizException.badRequest("未知费用分类：" + category);
        }
        BigDecimal amount = amountOverride != null ? amountOverride : decimal(body.get("amount"));
        if (amount == null) {
            throw BizException.badRequest("金额不能为空");
        }
        // 正常录入必须非负；红冲行允许负数（红字冲销的就地取负）
        if (reversalOf == null && amount.signum() < 0) {
            throw BizException.badRequest("金额必须为非负数");
        }

        PmExpense e = new PmExpense();
        e.setTenantId(tenantId);
        e.setProjectId(projectId);
        e.setDirection(direction);
        e.setCategory(category);
        e.setAmount(amount);
        e.setAllocRatio(decimal(body.get("allocRatio")));
        Object od = body.get("occurredAt");
        e.setOccurredAt(od == null || String.valueOf(od).isBlank() ? LocalDate.now() : LocalDate.parse(String.valueOf(od)));
        e.setContractPaymentId(asLong(body.get("contractPaymentId")));
        e.setVoucherFileId(asLong(body.get("voucherFileId")));
        e.setReversalOf(reversalOf);
        e.setRemark(str(body.get("remark")));
        e.setCreatedBy(actorId);
        e.setCreatedAt(LocalDateTime.now());
        expenseMapper.insert(e);
        return e;
    }

    private List<Map<String, Object>> categoryOptions() {
        List<Map<String, Object>> l = new ArrayList<>();
        l.add(Map.of("value", PmExpense.CAT_CONTRACT, "label", "合同款"));
        l.add(Map.of("value", PmExpense.CAT_LABOR, "label", "人工（人员费用）"));
        l.add(Map.of("value", PmExpense.CAT_PURCHASE, "label", "采购"));
        l.add(Map.of("value", PmExpense.CAT_TRAVEL, "label", "差旅"));
        l.add(Map.of("value", PmExpense.CAT_OTHER, "label", "其他"));
        return l;
    }

    private String categoryLabel(String c) {
        if (c == null) {
            return null;
        }
        return switch (c) {
            case PmExpense.CAT_CONTRACT -> "合同款";
            case PmExpense.CAT_LABOR -> "人工（人员费用）";
            case PmExpense.CAT_PURCHASE -> "采购";
            case PmExpense.CAT_TRAVEL -> "差旅";
            case PmExpense.CAT_OTHER -> "其他";
            default -> null;
        };
    }

    private boolean canWrite(AuthUser user, PmProject p) {
        return projectService.canManage(user, p) || PermissionCatalog.holds(user, PermissionCatalog.PM_BUDGET_MANAGE);
    }

    private void requireWrite(AuthUser user, PmProject p) {
        if (!canWrite(user, p)) {
            throw BizException.forbidden("仅项目负责人/项目经理、机构管理员及以上可维护经费流水");
        }
    }

    // ---- 工具 ----

    static String str(Object o) {
        return o == null ? "" : String.valueOf(o).trim();
    }

    static Long asLong(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        String s = String.valueOf(o).trim();
        return s.isEmpty() ? null : Long.parseLong(s);
    }

    static BigDecimal decimal(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof BigDecimal b) {
            return b.setScale(2, RoundingMode.HALF_UP);
        }
        if (o instanceof Number n) {
            return new BigDecimal(n.toString()).setScale(2, RoundingMode.HALF_UP);
        }
        String s = String.valueOf(o).trim();
        return s.isEmpty() ? null : new BigDecimal(s).setScale(2, RoundingMode.HALF_UP);
    }
}
