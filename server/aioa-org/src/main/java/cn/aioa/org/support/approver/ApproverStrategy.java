package cn.aioa.org.support.approver;

import java.util.List;

/**
 * 审批人解析策略 —— 四期「解析器策略化」（docs/23 §7 四期）。
 *
 * <p><b>它解决的问题</b>：改造前 {@code ApprovalFlowService} 用一个 switch 把
 * 「审批人类型 → 人」写死在一处，每种类型的求值口径（固定角色 / 部门负责人 / 指定人）
 * 混在同一个方法里。于是想加一种口径（如「按部门职务求值」）就要动主流程，
 * 且「一个节点可能对应<b>多个人</b>」这件事无处表达 —— 引擎只会给出一个人。</p>
 *
 * <p><b>策略化的两个收益</b>：</p>
 * <ol>
 *   <li>新增口径 = 新增一个策略类，主流程不动；</li>
 *   <li>策略返回<b>有序候选列表</b>（而非单值），把「多个人怎么用」交给
 *       {@code mode}（五期：single / parallel / grab）决定 —— 这与 O2OA
 *       把「处理人求值」和「处理模式」分成两件事是同一思路。</li>
 * </ol>
 *
 * <p><b>契约</b>：{@link #resolve} 必须<b>永不返回 null</b>；解析不到人时返回空列表，
 * 由引擎按「梯级缺位」口径顺延并写明原因（不静默兜底、不抛异常 —— 抛异常会让
 * 「部门暂不设负责人」这种合法状态变成提交失败）。</p>
 */
public interface ApproverStrategy {

    /** 本策略负责的审批人类型（对应 steps_json 的 {@code approver_type}）。 */
    String type();

    /**
     * 求值候选审批人。<b>有序</b>：第 0 个 = 单人模式（single）的默认人选。
     *
     * @return 不为 null；解析不到时为空列表
     */
    List<Candidate> resolve(Context ctx);

    /**
     * 一个候选审批人。
     *
     * @param userId       候选人 id
     * @param name         姓名快照（写任务时留痕，避免事后改名导致历史单据对不上）
     * @param approverType 该候选实际生效的类型（兜底改派时可能不同于请求类型）
     * @param dutyCode     职务码（仅职务型策略有值，用于节点显示「部门副职」）
     */
    record Candidate(Long userId, String name, String approverType, String dutyCode) {

        public static Candidate of(Long userId, String name, String approverType) {
            return new Candidate(userId, name, approverType, null);
        }
    }

    /**
     * 求值上下文 —— 策略所需的全部输入（不再让策略各自去查库拼参数）。
     *
     * @param tenantId               租户 id（<b>必填</b>：所有查人动作都必须租户内，防跨租户泄露）
     * @param institutionId          申请人所属机构（0 = 无机构）
     * @param departmentId           申请人所属部门（null / 0 = 未归属部门）
     * @param dutyCode               step 指定的职务码（仅职务型策略使用；null = 该类型的默认职务）
     * @param targetInstitutionId    UNIT_DUTY 显式指定的机构（null = 取申请人所属机构）
     * @param stepApproverId         step 里显式写死的审批人 id（仅 SPECIFIC 使用，优先于提交人指定）
     * @param specificApproverId     提交请求携带的指定审批人（SPECIFIC 的回退人选）
     * @param allowCrossDeptFallback 是否允许跨部门兜底（固定模板语义 true；申请人的上级链必须 false）
     */
    record Context(Long tenantId, Long institutionId, Long departmentId, String dutyCode,
                   Long targetInstitutionId, Long stepApproverId, Long specificApproverId,
                   boolean allowCrossDeptFallback) {
    }
}
