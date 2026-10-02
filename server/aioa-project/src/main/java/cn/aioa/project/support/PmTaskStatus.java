package cn.aioa.project.support;

import java.util.Map;
import java.util.Set;

/**
 * 任务状态机（BR-10）：{@code TODO → DOING → DONE}，旁路 {@code BLOCKED} / {@code CANCELED}。
 *
 * <p><b>{@link #DONE} 是终态、不可回退</b>：已完成的任务被改回「进行中」会污染所有
 * 「完成率 / 里程碑达成 / 交付统计」—— 这些数字都从任务状态推导，一旦可回退，
 * 历史统计就会随时间变化，里程碑「已达成」的结论也可能被事后推翻。</p>
 *
 * <p>{@link #CANCELED} 允许「重新打开」回到 {@link #TODO}：取消常因需求临时搁置，
 * 硬性终态会逼用户新建一条重复任务；而 DONE 没有这个语义需要（完成了就是完成了）。</p>
 *
 * <p>白名单是**唯一判定点**（{@link #canTransition}）：前端拦截非法拖拽、后端兜底，
 * 两处都调它，不各写一份 if。</p>
 */
public final class PmTaskStatus {

    public static final String TODO = "TODO";
    public static final String DOING = "DOING";
    public static final String BLOCKED = "BLOCKED";
    public static final String DONE = "DONE";
    public static final String CANCELED = "CANCELED";

    public static final Set<String> ALL = Set.of(TODO, DOING, BLOCKED, DONE, CANCELED);

    /** 状态 → 可迁移到的状态集合。 */
    private static final Map<String, Set<String>> TRANSITIONS = Map.of(
            TODO, Set.of(DOING, BLOCKED, CANCELED),
            DOING, Set.of(DONE, BLOCKED, CANCELED),
            BLOCKED, Set.of(TODO, DOING, CANCELED),
            DONE, Set.of(),
            CANCELED, Set.of(TODO));

    private static final Map<String, String> LABELS = Map.of(
            TODO, "待办",
            DOING, "进行中",
            BLOCKED, "阻塞",
            DONE, "已完成",
            CANCELED, "已取消");

    /** 优先级取值（前端下拉与后端校验共用）。 */
    public static final Set<String> PRIORITIES = Set.of("LOW", "MEDIUM", "HIGH", "URGENT");

    private PmTaskStatus() {
    }

    public static boolean isValid(String status) {
        return status != null && ALL.contains(status);
    }

    public static boolean isValidPriority(String priority) {
        return priority != null && PRIORITIES.contains(priority);
    }

    public static String label(String status) {
        return LABELS.getOrDefault(status, status);
    }

    /** 是否终态（DONE 不可回退）。 */
    public static boolean isTerminal(String status) {
        return DONE.equals(status);
    }

    /** 该迁移是否被允许。同态视为允许（幂等更新不报错）。 */
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
