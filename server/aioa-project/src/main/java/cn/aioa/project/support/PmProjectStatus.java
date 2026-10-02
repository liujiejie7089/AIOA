package cn.aioa.project.support;

import java.util.Map;
import java.util.Set;

/**
 * 项目状态机（docs/40 §3.3）。
 *
 * <pre>
 * DRAFT(草稿) → ACTIVE(进行中) → CLOSED(已结项)
 *                    ↘ SUSPENDED(暂停) ↗
 * 任意状态 → ARCHIVED(已归档，只读)
 * </pre>
 *
 * <p><b>只读终态</b>：{@link #CLOSED} / {@link #ARCHIVED} 不允许再建任务、加成员、改合同。
 * 该判定只有一处（{@link #isReadOnly}），不允许各 service 自己写
 * {@code if (status.equals("CLOSED") || ...)} —— 多了必然漏一处，
 * 而漏掉的那一处就是「结项后还能往项目里塞任务」这类静默错行为。</p>
 */
public final class PmProjectStatus {

    public static final String DRAFT = "DRAFT";
    public static final String ACTIVE = "ACTIVE";
    public static final String SUSPENDED = "SUSPENDED";
    public static final String CLOSED = "CLOSED";
    public static final String ARCHIVED = "ARCHIVED";

    public static final Set<String> ALL = Set.of(DRAFT, ACTIVE, SUSPENDED, CLOSED, ARCHIVED);

    /** 允许的目标状态迁移：key = 当前态，value = 可去的态。 */
    private static final Map<String, Set<String>> TRANSITIONS = Map.of(
            DRAFT, Set.of(ACTIVE, ARCHIVED),
            ACTIVE, Set.of(SUSPENDED, CLOSED, ARCHIVED),
            SUSPENDED, Set.of(ACTIVE, CLOSED, ARCHIVED),
            CLOSED, Set.of(ARCHIVED),
            ARCHIVED, Set.of());

    private PmProjectStatus() {
    }

    public static boolean isValid(String status) {
        return status != null && ALL.contains(status);
    }

    /** 只读终态：已结项 / 已归档，禁止再写入子对象。 */
    public static boolean isReadOnly(String status) {
        return CLOSED.equals(status) || ARCHIVED.equals(status);
    }

    /** 该迁移是否被允许（白名单）。同态视为允许（幂等改状态不报错）。 */
    public static boolean canTransition(String from, String to) {
        if (from == null || to == null) {
            return false;
        }
        if (from.equals(to)) {
            return true;
        }
        return TRANSITIONS.getOrDefault(from, Set.of()).contains(to);
    }
}
