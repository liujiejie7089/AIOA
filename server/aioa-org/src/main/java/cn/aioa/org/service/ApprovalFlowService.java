package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.ApprovalFlowDef;
import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgDepartment;
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
 * 兼容性：既有单级 {@code approval_order} 接口与 {@code ApprovalService} 完全不变，
 * 本引擎仅在 bizType 命中「配置了多级流程」时接管；未配置流程时按单节点 ORG_ADMIN 处理。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ApprovalFlowService {

    public static final String DEFAULT_APPROVER_TYPE = ApprovalTask.TYPE_ORG_ADMIN;

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
                            Long applicantUserId, String applicantName, Long specificApproverId) {
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
        order.put("bizType", req.bizType());
        order.put("title", req.title());
        order.put("content", req.content());
        order.put("formData", req.formData());
        order.put("attachment", null);
        order.put("createdBy", userId);
        statMapper.insertApprovalOrder(order);
        Long orderId = ((Number) order.get("id")).longValue();

        List<Node> nodes = expandNodes(tenantId, institutionId, req);
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
        if (note.length() > 0) {
            statMapper.updateApprovalOrderStatus(orderId, "PENDING", null,
                    "提交时的流程提示：" + note);
        }
        notify(firstApprover, tenantId, "新审批待处理",
                applicantName + " 提交了《" + (req.title() == null ? req.bizType() : req.title())
                        + "》，待你审批", orderId);
        audit.record(tenantId, institutionId, actor, "WORKFLOW_SUBMIT", "APPROVAL_ORDER", orderId,
                "提交「" + req.bizType() + "」审批单（共 " + nodes.size() + " 级节点）",
                null, Map.of("orderId", orderId, "nodes", nodes.size()));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("orderId", orderId);
        out.put("status", "PENDING");
        out.put("nodeCount", nodes.size());
        out.put("currentApproverId", firstApprover);
        out.put("timeline", timeline(orderId));
        return out;
    }

    private record Node(String approverType, Long approverId, String approverName,
                        String skipReason, String fallbackNote) {
    }

    /** 展开审批节点：解析审批人 → 阈值跳级 → 兜底。 */
    private List<Node> expandNodes(Long tenantId, Long institutionId, SubmitReq req) {
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

        List<Node> nodes = new ArrayList<>();
        boolean hasEffective = false;
        int index = 0;
        for (Map<String, Object> step : steps) {
            index++;
            String type = str(step.get("approver_type"), DEFAULT_APPROVER_TYPE);
            Double threshold = dbl(step.get("threshold_days"));
            Long specific = lng(step.get("approver_id"));
            Long approverId = null;
            String fallback = null;

            switch (type) {
                case ApprovalTask.TYPE_DEPT_LEADER -> {
                    approverId = resolveDeptLeader(institutionId, req.departmentId());
                    if (approverId == null) {
                        fallback = "第 " + index + " 级「部门负责人」未解析到（部门未设置负责人），已改由企业管理员审批";
                    }
                }
                case ApprovalTask.TYPE_ORG_ADMIN -> approverId = orgAdminId;
                case ApprovalTask.TYPE_TENANT_ADMIN -> approverId = tenantAdminId;
                case ApprovalTask.TYPE_SPECIFIC -> approverId = specific != null
                        ? specific : req.specificApproverId();
                default -> fallback = "未知审批人类型「" + type + "」，已改由企业管理员审批";
            }
            if (approverId == null && !ApprovalTask.TYPE_ORG_ADMIN.equals(type)) {
                approverId = orgAdminId;
                if (approverId == null) {
                    approverId = tenantAdminId;
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
            nodes.add(new Node(type, approverId, nameOf(approverId), skipReason, fallback));
        }
        return nodes;
    }

    private Long resolveDeptLeader(Long institutionId, Long departmentId) {
        if (departmentId != null && departmentId > 0) {
            OrgDepartment d = deptMapper.selectById(departmentId);
            if (d != null && d.getLeaderUserId() != null) {
                return d.getLeaderUserId();
            }
        }
        // 兜底：该机构第一个部门负责人
        List<OrgDepartment> list = deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId)
                .isNotNull(OrgDepartment::getLeaderUserId)
                .orderByAsc(OrgDepartment::getLevel)
                .orderByAsc(OrgDepartment::getSort)
                .last("limit 1"));
        return list.isEmpty() ? null : list.get(0).getLeaderUserId();
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

    /** 待我审批：我是当前节点审批人且单据仍未决。 */
    public List<Map<String, Object>> todo(AuthUser actor) {
        List<ApprovalTask> mine = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getApproverId, actor.getUserId())
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
            m.put("taskNote", t.getNote());
            m.put("totalNodes", taskMapper.selectCount(new LambdaQueryWrapper<ApprovalTask>()
                    .eq(ApprovalTask::getOrderId, t.getOrderId())));
            out.add(m);
        }
        return out;
    }

    public List<Map<String, Object>> mine(AuthUser actor) {
        return statMapper.selectApprovalOrders(actor.getTenantId(), actor.getUserId(), null);
    }

    public List<Map<String, Object>> timeline(Long orderId) {
        List<ApprovalTask> tasks = taskMapper.selectList(new LambdaQueryWrapper<ApprovalTask>()
                .eq(ApprovalTask::getOrderId, orderId)
                .orderByAsc(ApprovalTask::getSeq));
        List<Map<String, Object>> out = new ArrayList<>(tasks.size());
        for (ApprovalTask t : tasks) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("taskId", t.getId());
            m.put("seq", t.getSeq());
            m.put("approverType", t.getApproverType());
            m.put("approverId", t.getApproverId());
            m.put("approverName", t.getApproverName());
            m.put("status", t.getStatus());
            m.put("note", t.getNote());
            m.put("skipReason", t.getSkipReason());
            m.put("decidedAt", t.getDecidedAt() == null ? null : t.getDecidedAt().toString());
            out.add(m);
        }
        return out;
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

    private static long lng0(Object v) {
        Long l = lng(v);
        return l == null ? 0L : l;
    }
}
