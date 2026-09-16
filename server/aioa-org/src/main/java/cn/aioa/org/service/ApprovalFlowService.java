package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.ApprovalFlowDef;
import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.ApprovalFlowDefMapper;
import cn.aioa.org.mapper.ApprovalTaskMapper;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

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
 *   <tr><td>{@code approver_type}</td><td>审批人类型（DEPT_LEADER / ORG_ADMIN / TENANT_ADMIN / PLATFORM_ADMIN / SPECIFIC / APPLICANT_SUPERIOR）</td></tr>
 *   <tr><td>{@code levels}</td><td>仅 APPLICANT_SUPERIOR：向上几级。缺省 = 整条链（向后兼容）；1 = 只到直接上级</td></tr>
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
    private final OrgDepartmentMapper deptMapper;
    private final OrgMemberMapper memberMapper;
    private final OrgStatMapper statMapper;
    private final ObjectMapper objectMapper;
    private final AuditRecorder audit;
    private final ObjectProvider<ApprovalCallback> callbacks;

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
        int seq = 0;
        Long firstApprover = null;
        StringBuilder note = new StringBuilder();
        for (Node n : nodes) {
            seq++;
            ApprovalTask t = new ApprovalTask();
            t.setTenantId(tenantId);
            t.setInstitutionId(institutionId);
            t.setOrderId(orderId);
            t.setSeq(seq);
            t.setApproverType(n.approverType);
            t.setApproverId(n.approverId);
            t.setApproverName(n.approverName);
            t.setTaskRole(ApprovalTask.ROLE_APPROVE);
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
            throw BizException.badRequest("审批节点全部被跳过，无法进入审批（请检查 threshold_days 配置）");
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
        out.put("nodeCount", nodes.size());
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

    private record Node(String approverType, Long approverId, String approverName,
                        String skipReason, String fallbackNote) {
    }

    /** 展开结果：审批节点（阻塞推进）+ 知会节点（不阻塞，对标 O2OA 的「待阅」）。 */
    private record ExpandResult(List<Node> approve, List<Node> cc) {
    }

    /** 上级梯级的展开结果：节点 + 「梯级缺位被迫顺延」的可见提示。 */
    private record Ladder(List<Node> nodes, String note) {
    }

    /** 节点类型的中文标签（提示文案用）。 */
    private static String labelOf(String type) {
        if (type == null) {
            return "未知节点";
        }
        return switch (type) {
            case ApprovalTask.TYPE_DEPT_LEADER -> "部门负责人";
            case ApprovalTask.TYPE_ORG_ADMIN -> "企业管理员";
            case ApprovalTask.TYPE_TENANT_ADMIN -> "租户管理员";
            case ApprovalTask.TYPE_PLATFORM_ADMIN -> "平台管理员";
            default -> type;
        };
    }

    /** 展开审批节点：解析审批人 → 阈值跳级 → 兜底；并解析知会对象。 */
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

        OrgInstitution inst = institutionId == 0L ? null : institutionMapper.selectById(institutionId);
        Long orgAdminId = inst == null ? null : inst.getAdminUserId();
        Long tenantAdminId = statMapper.selectFirstUserIdOfRole(tenantId, OrgGuard.ROLE_TENANT_ADMIN);
        Long platformAdminId = statMapper.selectFirstUserIdOfRole(0L, OrgGuard.ROLE_ADMIN);
        Long deptLeaderId = resolveDeptLeader(institutionId, req.departmentId());
        // 上级链用的严格版：只认申请人「本部门」的负责人，不跨部门兜底（见 resolveDeptLeader）
        Long deptLeaderStrict = resolveDeptLeader(institutionId, req.departmentId(), false);

        List<Node> nodes = new ArrayList<>();
        boolean hasEffective = false;
        int index = 0;
        for (Map<String, Object> step : steps) {
            String type = str(step.get("approver_type"), DEFAULT_APPROVER_TYPE);
            Double threshold = dbl(step.get("threshold_days"));
            Long specific = lng(step.get("approver_id"));

            // 「申请人的上一级」：一个 step 展开为上级链（按申请人组织层级递推 + 自审防护）。
            // 与其它类型的关键区别 —— 起点由申请人自身所处的层级决定，而不是所有人共用一条固定链。
            // levels 控制向上几级：缺省 = 整条链（向后兼容），levels=1 = 只到直接上级，
            // 这正是「普通用户申请 → 部门负责人一级审批」的落地方式。
            if (ApprovalTask.TYPE_APPLICANT_SUPERIOR.equals(type)) {
                Ladder ladder = superiorLadder(tenantId, institutionId, req, asInt(step.get("levels")),
                        deptLeaderStrict, orgAdminId, tenantAdminId, platformAdminId);
                if (ladder.nodes().isEmpty()) {
                    throw BizException.badRequest("未找到可用的上级审批人：申请人在其组织层级之上没有可指派的审批人，"
                            + "请先配置部门负责人 / 企业管理员 / 租户管理员");
                }
                boolean first = true;
                for (Node n : ladder.nodes()) {
                    index++;
                    hasEffective = true;
                    // 梯级缺位的提示挂在首个节点上：前端「流程提示」据此显示
                    // 「部门负责人未设置，已顺延到企业管理员」，避免兜底改派被伪装成正常一级审批。
                    nodes.add(first ? new Node(n.approverType(), n.approverId(), n.approverName(),
                            n.skipReason(), ladder.note()) : n);
                    first = false;
                }
                continue;
            }

            index++;
            Long approverId = null;
            String fallback = null;

            switch (type) {
                case ApprovalTask.TYPE_DEPT_LEADER -> {
                    approverId = deptLeaderId;
                    if (approverId == null) {
                        fallback = "第 " + index + " 级「部门负责人」未解析到（部门未设置负责人），已改由企业管理员审批";
                    }
                }
                case ApprovalTask.TYPE_ORG_ADMIN -> approverId = orgAdminId;
                case ApprovalTask.TYPE_TENANT_ADMIN -> approverId = tenantAdminId;
                case ApprovalTask.TYPE_PLATFORM_ADMIN -> approverId = platformAdminId;
                case ApprovalTask.TYPE_SPECIFIC -> approverId = specific != null
                        ? specific : req.specificApproverId();
                default -> fallback = "未知审批人类型「" + type + "」，已改由企业管理员审批";
            }
            // 兜底改派时，节点类型必须同步改成「实际生效的类型」。
            // 历史缺陷：改派后 approver_type 仍保留原值，前端会把机构管理员显示成
            // 「部门负责人」，出现「节点名与审批人对不上」。
            String effectiveType = type;
            if (approverId == null && !ApprovalTask.TYPE_ORG_ADMIN.equals(type)) {
                if (orgAdminId != null) {
                    approverId = orgAdminId;
                    effectiveType = ApprovalTask.TYPE_ORG_ADMIN;
                } else if (tenantAdminId != null) {
                    approverId = tenantAdminId;
                    effectiveType = ApprovalTask.TYPE_TENANT_ADMIN;
                } else if (platformAdminId != null) {
                    approverId = platformAdminId;
                    effectiveType = ApprovalTask.TYPE_PLATFORM_ADMIN;
                }
                if (approverId != null && fallback == null) {
                    fallback = "第 " + index + " 级审批人未解析到，已改由机构管理员 / 租户管理员兜底";
                }
            }
            if (approverId == null) {
                throw BizException.badRequest("第 " + index + " 级节点无法解析审批人，请先在机构管理中指定企业管理员（FR-B2）");
            }

            String skipReason = null;
            if (threshold != null && hasEffective && req.days() != null && req.days() <= threshold) {
                skipReason = "申请天数 " + req.days() + " ≤ 阈值 " + threshold + "，按配置跳级";
            }
            if (skipReason == null) {
                hasEffective = true;
            }
            nodes.add(new Node(effectiveType, approverId, nameOf(approverId), skipReason, fallback));
        }

        List<Node> ccs = expandCcNodes(steps, req, deptLeaderId, orgAdminId, tenantAdminId, platformAdminId,
                nodes.stream().map(Node::approverId).filter(java.util.Objects::nonNull).toList());
        return new ExpandResult(nodes, ccs);
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
        java.util.Set<String> seenTypes = new java.util.LinkedHashSet<>();
        for (Map<String, Object> step : steps) {
            Object raw = step.get("cc");
            if (!(raw instanceof List<?> list)) {
                continue;
            }
            for (Object item : list) {
                String type = str(item, null);
                if (type == null || !seenTypes.add(type)) {
                    continue;
                }
                Long id = switch (type) {
                    case ApprovalTask.TYPE_DEPT_LEADER -> deptLeaderId;
                    case ApprovalTask.TYPE_ORG_ADMIN -> orgAdminId;
                    case ApprovalTask.TYPE_TENANT_ADMIN -> tenantAdminId;
                    case ApprovalTask.TYPE_PLATFORM_ADMIN -> platformAdminId;
                    default -> null;
                };
                if (id == null) {
                    continue;
                }
                if (req.applicantUserId() != null && req.applicantUserId().equals(id)) {
                    continue;
                }
                if (approverIds.contains(id)) {
                    continue;
                }
                boolean dup = out.stream().anyMatch(x -> id.equals(x.approverId()));
                if (dup) {
                    continue;
                }
                out.add(new Node(type, id, nameOf(id), null, null));
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
                                  Long deptLeaderId, Long orgAdminId, Long tenantAdminId, Long platformAdminId) {
        Long applicant = req.applicantUserId();

        List<Node> rungs = new ArrayList<>();
        rungs.add(new Node(ApprovalTask.TYPE_DEPT_LEADER, deptLeaderId, nameOf(deptLeaderId), null, null));
        rungs.add(new Node(ApprovalTask.TYPE_ORG_ADMIN, orgAdminId, nameOf(orgAdminId), null, null));
        rungs.add(new Node(ApprovalTask.TYPE_TENANT_ADMIN, tenantAdminId, nameOf(tenantAdminId), null, null));
        rungs.add(new Node(ApprovalTask.TYPE_PLATFORM_ADMIN, platformAdminId, nameOf(platformAdminId), null, null));

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

    /**
     * 解析「部门负责人」——<b>先职务、后回落</b>（O2OA 的 Duty 优先级）。
     *
     * <ol>
     *   <li>该部门内 {@code duty_code='DEPT_PRINCIPAL'}（部门正职）的成员 —— V42 回填后
     *       这是唯一权威口径，且支持同部门多正职（取 id 最小者，结果稳定）；</li>
     *   <li>回落 {@code org_department.leader_user_id} —— 兼容 V42 之前只配了这一列的部门；</li>
     *   <li>末级回落「该机构第一个有负责人的部门」—— 见 {@code allowCrossDeptFallback}。</li>
     * </ol>
     *
     * @param allowCrossDeptFallback 是否允许<b>跨部门</b>兜底取「本机构第一个部门负责人」。
     *       固定模板（如请假流的 {@code DEPT_LEADER} 节点）沿用既有行为传 true；
     *       <b>「申请人的上级链」必须传 false</b> —— 那道链里「部门负责人」的语义是
     *       「申请人<b>本部门</b>的负责人」，跨部门兜底会让 A 部门的申请被 B 部门负责人审批，
     *       且把「本部门没配负责人」这个配置缺陷伪装成「正常一级审批」。
     *       缺位时留 null，由上级链顺延到机构管理员并在单据上写明缺位原因。
     */
    private Long resolveDeptLeader(Long institutionId, Long departmentId, boolean allowCrossDeptFallback) {
        if (departmentId != null && departmentId > 0) {
            Long byDuty = firstPrincipalOfDept(departmentId);
            if (byDuty != null) {
                return byDuty;
            }
            OrgDepartment d = deptMapper.selectById(departmentId);
            if (d != null && d.getLeaderUserId() != null) {
                return d.getLeaderUserId();
            }
        }
        if (!allowCrossDeptFallback) {
            return null;
        }
        return firstDeptLeaderOfInstitution(institutionId);
    }

    /** 固定模板语义：允许跨部门兜底（既有行为，保持不变）。 */
    private Long resolveDeptLeader(Long institutionId, Long departmentId) {
        return resolveDeptLeader(institutionId, departmentId, true);
    }

    /** 兜底：该机构第一个部门负责人。 */
    private Long firstDeptLeaderOfInstitution(Long institutionId) {
        List<OrgDepartment> list = deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId)
                .isNotNull(OrgDepartment::getLeaderUserId)
                .orderByAsc(OrgDepartment::getLevel)
                .orderByAsc(OrgDepartment::getSort)
                .last("limit 1"));
        return list.isEmpty() ? null : list.get(0).getLeaderUserId();
    }

    /** 部门内持「部门正职」职务的第一个成员（按 id 升序，保证同部门多正职时结果稳定）。 */
    private Long firstPrincipalOfDept(Long departmentId) {
        List<OrgMember> rows = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getDepartmentId, departmentId)
                .eq(OrgMember::getDutyCode, OrgDuty.DEPT_PRINCIPAL)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByAsc(OrgMember::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0).getUserId();
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
                // cc：知会（抄送）对象类型清单，如 ["ORG_ADMIN"] —— 不阻塞流转，只进「抄送我的」
                List<String> cc = new ArrayList<>();
                if (n.has("cc") && n.get("cc").isArray()) {
                    for (JsonNode c : n.get("cc")) {
                        String s = c.asText(null);
                        if (s != null && !s.isBlank()) {
                            cc.add(s.trim());
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

    public List<Map<String, Object>> timeline(Long orderId) {
        List<Map<String, Object>> rows = statMapper.selectTasksOfOrder(orderId);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("taskId", lng(r.get("id")));
            m.put("seq", r.get("seq"));
            m.put("approverType", r.get("approverType"));
            m.put("approverId", lng(r.get("approverId")));
            m.put("approverName", displayApprover((String) r.get("approverName"), lng(r.get("approverId"))));
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
        if (!ApprovalTask.PENDING.equals(task.getStatus())) {
            throw BizException.badRequest("该审批节点已处理（" + task.getStatus() + "），不可重复审批");
        }
        // 知会（抄送）节点不需要审批：它的意义是「知情」而非「点头」。
        // 若放行，抄送人一个操作就能让单据终态 —— 与「不阻塞流转」的语义直接冲突。
        if (ApprovalTask.ROLE_CC.equals(task.getTaskRole())) {
            throw BizException.badRequest("该条目为知会（抄送），无需审批；如需推进请由当前审批人处理");
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
            ApprovalTask next = nextPending(task.getOrderId(), task.getSeq());
            if (next != null) {
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
                        + (finalDone ? "已全部审批通过" : approve ? "第 " + task.getSeq() + " 级已通过"
                        : "被驳回" + (note == null || note.isBlank() ? "" : "，意见：" + note)),
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
        out.put("orderStatus", finalDone ? "APPROVED" : approve ? "PENDING" : "REJECTED");
        out.put("timeline", timeline(task.getOrderId()));
        return out;
    }

    /** 当前节点 = 该单据 seq 最小的 PENDING 任务。 */
    private boolean isCurrentNode(ApprovalTask task) {
        List<ApprovalTask> pending = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, task.getOrderId())
                .eq(ApprovalTask::getStatus, ApprovalTask.PENDING)
                .orderByAsc(ApprovalTask::getSeq)
                .last("limit 1"));
        return !pending.isEmpty() && pending.get(0).getId().equals(task.getId());
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
            return json;
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw BizException.badRequest("steps 不是合法 JSON：" + e.getMessage());
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
        } catch (Exception e) {
            log.warn("notify failed: userId={} title={} err={}", userId, title, e.getMessage());
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
