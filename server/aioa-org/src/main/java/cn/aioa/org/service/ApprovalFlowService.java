package cn.aioa.org.service;

import cn.aioa.common.event.NotificationRequested;
import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.ApprovalFlowDef;
import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.ApprovalFlowDefMapper;
import cn.aioa.org.mapper.ApprovalTaskMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.approver.ApproverResolver;
import cn.aioa.org.support.approver.ApproverStrategy;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 多级审批流引擎（审批流程升级主交付）。
 *
 * <pre>
 * 提交单据（approval_order, PENDING）
 *   └─ 匹配 approval_flow_def → 展开 steps_json 为 N 条 approval_task(seq 升序)
 *        └─ 当前节点 = seq 最小的 PENDING 任务
 *             ├─ 通过 → 推进下一节点；末节点通过 → 单据 APPROVED + 触发回调
 *             ├─ 驳回 → 单据 REJECTED，其余任务 SKIPPED
 *             └─ 阈值跳级：天数 ≤ threshold_days 时该节点 SKIPPED（保留至少一个有效节点）
 * </pre>
 *
 * <h3>节点参数（steps_json 里每个 step 可带）</h3>
 * <table>
 *   <tr><th>参数</th><th>作用</th></tr>
 *   <tr><td>{@code approver_type}</td><td>审批人类型（DEPT_LEADER / DEPT_DUTY / UNIT_DUTY / ORG_ADMIN / TENANT_ADMIN / PLATFORM_ADMIN / SPECIFIC / APPLICANT_SUPERIOR）</td></tr>
 *   <tr><td>{@code duty_code}</td><td>仅 DEPT_DUTY / UNIT_DUTY：按哪个职务求值（缺省 = 部门正职 / 机构负责人）</td></tr>
 *   <tr><td>{@code institution_id}</td><td>仅 UNIT_DUTY：求值的目标机构（缺省 = 申请人所属机构；必须同租户）</td></tr>
 *   <tr><td>{@code levels}</td><td>仅 APPLICANT_SUPERIOR：向上几级。缺省 = 整条链（向后兼容）；1 = 只到直接上级</td></tr>
 *   <tr><td>{@code mode}</td><td>节点处理模式（五期）：{@code single}（缺省，单人）/ {@code parallel}（会签，全通过才推进）/ {@code grab}（抢占，任一人处理即完成）</td></tr>
 *   <tr><td>{@code when}</td><td>条件路由（五期）：{@code {"field":"days","op":"&lt;=","value":3}}；不满足则本节点 SKIPPED，用于按金额 / 天数分流</td></tr>
 *   <tr><td>{@code cc}</td><td>知会（抄送）对象类型清单，如 {@code ["ORG_ADMIN"]}。生成 task_role=CC 的任务，<b>不阻塞</b>流转，只进「抄送我的」</td></tr>
 *   <tr><td>{@code threshold_days}</td><td>跳级阈值</td></tr>
 * </table>
 *
 * <p><b>为何要有 {@code cc}</b>：一级审批（levels=1）把成员申请止于部门负责人后，机构管理员
 * 不再出现在链上。按 O2OA 的「待阅」把「要审批」与「要知晓」拆开 —— 审批要快，知情要全。</p>
 *
 * 兼容性：既有单级 {@code approval_order} 接口与 {@code ApprovalService} 完全不变，
 * 本引擎仅在 bizType 命中「配置了多级流程」时接管；未配置流程时按单节点 ORG_ADMIN 处理。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ApprovalFlowService {

    public static final String DEFAULT_APPROVER_TYPE = ApprovalTask.TYPE_ORG_ADMIN;

    /**
     * 申请主体：个人（一期行为，缺省）。
     *
     * <p>供 {@link PermissionGrantService} 复用（不新建枚举类，见 docs/26 §8 共享约定）。</p>
     */
    public static final String APPLICANT_USER = "USER";
    /**
     * 申请主体：部门（二期 E-01/E-04）—— 提交人即部门负责人，审批链从机构管理员起算。
     */
    public static final String APPLICANT_DEPARTMENT = "DEPARTMENT";

    private final ApprovalFlowDefMapper defMapper;
    private final ApprovalTaskMapper taskMapper;
    private final OrgInstitutionMapper institutionMapper;
    private final OrgMemberMapper memberMapper;
    private final OrgStatMapper statMapper;
    private final ObjectMapper objectMapper;
    private final AuditRecorder audit;
    private final ObjectProvider<ApprovalCallback> callbacks;
    /**
     * 审批人解析策略族（四期）。
     *
     * <p>引擎不再认识任何具体求值口径：类型 → 人的映射全部委托给策略族，
     * 引擎只负责「拿到有序候选之后怎么用」（单人 / 会签 / 抢占）与兜底提示。</p>
     */
    private final ApproverResolver approverResolver;
    private final ApplicationEventPublisher events;

    /** 提交请求（结构化，避免服务间传 Map 丢字段）。 */
    public record SubmitReq(String bizType, String title, String content, String formData,
                            Long institutionId, Long departmentId, Double days,
                            Long applicantUserId, String applicantName, Long specificApproverId,
                            // ↓ 二期新增（追加在末尾；缺省 null = 一期行为）
                            String applicantType, Long applicantDepartmentId) {
    }

    // ================================================================== 提交

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> submit(Long tenantId, AuthUser actor, SubmitReq req) {
        if (req.bizType() == null || req.bizType().isBlank()) {
            throw BizException.badRequest("bizType 不能为空");
        }
        Long institutionId = req.institutionId() == null ? 0L : req.institutionId();
        Long userId = req.applicantUserId() != null ? req.applicantUserId()
                : (actor == null ? 0L : actor.getUserId());
        String applicantName = req.applicantName() != null ? req.applicantName()
                : (actor == null ? "用户#" + userId : AuditRecorder.displayName(actor));

        Map<String, Object> order = new HashMap<>();
        order.put("tenantId", tenantId);
        order.put("userId", userId);
        order.put("applicantName", applicantName);
        // 二期主体字段：缺省（null）时 SQL 侧 COALESCE 成 'USER'，逐字等价一期。
        order.put("applicantType", req.applicantType());
        order.put("applicantDepartmentId", req.applicantDepartmentId());
        order.put("bizType", req.bizType());
        order.put("title", req.title());
        order.put("content", req.content());
        order.put("formData", req.formData());
        order.put("attachment", null);
        order.put("createdBy", userId);
        statMapper.insertApprovalOrder(order);
        Long orderId = ((Number) order.get("id")).longValue();

        ExpandResult expand = expandNodes(tenantId, institutionId, req);
        List<Node> nodes = expand.approve();
        if (nodes.isEmpty()) {
            throw BizException.badRequest("无法解析审批节点，请检查审批流定义（approval_flow_def）");
        }
        Long firstApprover = null;
        StringBuilder note = new StringBuilder();
        for (Node n : nodes) {
            ApprovalTask t = new ApprovalTask();
            t.setTenantId(tenantId);
            t.setInstitutionId(institutionId);
            t.setOrderId(orderId);
            // seq 由展开阶段决定，不再按写入顺序自增 —— 会签 / 抢占模式下
            // 一个节点会产生多条任务，它们必须**共用同一个 seq** 才成其为「一组」。
            t.setSeq(n.seq());
            t.setApproverType(n.approverType);
            t.setApproverId(n.approverId);
            t.setApproverName(n.approverName);
            t.setTaskRole(ApprovalTask.ROLE_APPROVE);
            t.setNodeMode(n.nodeMode());
            t.setNodeDuty(n.dutyCode());
            t.setStatus(n.skipReason == null ? ApprovalTask.PENDING : ApprovalTask.SKIPPED);
            t.setSkipReason(n.skipReason);
            t.setNote(n.fallbackNote);
            t.setCreatedAt(LocalDateTime.now());
            taskMapper.insert(t);
            if (t.getStatus().equals(ApprovalTask.PENDING) && firstApprover == null) {
                firstApprover = n.approverId;
            }
            if (n.fallbackNote != null) {
                note.append(n.fallbackNote).append("；");
            }
        }
        if (firstApprover == null) {
            throw BizException.badRequest("审批节点全部被跳过，无法进入审批（请检查 threshold_days / when 条件配置）");
        }
        // 知会（抄送）节点：状态为 CC 而非 PENDING —— **不阻塞**流转，只进「抄送我的」并推通知。
        // seq 取 900+ 与其审批序列明确区分（知会不占审批级次，nodeCount 也不含它们）。
        int ccSeq = 900;
        List<String> ccNames = new ArrayList<>();
        for (Node n : expand.cc()) {
            ccSeq++;
            ApprovalTask t = new ApprovalTask();
            t.setTenantId(tenantId);
            t.setInstitutionId(institutionId);
            t.setOrderId(orderId);
            t.setSeq(ccSeq);
            t.setApproverType(n.approverType);
            t.setApproverId(n.approverId);
            t.setApproverName(n.approverName);
            t.setTaskRole(ApprovalTask.ROLE_CC);
            t.setStatus(ApprovalTask.STATUS_CC);
            t.setNote("抄送知会：无需你审批，仅供知悉与督办");
            t.setCreatedAt(LocalDateTime.now());
            taskMapper.insert(t);
            ccNames.add(n.approverName);
            notify(n.approverId, tenantId, "抄送知会",
                    applicantName + " 提交了《" + (req.title() == null ? req.bizType() : req.title())
                            + "》，抄送给你知悉（无需审批）", orderId);
        }
        if (note.length() > 0) {
            statMapper.updateApprovalOrderStatus(orderId, "PENDING", null,
                    "提交时的流程提示：" + note);
        }
        notify(firstApprover, tenantId, "新审批待处理",
                applicantName + " 提交了《" + (req.title() == null ? req.bizType() : req.title())
                        + "》，待你审批", orderId);
        audit.record(tenantId, institutionId, actor, "WORKFLOW_SUBMIT", "APPROVAL_ORDER", orderId,
                "提交「" + req.bizType() + "」审批单（共 " + nodes.size() + " 级节点"
                        + (expand.cc().isEmpty() ? "" : "，知会 " + expand.cc().size() + " 人") + "）",
                null, Map.of("orderId", orderId, "nodes", nodes.size(), "cc", expand.cc().size()));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("orderId", orderId);
        out.put("status", "PENDING");
        // 「共 N 级」按**节点组**计（distinct seq）：会签 / 抢占会把一个节点展开成多条任务，
        // 若按任务条数计，一个三人会签节点会被报成「3 级」，与用户看到的流转路径不符。
        out.put("nodeCount", (int) nodes.stream().map(Node::seq).distinct().count());
        // 会签 / 抢占：一个节点对应多人时，把候选人数一并回报，前端可提示「需 N 人会签」
        out.put("taskCount", nodes.size());
        out.put("currentApproverId", firstApprover);
        // 二期主体：随回执下发，用户端/管理端据此渲染「部门申请」徽标（USER 时 applicantType='USER'）
        out.put("applicantType", req.applicantType() == null ? APPLICANT_USER : req.applicantType());
        out.put("applicantDepartmentId", req.applicantDepartmentId());
        // 「当前流转到谁」：提交回执直接给出审批人姓名，用户端无需再查一次
        out.put("currentApproverName", nameOf(firstApprover));
        // 知会（抄送）对象：不阻塞流转，仅用于「我提交的申请由谁知晓」的展示
        out.put("ccCount", expand.cc().size());
        out.put("ccNames", ccNames);
        out.put("timeline", timeline(orderId));
        return out;
    }

    /**
     * 展开后的一个审批节点（或其一个候选任务）。
     *
     * <p>{@code seq} 是<b>节点组</b>编号（写库 approval_task.seq）：单人模式下
     * 一个节点 = 一条任务；会签 / 抢占模式下一个节点 = 同 seq 的多条任务，
     * 它们共同构成「第 N 级」，推进判定也以组为单位。</p>
     *
     * @param nodeMode  处理模式（single / parallel / grab）—— 决定推进语义
     * @param dutyCode  职务码（仅职务型节点有值，用于显示「部门副职」而非笼统的「职务审批」）
     */
    private record Node(int seq, String approverType, Long approverId, String approverName,
                        String skipReason, String fallbackNote, String nodeMode, String dutyCode) {
    }

    /** 展开结果：审批节点（阻塞推进）+ 知会节点（不阻塞，对标 O2OA 的「待阅」）。 */
    private record ExpandResult(List<Node> approve, List<Node> cc) {
    }

    /** 上级梯级的展开结果：节点 + 「梯级缺位被迫顺延」的可见提示。 */
    private record Ladder(List<Node> nodes, String note) {
    }

    /** 条件路由的求值结果：命中的节点 + 回落默认分支时的提示。 */
    private record ConditionPlan(List<Map<String, Object>> steps, String note) {
    }

    /** 节点类型的中文标签（提示文案用）。 */
    private static String labelOf(String type) {
        if (type == null) {
            return "未知节点";
        }
        return switch (type) {
            case ApprovalTask.TYPE_DEPT_LEADER -> "部门负责人";
            case ApprovalTask.TYPE_DEPT_DUTY -> "部门职务";
            case ApprovalTask.TYPE_UNIT_DUTY -> "机构职务";
            case ApprovalTask.TYPE_ORG_ADMIN -> "企业管理员";
            case ApprovalTask.TYPE_TENANT_ADMIN -> "租户管理员";
            case ApprovalTask.TYPE_PLATFORM_ADMIN -> "平台管理员";
            default -> type;
        };
    }

    /**
     * 展开审批节点：条件路由 → 审批人解析（策略族）→ 阈值跳级 → 兜底；并解析知会对象。
     *
     * <p>四期把「审批人怎么求值」移交给 {@link ApproverResolver}；五期在此之上加了
     * 条件路由（{@code when}）与处理模式（{@code mode}）。本方法只做两件事：
     * <b>决定哪些节点生效</b>、<b>把每个节点展开成 1..K 条同组任务</b>。</p>
     */
    private ExpandResult expandNodes(Long tenantId, Long institutionId, SubmitReq req) {
        ApprovalFlowDef def = defMapper.selectOne(new LambdaQueryWrapper<ApprovalFlowDef>()
                .eq(ApprovalFlowDef::getTenantId, tenantId)
                .eq(ApprovalFlowDef::getInstitutionId, institutionId)
                .eq(ApprovalFlowDef::getBizType, req.bizType())
                .eq(ApprovalFlowDef::getStatus, "ACTIVE")
                .last("limit 1"));
        if (def == null && institutionId != 0L) {
            def = defMapper.selectOne(new LambdaQueryWrapper<ApprovalFlowDef>()
                    .eq(ApprovalFlowDef::getTenantId, tenantId)
                    .eq(ApprovalFlowDef::getInstitutionId, 0L)
                    .eq(ApprovalFlowDef::getBizType, req.bizType())
                    .eq(ApprovalFlowDef::getStatus, "ACTIVE")
                    .last("limit 1"));
        }
        List<Map<String, Object>> steps = def == null ? List.of() : parseSteps(def.getStepsJson());
        if (steps.isEmpty()) {
            steps = List.of(Map.of("seq", 1, "approver_type", DEFAULT_APPROVER_TYPE));
        }
        // 五期①条件路由：先按 when 把不命中的节点摘掉，再对剩下的求审批人。
        ConditionPlan plan = applyConditions(steps, req);
        steps = plan.steps();

        OrgInstitution inst = institutionId == 0L ? null : institutionMapper.selectById(institutionId);
        Long orgAdminId = inst == null ? null : inst.getAdminUserId();
        Long tenantAdminId = statMapper.selectFirstUserIdOfRole(tenantId, OrgGuard.ROLE_TENANT_ADMIN);
        Long platformAdminId = statMapper.selectFirstUserIdOfRole(0L, OrgGuard.ROLE_ADMIN);
        // 固定模板语义（如请假流的 DEPT_LEADER 节点）：允许跨部门兜底。
        Long deptLeaderId = approverResolver.deptLeader(tenantId, institutionId, req.departmentId(), true);
        // 上级链用的严格版：只认申请人「本部门」的负责人，不跨部门兜底（见 DeptLeaderApproverStrategy）
        Long deptLeaderStrict = approverResolver.deptLeader(tenantId, institutionId, req.departmentId(), false);

        List<Node> nodes = new ArrayList<>();
        boolean hasEffective = false;
        int index = 0;      // 节点序号（仅用于提示文案里的「第 N 级」）
        int nodeSeq = 0;    // 节点组编号（写库 seq）：与候选人数无关，一个 step 一个号
        for (Map<String, Object> step : steps) {
            String type = str(step.get("approver_type"), DEFAULT_APPROVER_TYPE);
            Double threshold = dbl(step.get("threshold_days"));
            Long specific = lng(step.get("approver_id"));
            // 五期②处理模式：一个节点解析出多个候选时的用法（single 只取第一个）
            String mode = normalizeMode(str(step.get("mode"), null));
            String dutyCode = str(step.get("duty_code"), null);

            // 「申请人的上一级」：一个 step 展开为上级链（按申请人组织层级递推 + 自审防护）。
            // 与其它类型的关键区别 —— 起点由申请人自身所处的层级决定，而不是所有人共用一条固定链。
            // levels 控制向上几级：缺省 = 整条链（向后兼容），levels=1 = 只到直接上级，
            // 这正是「普通用户申请 → 部门负责人一级审批」的落地方式。
            if (ApprovalTask.TYPE_APPLICANT_SUPERIOR.equals(type)) {
                Ladder ladder = superiorLadder(tenantId, institutionId, req, asInt(step.get("levels")),
                        deptLeaderStrict, orgAdminId, tenantAdminId, platformAdminId, mode);
                if (ladder.nodes().isEmpty()) {
                    throw BizException.badRequest("未找到可用的上级审批人：申请人在其组织层级之上没有可指派的审批人，"
                            + "请先配置部门负责人 / 企业管理员 / 租户管理员");
                }
                boolean first = true;
                for (Node n : ladder.nodes()) {
                    nodeSeq++;
                    index++;
                    hasEffective = true;
                    // 梯级缺位的提示挂在首个节点上：前端「流程提示」据此显示
                    // 「部门负责人未设置，已顺延到企业管理员」，避免兜底改派被伪装成正常一级审批。
                    nodes.add(withSeq(n, nodeSeq, first ? ladder.note() : n.fallbackNote()));
                    first = false;
                }
                continue;
            }

            index++;
            nodeSeq++;
            ApproverStrategy.Context ctx = new ApproverStrategy.Context(tenantId, institutionId,
                    req.departmentId(), dutyCode, lng(step.get("institution_id")), specific,
                    req.specificApproverId(), true);
            List<ApproverStrategy.Candidate> candidates = approverResolver.resolve(type, ctx);

            String effectiveType = type;
            String dutyOfNode = null;
            String fallback = null;
            List<ApproverStrategy.Candidate> picked = List.of();
            if (!candidates.isEmpty()) {
                picked = pickByMode(candidates, mode);
                effectiveType = picked.get(0).approverType() == null ? type : picked.get(0).approverType();
                if (isDutyTyped(type)) {
                    dutyOfNode = str(picked.get(0).dutyCode(), defaultDutyOf(type));
                }
            } else {
                fallback = missingNote(type, dutyCode, index);
            }

            // 兜底改派时，节点类型必须同步改成「实际生效的类型」。
            // 历史缺陷：改派后 approver_type 仍保留原值，前端会把机构管理员显示成
            // 「部门负责人」，出现「节点名与审批人对不上」。
            if (picked.isEmpty() && !ApprovalTask.TYPE_ORG_ADMIN.equals(type)) {
                Long byFallback = orgAdminId != null ? orgAdminId
                        : (tenantAdminId != null ? tenantAdminId
                        : (platformAdminId != null ? platformAdminId : null));
                if (orgAdminId != null) {
                    effectiveType = ApprovalTask.TYPE_ORG_ADMIN;
                } else if (tenantAdminId != null) {
                    effectiveType = ApprovalTask.TYPE_TENANT_ADMIN;
                } else if (platformAdminId != null) {
                    effectiveType = ApprovalTask.TYPE_PLATFORM_ADMIN;
                }
                if (byFallback != null) {
                    // 改派后节点不再是职务型节点：职务标记必须清掉，
                    // 否则流转路径会显示「部门副职 - 张三」而张三是机构管理员，口径又对不上。
                    picked = List.of(new ApproverStrategy.Candidate(byFallback, null, effectiveType, null));
                    dutyOfNode = null;
                    if (fallback == null) {
                        fallback = "第 " + index + " 级审批人未解析到，已改由机构管理员 / 租户管理员兜底";
                    }
                }
            }
            if (picked.isEmpty()) {
                throw BizException.badRequest("第 " + index + " 级节点无法解析审批人，请先在机构管理中指定企业管理员（FR-B2）");
            }

            String skipReason = null;
            if (threshold != null && hasEffective && req.days() != null && req.days() <= threshold) {
                skipReason = "申请天数 " + req.days() + " ≤ 阈值 " + threshold + "，按配置跳级";
            }
            if (skipReason == null) {
                hasEffective = true;
            }
            // 一个节点展开成 1..K 条**同 seq** 任务：K>1 只发生在 parallel / grab 模式下，
            // 它们共同构成「第 N 级」，推进判定以组为单位（见 decide）。
            for (ApproverStrategy.Candidate c : picked) {
                nodes.add(new Node(nodeSeq, effectiveType, c.userId(),
                        c.name() == null ? nameOf(c.userId()) : c.name(),
                        skipReason, fallback, mode, dutyOfNode));
            }
        }
        // 条件路由的回落提示与梯级缺位提示共用「流程提示」出口（挂在首节点）。
        if (plan.note() != null && !nodes.isEmpty()) {
            Node h = nodes.get(0);
            nodes.set(0, withSeq(h, h.seq(),
                    h.fallbackNote() == null ? plan.note() : plan.note() + h.fallbackNote()));
        }

        List<Node> ccs = expandCcNodes(steps, req, deptLeaderId, orgAdminId, tenantAdminId, platformAdminId,
                nodes.stream().map(Node::approverId).filter(Objects::nonNull).toList());
        return new ExpandResult(nodes, ccs);
    }

    /** 复制一个节点并换掉 seq / 提示（展开阶段用它给节点组编号、给首节点挂提示）。 */
    private static Node withSeq(Node n, int seq, String fallbackNote) {
        return new Node(seq, n.approverType(), n.approverId(), n.approverName(),
                n.skipReason(), fallbackNote, n.nodeMode(), n.dutyCode());
    }

    /** 处理模式归一化：缺省 / 空串 = single；不认识的值<b>保底为 single</b> 并留日志。 */
    private static String normalizeMode(String raw) {
        if (raw == null || raw.isBlank()) {
            return ApprovalTask.MODE_SINGLE;
        }
        String m = raw.trim().toLowerCase();
        return switch (m) {
            case ApprovalTask.MODE_PARALLEL -> ApprovalTask.MODE_PARALLEL;
            case ApprovalTask.MODE_GRAB -> ApprovalTask.MODE_GRAB;
            case ApprovalTask.MODE_SINGLE -> ApprovalTask.MODE_SINGLE;
            default -> {
                log.warn("未知的节点处理模式「{}」，已按 single 处理（可用：single / parallel / grab）", raw);
                yield ApprovalTask.MODE_SINGLE;
            }
        };
    }

    /** 按处理模式挑选实际要落库的候选：single 只取第 1 个，会签 / 抢占取全部。 */
    private static List<ApproverStrategy.Candidate> pickByMode(List<ApproverStrategy.Candidate> all,
                                                               String mode) {
        if (all.size() <= 1) {
            return List.copyOf(all);
        }
        return ApprovalTask.MODE_SINGLE.equals(mode) ? List.of(all.get(0)) : List.copyOf(all);
    }

    /** 是否为「职务型」节点（决定要不要记录 node_duty / 显示职务名）。 */
    private static boolean isDutyTyped(String type) {
        return ApprovalTask.TYPE_DEPT_DUTY.equals(type) || ApprovalTask.TYPE_UNIT_DUTY.equals(type);
    }

    /** 职务型节点未指定 duty_code 时的默认职务。 */
    private static String defaultDutyOf(String type) {
        return ApprovalTask.TYPE_UNIT_DUTY.equals(type) ? OrgDuty.ORG_LEADER : OrgDuty.DEPT_PRINCIPAL;
    }

    /**
     * 「该节点解析不到审批人」的可见文案 —— 分工到具体口径。
     *
     * <p>返回 null 表示该类型没有专属文案，交给调用方的通用兜底提示
     * （与改造前的文案分工逐字保持一致，避免既有套件的文案断言漂移）。</p>
     */
    private static String missingNote(String type, String dutyCode, int index) {
        if (ApprovalTask.TYPE_DEPT_DUTY.equals(type)) {
            return "第 " + index + " 级「部门" + OrgDuty.nameOf(str(dutyCode, OrgDuty.DEPT_PRINCIPAL))
                    + "」未解析到（该部门无此职务的在职成员），已改由企业管理员审批";
        }
        if (ApprovalTask.TYPE_UNIT_DUTY.equals(type)) {
            return "第 " + index + " 级「机构" + OrgDuty.nameOf(str(dutyCode, OrgDuty.ORG_LEADER))
                    + "」未解析到（该机构无此职务的在职成员），已改由企业管理员审批";
        }
        if (ApprovalTask.TYPE_DEPT_LEADER.equals(type)) {
            return "第 " + index + " 级「部门负责人」未解析到（部门未设置负责人），已改由企业管理员审批";
        }
        if (ApprovalTask.TYPE_ORG_ADMIN.equals(type) || ApprovalTask.TYPE_TENANT_ADMIN.equals(type)
                || ApprovalTask.TYPE_PLATFORM_ADMIN.equals(type) || ApprovalTask.TYPE_SPECIFIC.equals(type)) {
            return null;
        }
        return "未知审批人类型「" + type + "」，已改由企业管理员审批";
    }

    // ------------------------------------------------------------------ 五期①：条件路由

    /**
     * 条件路由 —— 按节点的 {@code when} 决定它是否参与本次审批（五期）。
     *
     * <p>用途：按金额 / 天数分流，例如「≤3 天由部门负责人批，>3 天再加租户管理员」。</p>
     *
     * <p><b>不变量：永远至少留下一个生效节点</b>。若所有带条件的节点都不命中，
     * 依次回落：① 第一个<b>无</b>条件的节点（即配置里的默认分支）；
     * ② 末级节点。并写一条「流程提示」说明是回落来的 —— 否则「条件写错」
     * 会表现为「流程静默换了审批人」，比直接报错更难查。</p>
     */
    private ConditionPlan applyConditions(List<Map<String, Object>> steps, SubmitReq req) {
        List<Map<String, Object>> hit = new ArrayList<>();
        Map<String, Object> firstUnconditional = null;
        Map<String, Object> last = null;
        int idx = 0;
        int firstIdx = 0;
        int lastIdx = 0;
        for (Map<String, Object> step : steps) {
            idx++;
            last = step;
            lastIdx = idx;
            Object when = step.get("when");
            if (when == null) {
                if (firstUnconditional == null) {
                    firstUnconditional = step;
                    firstIdx = idx;
                }
                hit.add(step);
                continue;
            }
            if (matchCondition(when, req)) {
                hit.add(step);
            }
        }
        if (!hit.isEmpty()) {
            return new ConditionPlan(hit, null);
        }
        if (firstUnconditional != null) {
            return new ConditionPlan(List.of(firstUnconditional),
                    "条件路由：所有带条件的节点均不满足，已回落第 " + firstIdx + " 级无条件节点；");
        }
        return new ConditionPlan(last == null ? List.of() : List.of(last),
                "条件路由：全部节点条件均不满足且无默认分支，已按末级节点（第 " + lastIdx + " 级）处理；");
    }

    /**
     * 单个条件求值。
     *
     * <p>形态不对（不是对象）或 {@code field} 缺失时<b>返回 true 即不拦截</b> ——
     * 审批场景下「宁可多审一级，不可漏审一级」，配置写坏不该导致节点被静默摘掉。</p>
     */
    private boolean matchCondition(Object when, SubmitReq req) {
        if (!(when instanceof Map<?, ?> m)) {
            return true;
        }
        Object f = m.get("field");
        String field = f == null ? null : String.valueOf(f).trim();
        String op = m.get("op") == null ? "==" : String.valueOf(m.get("op")).trim();
        Object expected = m.get("value");
        if (field == null || field.isEmpty()) {
            return true;
        }
        Object actual = fieldValue(field, req);
        if (actual == null) {
            // 字段缺失 → 条件不成立（如「金额 > 10000」在无金额的业务里不适用）
            return false;
        }
        return compare(actual, op, expected);
    }

    /** 条件取值：先看请求内置字段，再回落业务表单 formData 的同名字段。 */
    private Object fieldValue(String field, SubmitReq req) {
        switch (field) {
            case "days" -> {
                if (req.days() != null) {
                    return req.days();
                }
            }
            case "bizType" -> {
                return req.bizType();
            }
            case "departmentId" -> {
                return req.departmentId();
            }
            case "institutionId" -> {
                return req.institutionId();
            }
            case "applicantType" -> {
                return req.applicantType() == null ? APPLICANT_USER : req.applicantType();
            }
            case "applicantUserId" -> {
                return req.applicantUserId();
            }
            default -> {
                // 其余字段一律查业务表单（如 quota 扩容的 tokens、请假的 leaveTypeCode）
            }
        }
        String fd = req.formData();
        if (fd == null || fd.isBlank()) {
            return null;
        }
        try {
            JsonNode n = objectMapper.readTree(fd).get(field);
            if (n == null || n.isNull()) {
                return null;
            }
            return n.isNumber() ? (Object) n.asDouble() : (Object) n.asText();
        } catch (Exception e) {
            log.warn("解析 formData 取条件字段「{}」失败：{}", field, e.getMessage());
            return null;
        }
    }

    /**
     * 条件比较：两侧都能解析为数字 → 数值比较；否则按字符串比较（排序类按字典序）。
     *
     * <p>不认识的运算符<b>返回 true</b>（保留节点）并记日志 —— 与
     * {@link #matchCondition} 同一原则：配置写坏不该让审批级次被静默摘掉。</p>
     */
    private boolean compare(Object actual, String op, Object expected) {
        Double a = toDouble(actual);
        Double b = toDouble(expected);
        if (a != null && b != null) {
            return switch (op) {
                case "<" -> a < b;
                case "<=" -> a <= b;
                case ">" -> a > b;
                case ">=" -> a >= b;
                case "==", "=" -> a.doubleValue() == b.doubleValue();
                case "!=", "<>" -> a.doubleValue() != b.doubleValue();
                default -> keepUnknownOp(op);
            };
        }
        String sa = String.valueOf(actual);
        String sb = expected == null ? "" : String.valueOf(expected);
        return switch (op) {
            case "==", "=" -> sa.equals(sb);
            case "!=", "<>" -> !sa.equals(sb);
            case "<" -> sa.compareTo(sb) < 0;
            case "<=" -> sa.compareTo(sb) <= 0;
            case ">" -> sa.compareTo(sb) > 0;
            case ">=" -> sa.compareTo(sb) >= 0;
            default -> keepUnknownOp(op);
        };
    }

    private static boolean keepUnknownOp(String op) {
        log.warn("未知的条件运算符「{}」，已按「条件成立」处理（可用：< <= > >= == !=）", op);
        return true;
    }

    /** 宽松转数字：非数字返回 null（走字符串比较），不抛异常。 */
    private static Double toDouble(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * 展开知会（抄送）对象 —— 对标 O2OA 的「待阅」：不需要审批但要知晓的人。
     *
     * <p>一级审批把成员申请止于部门负责人后，机构管理员不再出现在链上（V39 曾因此把链拉长，
     * 代价是所有人都得等两级）。改用知会：<b>审批要快，知情要全</b>。</p>
     *
     * <p>三重过滤：① 该类型解析不到人（如未设部门负责人）→ 无抄送对象；
     * ② 不抄送申请人自己；③ 已经是审批人的不再重复抄送（否则同一人既审批又「被知会」）。</p>
     */
    private List<Node> expandCcNodes(List<Map<String, Object>> steps, SubmitReq req,
                                    Long deptLeaderId, Long orgAdminId, Long tenantAdminId, Long platformAdminId,
                                    List<Long> approverIds) {
        List<Node> out = new ArrayList<>();
        // 同类型只解析一次（避免「五个节点都配了 ORG_ADMIN」生成五条重复知会）；
        // 指定人（C-11）按人 id 去重 —— 两个节点指定同一个人也只知会一次。
        Set<String> seenTypes = new LinkedHashSet<>();
        Set<Long> seenIds = new LinkedHashSet<>();
        for (Map<String, Object> step : steps) {
            Object raw = step.get("cc");
            if (!(raw instanceof List<?> list)) {
                continue;
            }
            for (Object item : list) {
                String type;
                Long explicitId = null;
                if (item instanceof Map<?, ?> m) {
                    // 对象形态（C-11）：{"type":"SPECIFIC","user_id":123} —— 指定具体人；
                    // {"type":"ORG_ADMIN"} 等价于字符串形态。
                    type = str(m.get("type"), null);
                    explicitId = lng(m.get("user_id"));
                } else {
                    type = str(item, null);
                }
                if (type == null) {
                    continue;
                }
                Long id;
                if (explicitId != null) {
                    id = explicitId;
                } else {
                    if (!seenTypes.add(type)) {
                        continue;
                    }
                    id = switch (type) {
                        case ApprovalTask.TYPE_DEPT_LEADER -> deptLeaderId;
                        case ApprovalTask.TYPE_ORG_ADMIN -> orgAdminId;
                        case ApprovalTask.TYPE_TENANT_ADMIN -> tenantAdminId;
                        case ApprovalTask.TYPE_PLATFORM_ADMIN -> platformAdminId;
                        default -> null;
                    };
                }
                if (id == null) {
                    continue;
                }
                if (req.applicantUserId() != null && req.applicantUserId().equals(id)) {
                    continue;
                }
                if (approverIds.contains(id)) {
                    continue;
                }
                if (!seenIds.add(id)) {
                    continue;
                }
                out.add(new Node(0, type, id, nameOf(id), null, null, ApprovalTask.MODE_SINGLE, null));
            }
        }
        return out;
    }

    /**
     * 展开「申请人的上级链」：部门负责人 → 机构管理员 → 租户管理员 → 平台管理员。
     *
     * <p>与固定模板的本质区别：<b>起点由申请人自身所处的层级决定</b> ——</p>
     * <ul>
     *   <li>普通成员：从部门负责人起，四级俱全；</li>
     *   <li>部门负责人：从机构管理员起（自己不能审自己，也不该被下级审）；</li>
     *   <li>机构管理员：从租户管理员起；</li>
     *   <li>租户管理员：从平台管理员起（租户内已无上级）。</li>
     * </ul>
     *
     * <p><b>levels（向上几级）</b>：缺省 / ≤0 = 整条链（改造前行为，向后兼容）；
     * {@code levels=1} = 只取第一个有效梯级 —— 用户要求「普通用户申请权限由部门负责人
     * 一级审批即可」即由此实现，且对更高层级申请人自然退化为「直接上级」：</p>
     *
     * <pre>
     * 普通成员   levels=1 → 部门负责人
     * 部门负责人 levels=1 → 企业管理员
     * 企业管理员 levels=1 → 租户管理员
     * 租户管理员 levels=1 → 平台管理员
     * </pre>
     *
     * <p>三重过滤：① 该级没人可指派（如部门未设负责人）→ 跳过；
     * ② <b>自审防护</b>：审批人 == 申请人 → 跳过；③ 同一人兼任多级 → 只保留一次。</p>
     *
     * <p><b>梯级缺位不静默兜底</b>：限定了 levels 时，若本应命中的那一级为空而被迫顺延，
     * 会在 note 里写明「哪一级缺位、顺延到哪一级」。否则「部门负责人未配」会伪装成
     * 「部门负责人已审批」，把配置缺陷藏起来（V39 实测过这个陷阱）。</p>
     */
    private Ladder superiorLadder(Long tenantId, Long institutionId, SubmitReq req, Integer levels,
                                  Long deptLeaderId, Long orgAdminId, Long tenantAdminId, Long platformAdminId,
                                  String nodeMode) {
        Long applicant = req.applicantUserId();

        // seq 此处留 0：梯级的级次由 expandNodes 按顺序赋值（一个梯级 = 一个节点组）。
        List<Node> rungs = new ArrayList<>();
        rungs.add(new Node(0, ApprovalTask.TYPE_DEPT_LEADER, deptLeaderId, nameOf(deptLeaderId),
                null, null, nodeMode, OrgDuty.DEPT_PRINCIPAL));
        rungs.add(new Node(0, ApprovalTask.TYPE_ORG_ADMIN, orgAdminId, nameOf(orgAdminId),
                null, null, nodeMode, null));
        rungs.add(new Node(0, ApprovalTask.TYPE_TENANT_ADMIN, tenantAdminId, nameOf(tenantAdminId),
                null, null, nodeMode, null));
        rungs.add(new Node(0, ApprovalTask.TYPE_PLATFORM_ADMIN, platformAdminId, nameOf(platformAdminId),
                null, null, nodeMode, null));

        int start = 0;
        if (APPLICANT_DEPARTMENT.equals(req.applicantType())) {
            // 部门名义申请：首节点 = 该部门所属机构（机构管理员）。
            // 提交人本人就是部门正职，若从 DEPT_LEADER 起会「自己审自己」——
            // 故起点直接锚定到机构管理员，自审防护仍在下方循环对每一级生效（E-04/D-2）。
            start = 1;
        } else if (applicant != null && applicant.equals(tenantAdminId)) {
            start = 3;
        } else if (applicant != null && applicant.equals(orgAdminId)) {
            start = 2;
        } else if (applicant != null && applicant.equals(deptLeaderId)) {
            start = 1;
        }

        boolean whole = levels == null || levels <= 0;
        int need = whole ? Integer.MAX_VALUE : levels;

        List<Node> out = new ArrayList<>();
        StringBuilder note = new StringBuilder();
        for (int i = start; i < rungs.size() && out.size() < need; i++) {
            Node r = rungs.get(i);
            if (r.approverId == null) {
                if (!whole) {
                    note.append("第 ").append(i + 1).append(" 级「").append(labelOf(r.approverType))
                            .append("」未解析到（该部门未设置负责人），已顺延到下一级；");
                }
                continue;
            }
            if (applicant != null && applicant.equals(r.approverId)) {
                // 自审防护可见化（D-2/A2-2）：提交人若同时是机构管理员，则该级被跳过并顺延，
                // 仅当 levels 限定时写明原因（与既有 note 口径一致，整链时不写以免刷屏）。
                if (!whole) {
                    note.append("第 ").append(i + 1).append(" 级「").append(labelOf(r.approverType))
                            .append("」为提交人本人，按自审防护跳过，已顺延到下一级；");
                }
                continue;
            }
            boolean dup = out.stream().anyMatch(x -> r.approverId.equals(x.approverId));
            if (dup) {
                continue;
            }
            out.add(r);
        }
        return new Ladder(out, note.length() == 0 ? null : note.toString());
    }

    private List<Map<String, Object>> parseSteps(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            JsonNode node = objectMapper.readTree(json);
            if (!node.isArray()) {
                return List.of();
            }
            List<Map<String, Object>> out = new ArrayList<>();
            for (JsonNode n : node) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("seq", n.has("seq") ? n.get("seq").asInt() : out.size() + 1);
                m.put("approver_type", n.has("approver_type") ? n.get("approver_type").asText() : null);
                m.put("approver_id", n.has("approver_id") && !n.get("approver_id").isNull()
                        ? n.get("approver_id").asLong() : null);
                m.put("threshold_days", n.has("threshold_days") && !n.get("threshold_days").isNull()
                        ? n.get("threshold_days").asDouble() : null);
                // levels：仅对 APPLICANT_SUPERIOR 有意义 —— 向上几级；缺省 = 整条链（向后兼容）
                m.put("levels", n.has("levels") && !n.get("levels").isNull() ? n.get("levels").asInt() : null);
                // 四期：职务型节点的参数
                m.put("duty_code", n.hasNonNull("duty_code") ? n.get("duty_code").asText().trim() : null);
                m.put("institution_id", n.has("institution_id") && !n.get("institution_id").isNull()
                        ? n.get("institution_id").asLong() : null);
                // 五期②：处理模式（single / parallel / grab）
                m.put("mode", n.hasNonNull("mode") ? n.get("mode").asText().trim() : null);
                // 五期①：条件路由 —— {"field":"days","op":"<=","value":3}
                m.put("when", parseWhen(n.get("when")));
                // cc：知会（抄送）对象清单 —— 不阻塞流转，只进「抄送我的」。
                // 支持两种形态：字符串（角色类型，如 "ORG_ADMIN"）与对象（指定人 C-11，
                // 如 {"type":"SPECIFIC","user_id":123}）。两者可混用。
                List<Object> cc = new ArrayList<>();
                if (n.has("cc") && n.get("cc").isArray()) {
                    for (JsonNode c : n.get("cc")) {
                        if (c.isObject()) {
                            if (!c.hasNonNull("type")) {
                                continue;
                            }
                            Map<String, Object> o = new LinkedHashMap<>();
                            o.put("type", c.get("type").asText().trim());
                            o.put("user_id", c.hasNonNull("user_id") ? c.get("user_id").asLong() : null);
                            if (o.get("type") == null || String.valueOf(o.get("type")).isBlank()) {
                                continue;
                            }
                            cc.add(o);
                        } else {
                            String s = c.asText(null);
                            if (s != null && !s.isBlank()) {
                                cc.add(s.trim());
                            }
                        }
                    }
                }
                m.put("cc", cc);
                out.add(m);
            }
            out.sort((a, b) -> Integer.compare((int) lng0(a.get("seq")), (int) lng0(b.get("seq"))));
            return out;
        } catch (Exception e) {
            log.warn("parse steps_json failed: {}", e.getMessage());
            return List.of();
        }
    }

    /**
     * 解析条件路由的 {@code when} 对象。
     *
     * <p>形态不合法（不是对象 / 缺 {@code field}）时返回 null，等价于「无条件下」——
     * 即该节点照常参与审批。这是刻意的<b>失败方向选择</b>：配置写坏时宁可多审一级，
     * 也不要静默把审批节点摘掉（那会让单据在无人察觉的情况下少一道关）。</p>
     */
    private static Map<String, Object> parseWhen(JsonNode w) {
        if (w == null || w.isNull() || !w.isObject() || !w.hasNonNull("field")) {
            return null;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("field", w.get("field").asText().trim());
        m.put("op", w.hasNonNull("op") ? w.get("op").asText().trim() : "==");
        JsonNode v = w.get("value");
        if (v == null || v.isNull()) {
            m.put("value", null);
        } else if (v.isNumber()) {
            m.put("value", v.asDouble());
        } else if (v.isBoolean()) {
            m.put("value", v.asBoolean());
        } else {
            m.put("value", v.asText());
        }
        return m;
    }

    // ================================================================== 待办 / 我的申请 / 轨迹

    /** 待我审批：我是当前节点审批人且单据仍未决（不含知会条目）。 */
    public List<Map<String, Object>> todo(AuthUser actor) {
        List<ApprovalTask> mine = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getApproverId, actor.getUserId())
                .eq(ApprovalTask::getTaskRole, ApprovalTask.ROLE_APPROVE)
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)
                .orderByAsc(ApprovalTask::getOrderId));
        List<Map<String, Object>> out = new ArrayList<>();
        for (ApprovalTask t : mine) {
            if (!isCurrentNode(t)) {
                continue;
            }
            Map<String, Object> order = statMapper.selectApprovalOrder(t.getOrderId());
            if (order == null || !"PENDING".equals(order.get("status"))) {
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>(order);
            m.put("taskId", t.getId());
            m.put("seq", t.getSeq());
            m.put("approverType", t.getApproverType());
            m.put("approverName", displayApprover(t.getApproverName(), t.getApproverId()));
            m.put("taskNote", t.getNote());
            m.put("totalNodes", statMapper.countTasksOfOrder(t.getOrderId()));
            // 流转路径：前端据此渲染「当前流转到谁 / 各节点由谁审核、状态与时间」
            m.put("timeline", timeline(t.getOrderId()));
            m.put("currentSeq", t.getSeq());
            out.add(m);
        }
        return out;
    }

    /**
     * 我发起的审批（全业务类型：请假 / 额度扩容 / 成果 / 公文…）。
     *
     * <p>带全字段（form_data / attachment）与流转路径：用户端「我的申请」要回显表单、
     * 附件，并展示单据当前流转到哪个节点、各节点由谁审核。</p>
     */
    public List<Map<String, Object>> mine(AuthUser actor) {
        Long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();
        List<Map<String, Object>> rows = statMapper.selectApprovalOrdersOfUser(tenantId, actor.getUserId());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            Object idObj = r.get("id");
            if (!(idObj instanceof Number n)) {
                out.add(r);
                continue;
            }
            long orderId = n.longValue();
            Map<String, Object> m = new LinkedHashMap<>(r);
            m.put("mine", true);
            m.put("creatorName", r.get("applicantName"));
            m.put("totalNodes", statMapper.countTasksOfOrder(orderId));
            m.put("timeline", timeline(orderId));
            Map<String, Object> cur = statMapper.selectCurrentTaskOfOrder(orderId);
            if (cur != null) {
                m.put("currentSeq", cur.get("seq"));
                m.put("currentApproverName", displayApprover(
                        (String) cur.get("approverName"), lng(cur.get("approverId"))));
                m.put("currentApproverType", cur.get("approverType"));
            }
            out.add(m);
        }
        return out;
    }

    /**
     * 「本部门名义发起的申请」（E-10）—— 部门成员的只读可见性。
     *
     * <p>二期让部门能以部门名义发起审批，但那时只有提交人（部门正职）与审批人看得到它。
     * 一个以部门名义提交的申请，部门成员却看不到 —— 这与「部门名义」的含义不符。
     * 本方法补上这个视角。</p>
     *
     * <p><b>为什么单开一个范围而不是并进「我的申请」</b>：{@code /workflow/mine} 的长度
     * 与「我的数据 · 我的申请」这个统计口径是同源的（既有套件有一致性断言），
     * 往其中混入「部门申请」会让统计数字与实际含义脱节。分开后个人视角保持纯净，
     * 部门视角可以被独立计数与解释。</p>
     *
     * <p><b>只读</b>：返回行带 {@code readonly=true}。成员能看见本部门提过什么、
     * 卡在谁那里，但不能替部门决策 —— 决策权限仍属被指派的审批人。</p>
     *
     * @return 本部门名义发起的单据（新到旧，上限 200）；无部门归属时为空列表（非 403）
     */
    public List<Map<String, Object>> deptSubjectOrders(AuthUser actor) {
        Long deptId = actor == null ? null : actor.getDepartmentId();
        if (deptId == null || deptId <= 0L) {
            // 无部门归属（平台 / 租户管理员，或未挂部门的账号）→ 没有「本部门」可言。
            // 刻意不返回 403：这不是越权，而是「这个视角对你没有内容」，与 todo / cc 的空态一致。
            return List.of();
        }
        Long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();
        List<Map<String, Object>> rows = statMapper.selectDeptSubjectOrdersOfDept(tenantId, deptId);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            Long orderId = lng(r.get("id"));
            if (orderId == null) {
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>(r);
            // mine 按真实提交人判定：部门正职自己既是提交人也是部门成员，
            // 对他而言这一单确实「是我的申请」，前端据此决定是否显示「部门申请」徽标。
            m.put("mine", actor.getUserId() != null && actor.getUserId().equals(lng(r.get("userId"))));
            m.put("deptSubject", true);
            m.put("readonly", true);
            m.put("creatorName", r.get("applicantName"));
            m.put("totalNodes", statMapper.countTasksOfOrder(orderId));
            m.put("timeline", timeline(orderId));
            Map<String, Object> cur = statMapper.selectCurrentTaskOfOrder(orderId);
            if (cur != null) {
                m.put("currentSeq", cur.get("seq"));
                m.put("currentApproverName", displayApprover(
                        (String) cur.get("approverName"), lng(cur.get("approverId"))));
                m.put("currentApproverType", cur.get("approverType"));
            }
            out.add(m);
        }
        return out;
    }

    /**
     * 「抄送我的」—— 知会 / 待阅清单（对标 O2OA 的「待阅」）。
     *
     * <p>与「待我处理」<b>完全分账</b>：知会不阻塞流转、不占待办红点，只做知悉与督办。
     * 一级审批（levels=1）下机构管理员不再位于审批链上，正是靠这里「可见」。</p>
     *
     * <p>返回行的 {@code id} 取单据 id（而非任务 id），使前端可与「待我处理 / 我的申请」
     * 复用同一套单据卡片渲染。</p>
     */
    public List<Map<String, Object>> cc(AuthUser actor) {
        List<Map<String, Object>> rows = statMapper.selectCcTasksOfUser(actor.getUserId());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            Map<String, Object> m = new LinkedHashMap<>(r);
            Long orderId = lng(r.get("orderId"));
            m.put("id", orderId);
            m.put("taskId", lng(r.get("taskId")));
            m.put("cc", true);
            m.put("creatorName", r.get("applicantName"));
            m.put("taskNote", "抄送知会：无需你审批，仅供知悉与督办");
            m.put("totalNodes", orderId == null ? 0L : statMapper.countTasksOfOrder(orderId));
            // 三期待阅已读态（C-05）：已读条目仍在列表，仅 read=true / readAt 有值（可回查）。
            Object readAt = r.get("readAt");
            m.put("read", readAt != null);
            m.put("readAt", readAt == null ? null : String.valueOf(readAt));
            // 抄送人要看的是「这单现在流转到谁、我为什么要知道它」——
            // 不给流转路径，机构管理员就只能看到一行摘要，谈不上「可督办」。
            m.put("timeline", orderId == null ? List.of() : timeline(orderId));
            out.add(m);
        }
        return out;
    }

    /**
     * 标记知会（抄送）条目为已读 —— 三期 C-04/C-09。
     *
     * <p>语义：知会「点开即已读」，降噪优先，但条目仍可回查（{@link #cc}）。</p>
     * <ul>
     *   <li>条目不存在 / 非本人 → <b>404</b>（不泄露存在性，跨人不泄露）；</li>
     *   <li>{@code task_role='APPROVE'} → 业务错误（审批任务无需标记已读）；</li>
     *   <li>幂等：{@code cc_read_at} 仅在未读时写入一次，重复调用时间<b>不倒退</b>；</li>
     *   <li>联动：同步置该单推给本人（{@code ref_id=orderId}）的站内通知已读（C-09）。</li>
     * </ul>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> markCcRead(Long taskId, AuthUser actor) {
        Long uid = actor == null ? null : actor.getUserId();
        Map<String, Object> t = statMapper.selectCcTask(taskId);
        if (t == null) {
            throw BizException.notFound("知会条目不存在");
        }
        String role = t.get("taskRole") == null ? null : String.valueOf(t.get("taskRole"));
        if (!ApprovalTask.ROLE_CC.equals(role)) {
            throw BizException.badRequest("该条目为审批任务，无需标记已读");
        }
        Long approverId = lng(t.get("approverId"));
        if (approverId == null || uid == null || !approverId.equals(uid)) {
            throw BizException.notFound("知会条目不存在");
        }
        Long orderId = lng(t.get("orderId"));
        // 截断到微秒：DB 列为 DATETIME(6)，若用纳秒会在写库时被四舍五入，
        // 导致「首次返回值 ≠ 回读值」而破坏幂等（重复标记 readAt 看似漂移）。
        LocalDateTime now = LocalDateTime.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        LocalDateTime readAt = toLocalDateTime(t.get("readAt"));
        if (readAt == null) {
            statMapper.markCcRead(taskId, now);
            readAt = now;
        }
        // C-09：点开知会 → 联动置该单推给本人的通知已读
        if (orderId != null) {
            statMapper.markNotificationsReadOfOrder(uid, orderId);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("taskId", taskId);
        out.put("orderId", orderId);
        out.put("read", true);
        out.put("readAt", readAt == null ? null : readAt.toString());
        out.put("ccUnread", statMapper.countMyUnreadCcTasks(uid));
        return out;
    }

    /** 兼容 MySQL DATETIME 的多种 JDBC 映射（LocalDateTime / Timestamp / Date）。 */
    private static LocalDateTime toLocalDateTime(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof LocalDateTime ldt) {
            return ldt;
        }
        if (v instanceof java.sql.Timestamp ts) {
            return ts.toLocalDateTime();
        }
        if (v instanceof java.util.Date d) {
            return LocalDateTime.ofInstant(d.toInstant(), java.time.ZoneId.systemDefault());
        }
        try {
            return LocalDateTime.parse(String.valueOf(v).replace(' ', 'T'));
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 流转路径（各节点的审批人、状态与时间）。
     *
     * <p>四期后额外带出 {@code nodeMode}（处理模式）与 {@code dutyName}（职务中文名）——
     * 前端据此把「部门副职」这类职务型节点显示成人能看懂的名字，
     * 并把会签 / 抢占节点标注出来（否则同 seq 的多条任务看起来像重复数据）。
     * 职务名取自租户职务字典，仅当存在职务型节点时才多查一次库。</p>
     */
    public List<Map<String, Object>> timeline(Long orderId) {
        List<Map<String, Object>> rows = statMapper.selectTasksOfOrder(orderId);
        // 收集本单用到的职务码，一次性取中文名（字典名可被租户自定义，故不硬编码在前端）
        Set<String> dutyCodes = new LinkedHashSet<>();
        Long tenantId = null;
        for (Map<String, Object> r : rows) {
            if (r.get("nodeDuty") != null) {
                dutyCodes.add(String.valueOf(r.get("nodeDuty")));
            }
            if (tenantId == null && r.get("tenantId") != null) {
                tenantId = lng(r.get("tenantId"));
            }
        }
        Map<String, String> dutyLabels = dutyCodes.isEmpty() ? Map.of()
                : approverResolver.dutyLabels(tenantId, dutyCodes);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("taskId", lng(r.get("id")));
            m.put("seq", r.get("seq"));
            m.put("approverType", r.get("approverType"));
            m.put("approverId", lng(r.get("approverId")));
            m.put("approverName", displayApprover((String) r.get("approverName"), lng(r.get("approverId"))));
            String mode = r.get("nodeMode") == null ? ApprovalTask.MODE_SINGLE : String.valueOf(r.get("nodeMode"));
            m.put("nodeMode", mode);
            String duty = r.get("nodeDuty") == null ? null : String.valueOf(r.get("nodeDuty"));
            m.put("nodeDuty", duty);
            m.put("dutyName", duty == null ? null : dutyLabels.getOrDefault(duty, OrgDuty.nameOf(duty)));
            m.put("status", r.get("status"));
            m.put("note", r.get("note"));
            m.put("skipReason", r.get("skipReason"));
            Object decidedAt = r.get("decidedAt");
            m.put("decidedAt", decidedAt == null ? null : String.valueOf(decidedAt));
            out.add(m);
        }
        return out;
    }

    /** 审批人显示名：任务上已快照则直接用，否则回查 sys_user，最后退化为「用户#id」。 */
    private String displayApprover(String snapshot, Long approverId) {
        if (snapshot != null && !snapshot.isBlank()) {
            return snapshot;
        }
        return nameOf(approverId);
    }

    // ================================================================== 决策

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> decide(Long taskId, AuthUser actor, boolean approve, String note) {
        ApprovalTask task = taskMapper.selectById(taskId);
        if (task == null) {
            throw BizException.notFound("审批任务不存在：" + taskId);
        }
        // 知会（抄送）节点不需要审批：它的意义是「知情」而非「点头」。
        // 若放行，抄送人一个操作就能让单据终态 —— 与「不阻塞流转」的语义直接冲突。
        //
        // 这一条必须排在「状态是否 PENDING」之前：知会任务的 status 就是 CC（非 PENDING），
        // 若先判状态，抄送人点审批只会收到「该审批节点已处理（CC）」——
        // 听起来像是有人已经批过了，而真实含义是「这本就不需要你批」。错误信息把人引向
        // 错误结论，比没有信息更糟，所以按语义优先级排序。
        if (ApprovalTask.ROLE_CC.equals(task.getTaskRole())) {
            throw BizException.badRequest("该条目为知会（抄送），无需审批；如需推进请由当前审批人处理");
        }
        if (!ApprovalTask.PENDING.equals(task.getStatus())) {
            throw BizException.badRequest("该审批节点已处理（" + task.getStatus() + "），不可重复审批");
        }
        if (task.getApproverId() != null && !task.getApproverId().equals(actor.getUserId())) {
            throw BizException.forbidden("该节点不由你审批（当前审批人 #" + task.getApproverId() + "）");
        }
        Map<String, Object> order = statMapper.selectApprovalOrder(task.getOrderId());
        if (order == null) {
            throw BizException.notFound("审批单不存在：" + task.getOrderId());
        }
        if (!"PENDING".equals(order.get("status"))) {
            throw BizException.badRequest("审批单已终态（" + order.get("status") + "）");
        }
        if (!isCurrentNode(task)) {
            throw BizException.badRequest("前序节点尚未通过，本节点暂不可审批");
        }

        task.setStatus(approve ? ApprovalTask.APPROVED : ApprovalTask.REJECTED);
        task.setNote(note);
        task.setDecidedAt(LocalDateTime.now());
        task.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(task);

        String approverName = AuditRecorder.displayName(actor);
        Long institutionId = task.getInstitutionId();
        boolean finalDone = false;
        // 会签未齐时的进度文案（其余场景为 null，走既有文案，保证既有断言不变）
        String progressNote = null;

        if (!approve) {
            // 驳回：其余 PENDING 节点全部 SKIPPED，单据 REJECTED
            List<ApprovalTask> rest = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                    .eq(ApprovalTask::getOrderId, task.getOrderId())
                    .eq(ApprovalTask::getStatus, ApprovalTask.PENDING));
            for (ApprovalTask r : rest) {
                ApprovalTask patch = new ApprovalTask();
                patch.setId(r.getId());
                patch.setStatus(ApprovalTask.SKIPPED);
                patch.setSkipReason("前序节点驳回，流程终止");
                patch.setUpdatedAt(LocalDateTime.now());
                taskMapper.updateById(patch);
            }
            statMapper.updateApprovalOrderStatus(task.getOrderId(), "REJECTED", approverName,
                    note == null ? "驳回" : note);
            fire(order, false);
        } else {
            // 五期②：推进判定以**节点组**（同 seq 的全部任务）为单位，而不是单条任务。
            //   single  —— 组内只有 1 条，本条通过即组完成；
            //   grab    —— 本条通过即组完成，其余同组任务置 SKIPPED（写明被谁抢先）；
            //   parallel—— 必须等组内全部通过，未齐则不推进（会签）。
            String mode = task.getNodeMode() == null ? ApprovalTask.MODE_SINGLE : task.getNodeMode();
            int inFlight = countPendingInGroup(task.getOrderId(), task.getSeq());
            if (inFlight > 0 && ApprovalTask.MODE_GRAB.equals(mode)) {
                int n = skipGroupSiblings(task.getOrderId(), task.getSeq(), task.getId(),
                        "抢占模式：该节点已由「" + approverName + "」处理，无需你重复操作");
                log.info("抢占节点完成：orderId={} seq={} 处理人={}，同组 {} 条任务已置 SKIPPED",
                        task.getOrderId(), task.getSeq(), approverName, n);
                inFlight = 0;
            }
            boolean nodeDone = inFlight == 0;
            if (!nodeDone) {
                // 会签未齐：节点不推进。提醒组内仍在等待的人「还有谁没处理」，
                // 否则多人会签容易互相等（都以为对方会先批）。
                int total = countGroup(task.getOrderId(), task.getSeq());
                int approved = countGroupByStatus(task.getOrderId(), task.getSeq(), ApprovalTask.APPROVED);
                for (ApprovalTask w : groupPending(task.getOrderId(), task.getSeq())) {
                    notify(w.getApproverId(), task.getTenantId(), "会签进行中",
                            "《" + order.get("title") + "》第 " + task.getSeq() + " 级为会签节点，"
                                    + "已通过 " + approved + " / " + total + " 人，仍待你处理",
                            task.getOrderId());
                }
                progressNote = "第 " + task.getSeq() + " 级会签进行中（已 " + approved + " / " + total + " 人通过）";
            }
            ApprovalTask next = nodeDone ? nextPending(task.getOrderId(), task.getSeq()) : null;
            if (!nodeDone) {
                // 保持 PENDING，不动单据状态、不触发回调
            } else if (next != null) {
                notify(next.getApproverId(), task.getTenantId(), "新审批待处理",
                        "《" + order.get("title") + "》已通过第 " + task.getSeq()
                                + " 级审批，待你处理", task.getOrderId());
            } else {
                statMapper.updateApprovalOrderStatus(task.getOrderId(), "APPROVED", approverName,
                        note == null ? "同意" : note);
                finalDone = true;
                fire(order, true);
            }
        }

        notify(lng0(order.get("userId")), task.getTenantId(),
                approve ? "审批进度更新" : "审批被驳回",
                "你的《" + order.get("title") + "》"
                        + (finalDone ? "已全部审批通过"
                        : !approve ? "被驳回" + (note == null || note.isBlank() ? "" : "，意见：" + note)
                        : progressNote != null ? progressNote
                        : "第 " + task.getSeq() + " 级已通过"),
                task.getOrderId());

        audit.record(task.getTenantId(), institutionId, actor,
                approve ? "WORKFLOW_APPROVE" : "WORKFLOW_REJECT", "APPROVAL_TASK", taskId,
                "审批《" + order.get("title") + "》第 " + task.getSeq() + " 级节点："
                        + (approve ? "通过" : "驳回") + (finalDone ? "（终审通过）" : ""),
                null, Map.of("taskId", taskId, "decision", approve ? "APPROVED" : "REJECTED",
                        "finalDone", finalDone));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("taskId", taskId);
        out.put("orderId", task.getOrderId());
        out.put("decision", approve ? "APPROVED" : "REJECTED");
        out.put("finalDone", finalDone);
        // 会签节点：本条通过了但组内还有人没批 → nodeDone=false，单据仍 PENDING。
        // 前端据此提示「已通过 X/Y 人，仍待其余人会签」，避免用户以为单子已走完。
        boolean nodeDone = !approve || finalDone || progressNote == null;
        out.put("nodeDone", nodeDone);
        out.put("nodeProgress", progressNote);
        out.put("orderStatus", finalDone ? "APPROVED" : approve ? "PENDING" : "REJECTED");
        out.put("timeline", timeline(task.getOrderId()));
        return out;
    }

    /**
     * 当前节点 = 该单据 seq 最小的 PENDING 任务<b>所在的那一组</b>。
     *
     * <p>四期起改为比较 {@code seq} 而非任务 id：会签 / 抢占会让同一节点产生
     * 多条同 seq 任务，按 id 比较只有其中一条会被判为「当前」，其余同组任务
     * 会被误判为「前序节点未通过，暂不可审批」。</p>
     */
    private boolean isCurrentNode(ApprovalTask task) {
        List<ApprovalTask> pending = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, task.getOrderId())
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)
                .orderByAsc(ApprovalTask::getSeq)
                .last("limit 1"));
        return !pending.isEmpty() && Objects.equals(pending.get(0).getSeq(), task.getSeq());
    }

    /** 同节点组内仍为 PENDING 的任务条数（会签用它判断「是否全部通过」）。 */
    private int countPendingInGroup(Long orderId, Integer seq) {
        return Math.toIntExact(taskMapper.selectCount(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getSeq, seq)
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)));
    }

    /** 同节点组的全部任务条数（含已处理的）。 */
    private int countGroup(Long orderId, Integer seq) {
        return Math.toIntExact(taskMapper.selectCount(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getSeq, seq)));
    }

    /** 同节点组内指定状态的任务条数。 */
    private int countGroupByStatus(Long orderId, Integer seq, String status) {
        return Math.toIntExact(taskMapper.selectCount(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getSeq, seq)
                .eq(ApprovalTask::getStatus, status)));
    }

    /** 同节点组内仍待处理的任务（会签催办用）。 */
    private List<ApprovalTask> groupPending(Long orderId, Integer seq) {
        return taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getSeq, seq)
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)
                .orderByAsc(ApprovalTask::getId));
    }

    /**
     * 抢占模式：把同组其余待处理任务置为 SKIPPED（写明被谁抢先）。
     *
     * <p>用 SKIPPED 而不是删掉：<b>必须留痕</b>。否则「其余值班负责人为什么没审」
     * 在流转路径里查不到答案，会以为是系统漏派。</p>
     *
     * @return 实际置为 SKIPPED 的条数
     */
    private int skipGroupSiblings(Long orderId, Integer seq, Long keepTaskId, String reason) {
        List<ApprovalTask> siblings = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getSeq, seq)
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)
                .ne(ApprovalTask::getId, keepTaskId));
        for (ApprovalTask s : siblings) {
            ApprovalTask patch = new ApprovalTask();
            patch.setId(s.getId());
            patch.setStatus(ApprovalTask.SKIPPED);
            patch.setSkipReason(reason);
            patch.setUpdatedAt(LocalDateTime.now());
            taskMapper.updateById(patch);
        }
        return siblings.size();
    }

    private ApprovalTask nextPending(Long orderId, int afterSeq) {
        List<ApprovalTask> list = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)
                .gt(ApprovalTask::getSeq, afterSeq)
                .orderByAsc(ApprovalTask::getSeq)
                .last("limit 1"));
        return list.isEmpty() ? null : list.get(0);
    }

    private void fire(Map<String, Object> order, boolean approved) {
        String bizType = String.valueOf(order.get("bizType"));
        callbacks.stream()
                .filter(c -> bizType.equalsIgnoreCase(c.bizType()))
                .forEach(c -> {
                    try {
                        if (approved) {
                            c.onApproved(order);
                        } else {
                            c.onRejected(order);
                        }
                    } catch (Exception e) {
                        log.error("approval callback failed: bizType={} orderId={}", bizType,
                                order.get("id"), e);
                        throw e;
                    }
                });
    }

    // ================================================================== 流程定义管理

    public List<ApprovalFlowDef> listDefs(Long tenantId, Long institutionId) {
        LambdaQueryWrapper<ApprovalFlowDef> w = new LambdaQueryWrapper<ApprovalFlowDef>()
                .eq(ApprovalFlowDef::getTenantId, tenantId);
        if (institutionId != null) {
            w.eq(ApprovalFlowDef::getInstitutionId, institutionId);
        }
        return defMapper.selectList(w.orderByAsc(ApprovalFlowDef::getBizType));
    }

    @Transactional(rollbackFor = Exception.class)
    public ApprovalFlowDef saveDef(Long tenantId, AuthUser actor, Map<String, Object> body) {
        Long id = body.get("id") instanceof Number n ? n.longValue() : null;
        String bizType = req(body, "bizType");
        Long institutionId = body.get("institutionId") instanceof Number n ? n.longValue() : 0L;
        if (id != null) {
            ApprovalFlowDef def = defMapper.selectById(id);
            if (def == null || !def.getTenantId().equals(tenantId)) {
                throw BizException.notFound("审批流定义不存在：" + id);
            }
            if (bizType != null) {
                def.setBizType(bizType);
            }
            if (body.get("name") != null) {
                def.setName(String.valueOf(body.get("name")));
            }
            if (body.get("steps") != null) {
                def.setStepsJson(writeSteps(body.get("steps")));
            }
            if (body.get("status") != null) {
                def.setStatus(String.valueOf(body.get("status")));
            }
            if (body.get("remark") != null) {
                def.setRemark(String.valueOf(body.get("remark")));
            }
            def.setUpdatedAt(LocalDateTime.now());
            defMapper.updateById(def);
            audit.record(tenantId, 0L, actor, "FLOW_DEF_UPDATE", "APPROVAL_FLOW_DEF", def.getId(),
                    "编辑审批流「" + def.getName() + "」", null, def);
            return def;
        }
        ApprovalFlowDef def = new ApprovalFlowDef();
        def.setTenantId(tenantId);
        def.setInstitutionId(institutionId == null ? 0L : institutionId);
        def.setBizType(bizType == null ? "LEAVE" : bizType);
        def.setName(body.get("name") == null ? "新审批流" : String.valueOf(body.get("name")));
        def.setStepsJson(writeSteps(body.get("steps")));
        def.setStatus("ACTIVE");
        def.setRemark(body.get("remark") == null ? null : String.valueOf(body.get("remark")));
        def.setCreatedAt(LocalDateTime.now());
        def.setCreatedBy(actor.getUserId());
        defMapper.insert(def);
        audit.record(tenantId, institutionId, actor, "FLOW_DEF_CREATE", "APPROVAL_FLOW_DEF", def.getId(),
                "新建审批流「" + def.getName() + "」（" + def.getBizType() + "）", null, def);
        return def;
    }

    private String writeSteps(Object steps) {
        if (steps == null) {
            throw BizException.badRequest("steps 不能为空");
        }
        try {
            String json = steps instanceof String s ? s : objectMapper.writeValueAsString(steps);
            JsonNode node = objectMapper.readTree(json);
            if (!node.isArray() || node.isEmpty()) {
                throw BizException.badRequest("steps 必须是非空数组");
            }
            validateSteps(node);
            return json;
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw BizException.badRequest("steps 不是合法 JSON：" + e.getMessage());
        }
    }

    /**
     * 保存期的配置校验（五期）。
     *
     * <p>与运行期的宽容策略刻意相反：<b>运行期宁可多审一级</b>（未知模式退回 single、
     * 坏条件不拦截、解析不到人走兜底并写明原因），但<b>保存期必须报错</b> ——
     * 配置页是唯一能告诉管理员「你写错了」的地方，在这里静默接受，等于把问题
     * 推迟到某张真实单据上才暴露。</p>
     */
    private void validateSteps(JsonNode steps) {
        int i = 0;
        for (JsonNode s : steps) {
            i++;
            if (!s.isObject()) {
                throw BizException.badRequest("第 " + i + " 个节点必须是对象");
            }
            JsonNode mode = s.get("mode");
            if (mode != null && !mode.isNull()) {
                String m = mode.asText().trim();
                if (!ApprovalTask.MODE_SINGLE.equals(m) && !ApprovalTask.MODE_PARALLEL.equals(m)
                        && !ApprovalTask.MODE_GRAB.equals(m)) {
                    throw BizException.badRequest("第 " + i + " 个节点的 mode「" + m
                            + "」不支持（可用：single / parallel / grab）");
                }
            }
            JsonNode when = s.get("when");
            if (when != null && !when.isNull()) {
                if (!when.isObject() || !when.hasNonNull("field")) {
                    throw BizException.badRequest("第 " + i + " 个节点的 when 必须是含 field 的对象，"
                            + "如 {\"field\":\"days\",\"op\":\"<=\",\"value\":3}");
                }
            }
            JsonNode cc = s.get("cc");
            if (cc != null && !cc.isNull()) {
                if (!cc.isArray()) {
                    throw BizException.badRequest("第 " + i + " 个节点的 cc 必须是数组");
                }
                for (JsonNode c : cc) {
                    if (c.isObject()) {
                        if (!c.hasNonNull("type")) {
                            throw BizException.badRequest("第 " + i + " 个节点的 cc 对象必须含 type，"
                                    + "如 {\"type\":\"SPECIFIC\",\"user_id\":123}");
                        }
                    } else if (c.asText("").isBlank()) {
                        throw BizException.badRequest("第 " + i + " 个节点的 cc 含空值");
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------ 工具

    /** 仅本机构成员可作为审批人（供前端选人）。 */
    public List<OrgMember> approverCandidates(Long institutionId) {
        return memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByAsc(OrgMember::getId));
    }

    private String nameOf(Long userId) {
        if (userId == null) {
            return null;
        }
        Map<String, Object> u = statMapper.selectUserName(userId);
        return u == null || u.get("name") == null ? ("用户#" + userId) : String.valueOf(u.get("name"));
    }

    private void notify(Long userId, Long tenantId, String title, String content, Long refId) {
        if (userId == null || userId == 0L) {
            return;
        }
        try {
            Map<String, Object> row = new HashMap<>();
            row.put("tenantId", tenantId);
            row.put("userId", userId);
            row.put("type", "APPROVAL");
            row.put("title", title);
            row.put("content", content);
            row.put("refId", refId);
            statMapper.insertNotification(row);
            // 站内信落库后发布触达事件（自增 id 已回填到 row.get("id")）；
            // 发布失败绝不影响审批主流程（仅记 warn）。
            Object idObj = row.get("id");
            Long notificationId = idObj instanceof Number ? ((Number) idObj).longValue() : null;
            publishNotification(tenantId, userId, title, content, refId, notificationId);
        } catch (Exception e) {
            log.warn("notify failed: userId={} title={} err={}", userId, title, e.getMessage());
        }
    }

    /** 发布 NotificationRequested 事件（尽力而为，actor 不在本方法可见范围内 → null）。 */
    private void publishNotification(Long tenantId, Long userId, String title, String content,
                                     Long refId, Long notificationId) {
        try {
            events.publishEvent(new NotificationRequested(
                    tenantId == null ? 0L : tenantId, userId, "APPROVAL", title, content,
                    refId, null, notificationId));
        } catch (Exception e) {
            log.warn("发布通知触达事件失败（不影响审批主流程）userId={} title={}", userId, title, e);
        }
    }

    private static String req(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        if (v == null) {
            return null;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() ? null : s;
    }

    private static String str(Object v, String def) {
        return v == null || String.valueOf(v).isBlank() ? def : String.valueOf(v).trim();
    }

    private static Double dbl(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(v));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Long lng(Object v) {
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

    private static Integer asInt(Object v) {
        Long l = lng(v);
        return l == null ? null : l.intValue();
    }

    private static long lng0(Object v) {
        Long l = lng(v);
        return l == null ? 0L : l;
    }
}
