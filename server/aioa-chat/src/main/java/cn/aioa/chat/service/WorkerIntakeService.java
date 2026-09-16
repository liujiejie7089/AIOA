package cn.aioa.chat.service;

import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.org.service.LeaveService;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.service.BillingService;
import cn.aioa.resource.service.KbService;
import cn.aioa.resource.service.ToolGatewayService;
import cn.aioa.resource.support.WorkerRole;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 数字员工「准入链路」服务 —— 意图识别 + 创建前六项前置检查（需求项 6）。
 *
 * <p><b>为什么放在 aioa-chat</b>：六项检查要同时读「权限/计费/工具」（aioa-resource）与
 * 「审批人/审批流/假种/知识库」（aioa-org），而这两个模块是<b>互不依赖</b>的兄弟模块，
 * 只有 aioa-chat 同时依赖二者（与 {@code StatsController} 同理）。
 * 放在这里是为了不发明新依赖，而不是因为业务归属在"聊天"。</p>
 *
 * <p><b>需求原文的流程</b>：意图识别 → 前置检查 → 权限申请 → 审批授权 → 创建向导 →
 * 表单配置 → 运行计费审计回收。本类负责前两段：</p>
 * <ul>
 *   <li>{@link #intent} —— 自然语言归类到数字员工类型。分类算法在 Python
 *       （{@code agent/app/core/worker_intake.py}），符合「AI 相关业务在 Python 实现」的边界；
 *       本方法只负责调用与「补权限信息」（权限映射属治理事实，只在 Java 侧定义一份）。</li>
 *   <li>{@link #precheck} —— 六项检查一次性给出，每项都要能回答「能不能做 / 卡在哪 / 找谁办」。</li>
 * </ul>
 *
 * <p><b>设计原则：不把「拒绝」做成死胡同。</b> 每一项 BLOCKED 都必须同时给出
 * {@code adminScript}（给管理员的话术）与 {@code nextStep}（用户自己能走的下一步）；
 * 否则用户只知道不行，不知道怎么办 —— 这正是需求里「审批人缺失时直接阻断并给管理员话术」的本意。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerIntakeService {

    public static final String PASS = "PASS";
    public static final String WARN = "WARN";
    public static final String BLOCKED = "BLOCKED";

    /** 权限申请的审批流业务类型（V37 已种租户默认流）。 */
    private static final String BIZ_PERMISSION_GRANT = "PERMISSION_GRANT";

    private final ObjectMapper objectMapper;
    private final ToolGatewayService toolGatewayService;
    private final ApprovalFlowService approvalFlowService;
    private final BillingService billingService;
    private final KbService kbService;
    private final LeaveService leaveService;
    private final OrgDepartmentMapper departmentMapper;
    private final OrgMemberMapper memberMapper;

    @Value("${aioa.agent.base-url:http://localhost:8000}")
    private String agentBaseUrl;

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    // ================================================================== 意图识别

    /**
     * 自然语言 → 数字员工类型 → 推荐权限（不要求用户认识权限码）。
     *
     * <p>Python 侧不可达时降级为 Java 侧关键词推断（{@link WorkerRole#infer}），
     * 保证「agent 挂了」不会连带把创建入口也搞挂 —— 准入链路必须比 AI 推理更可靠。</p>
     */
    public Map<String, Object> intent(String text) {
        Map<String, Object> out = new LinkedHashMap<>();
        String roleCode;
        double confidence;
        List<String> matched;
        String boundary;
        List<String> formFields;
        String nextStep;
        String source;

        JsonNode node = callPython(text);
        if (node != null && node.hasNonNull("role")) {
            roleCode = node.get("role").asText();
            confidence = node.path("confidence").asDouble(0);
            matched = toStringList(node.path("matched"));
            boundary = node.path("boundary").asText("");
            formFields = toStringList(node.path("formFields"));
            nextStep = node.path("nextStep").asText("");
            source = "agent";
        } else {
            WorkerRole inferred = WorkerRole.infer(text, null);
            roleCode = inferred.code();
            confidence = inferred == WorkerRole.GENERAL ? 0.0 : 0.5;
            matched = List.of();
            boundary = inferred.duty();
            formFields = List.of();
            nextStep = "补充职责描述，或直接开始对话";
            source = "local-fallback";
        }

        WorkerRole role = WorkerRole.of(roleCode);
        String permission = role.requiredPermission();

        out.put("role", role.code());
        out.put("roleName", role.displayName());
        out.put("duty", role.duty());
        out.put("boundary", boundary);
        out.put("confidence", confidence);
        out.put("matched", matched);
        out.put("formFields", formFields);
        out.put("nextStep", nextStep);
        out.put("source", source);
        // 权限映射：类型 → 权限码 → 允许角色，全部取自 PermissionCatalog，不在此处另写一份
        out.put("requiredPermission", permission);
        out.put("permissionName", PermissionCatalog.nameOf(permission));
        out.put("allowedRoles", PermissionCatalog.rolesText(permission));
        out.put("applicable", PermissionCatalog.applicable(permission));
        out.put("applyPath", PermissionCatalog.applicable(permission)
                ? "管理端 → 权限授权，或对 AI 说「帮我申请 " + permission + " 权限」"
                : "该权限不开放申请，请联系平台管理员");
        return out;
    }

    private JsonNode callPython(String text) {
        try {
            String body = objectMapper.writeValueAsString(Map.of("text", text));
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/worker-intent"))
                    .timeout(Duration.ofSeconds(8))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() / 100 != 2) {
                log.warn("worker-intent 返回 HTTP {}，降级为本地推断", resp.statusCode());
                return null;
            }
            return objectMapper.readTree(resp.body());
        } catch (Exception e) {
            log.warn("worker-intent 调用失败，降级为本地推断: {}", e.getMessage());
            return null;
        }
    }

    // ================================================================== 前置检查

    /**
     * 创建前六项前置检查：权限 / 能力 / 审批人 / 表单 / 审批流 / 计费。
     *
     * <p>只做检查，<b>不落库、不产生半成品</b>；创建接口自身仍会独立再做一次准入校验，
     * 本方法不是唯一防线（防止绕过 precheck 直接调创建）。</p>
     */
    public Map<String, Object> precheck(AuthUser user, Map<String, Object> body) {
        String text = str(body.get("text"));
        String explicitType = str(body.get("workerType"));

        Map<String, Object> identified;
        if (explicitType != null && !explicitType.isBlank()) {
            identified = describe(explicitType);
            identified.put("confidence", 1.0);
            identified.put("matched", List.of());
            identified.put("source", "explicit");
        } else {
            identified = intent(text == null ? "" : text);
        }

        WorkerRole role = WorkerRole.of(str(identified.get("role")));
        List<Map<String, Object>> checks = new ArrayList<>();
        checks.add(checkPermission(user, role));
        checks.add(checkCapability(user, role));
        checks.add(checkApprover(user, role));
        checks.add(checkForm(user, role));
        checks.add(checkFlow(user, role));
        checks.add(checkQuota(user));

        List<Map<String, Object>> blockers = checks.stream()
                .filter(c -> BLOCKED.equals(c.get("status")))
                .toList();
        boolean ok = blockers.isEmpty();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", ok);
        out.putAll(identified);
        out.put("checks", checks);
        out.put("blockers", blockers);
        out.put("blockedCodes", blockers.stream().map(b -> b.get("key")).toList());
        // 唯一下一步 + 可转述给管理员的话术：阻断时以第一个阻断项为准，避免多线索让用户无从下手
        Map<String, Object> lead = ok ? null : blockers.get(0);
        out.put("nextAction", ok
                ? str(identified.get("nextStep"))
                : str(lead.get("nextAction")));
        out.put("adminScript", ok ? null : str(lead.get("adminScript")));
        out.put("canCreate", ok && PermissionCatalog.holds(user, role.requiredPermission()));
        return out;
    }

    private Map<String, Object> describe(String workerType) {
        WorkerRole role = WorkerRole.of(workerType);
        String permission = role.requiredPermission();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("role", role.code());
        m.put("roleName", role.displayName());
        m.put("duty", role.duty());
        m.put("boundary", role.duty());
        m.put("formFields", List.of());
        m.put("nextStep", "确认配置后创建");
        m.put("requiredPermission", permission);
        m.put("permissionName", PermissionCatalog.nameOf(permission));
        m.put("allowedRoles", PermissionCatalog.rolesText(permission));
        m.put("applicable", PermissionCatalog.applicable(permission));
        return m;
    }

    /** ① 权限：是否持有该类型所需权限码；不持有但可申请时给出申请路径。 */
    private Map<String, Object> checkPermission(AuthUser user, WorkerRole role) {
        String permission = role.requiredPermission();
        if (PermissionCatalog.holds(user, permission)) {
            return check("PERMISSION", "权限", PASS,
                    "已持有「" + PermissionCatalog.nameOf(permission) + "」（" + permission + "）");
        }
        String tail = PermissionCatalog.applicable(permission)
                ? "该权限可申请"
                : "该权限不开放申请";
        return check("PERMISSION", "权限", BLOCKED,
                "缺少权限码 " + permission + "（" + PermissionCatalog.nameOf(permission) + "，允许角色："
                        + PermissionCatalog.rolesText(permission) + "）；" + tail,
                PermissionCatalog.applicable(permission)
                        ? "对 AI 说「帮我申请 " + permission + " 权限」，提交后由部门负责人与租户管理员审批"
                        : "联系平台管理员开通该权限",
                PermissionCatalog.applicable(permission)
                        ? "请为本单位成员开通「" + PermissionCatalog.nameOf(permission) + "」（" + permission
                        + "）。办理路径：管理端 → 权限授权（/api/v1/tenant/grants），"
                        + "或让其在对 AI 提交权限申请后由您审批。"
                        : "该权限为平台级权限，请联系平台管理员");
    }

    /** ② 能力：平台是否注册了该类型所需工具；以及该类型赖以工作的数据是否就绪。 */
    private Map<String, Object> checkCapability(AuthUser user, WorkerRole role) {
        List<String> tools = role.requiredTools();
        Set<String> registered = toolGatewayService.listTools().stream()
                .map(t -> {
                    Object fn = t.get("function");
                    if (fn instanceof Map<?, ?> m) {
                        Object name = m.get("name");
                        return name == null ? null : String.valueOf(name);
                    }
                    return null;
                })
                .filter(java.util.Objects::nonNull)
                .collect(Collectors.toSet());
        List<String> missing = tools.stream().filter(t -> !registered.contains(t)).toList();
        if (!missing.isEmpty()) {
            return check("CAPABILITY", "能力", BLOCKED,
                    "平台尚未提供该类型所需能力：" + String.join("、", missing),
                    "联系平台管理员开通对应工具能力后再创建",
                    "该数字人类型的工具能力（" + String.join("、", missing)
                            + "）尚未在本平台注册，请先完成工具接入。");
        }

        // 数据就绪：知识库问答没有可检索文档、请假审批没有假种配置，都会让数字人"建了等于没建"
        if (role == WorkerRole.KB_ASSISTANT) {
            List<KbDocument> docs = kbService.list(user.getTenantId(), user.getUserId());
            if (docs == null || docs.isEmpty()) {
                return check("CAPABILITY", "能力", WARN,
                        "本账号当前没有可用知识库文档，知识库问答数字人将检索不到任何内容",
                        "先上传企业制度/资料到知识库，再创建该数字人",
                        "请为该成员上传或授权知识库文档（管理端 → 知识库），否则该数字人无法据实作答。");
            }
            return check("CAPABILITY", "能力", PASS, "知识库可用文档 " + docs.size() + " 篇");
        }
        if (role == WorkerRole.LEAVE_APPROVER) {
            int types = leaveService.listTypes(user.getTenantId()).size();
            if (types == 0) {
                return check("CAPABILITY", "能力", BLOCKED,
                        "本租户尚未配置任何假种，请假审批数字人无法受理申请",
                        "请先由租户管理员配置假种",
                        "请先在「管理端 → 请假设置」配置假种（年假/事假/病假等），"
                                + "否则请假数字人没有可受理的业务类型。");
            }
            return check("CAPABILITY", "能力", PASS, "已配置假种 " + types + " 种，工具能力齐全");
        }
        return check("CAPABILITY", "能力", PASS,
                tools.isEmpty() ? "纯生成能力，无外部工具依赖" : "所需能力已就绪");
    }

    /**
     * 该场景是否需要审批链。
     *
     * <p>这是「审批人」「审批流」两项检查的前置门控，缺了它会出两种误报（实测踩到）：
     * ① 通用助手根本不产生审批单，却因为「本部门无负责人」被判阻断；
     * ② 租户管理员自己就是终审人，却因为「找不到上游审批人」被判阻断。
     * 两种情况都会把正常的创建流程拦死，属于典型的「检查越界」。</p>
     */
    private static boolean needsApprovalChain(AuthUser user, WorkerRole role) {
        if (role == WorkerRole.LEAVE_APPROVER) {
            return true;
        }
        String permission = role.requiredPermission();
        return !PermissionCatalog.holds(user, permission) && PermissionCatalog.applicable(permission);
    }

    /** ③ 审批人：该类型投入使用（或申请权限）后，审批单是否有可流转的审批人。 */
    private Map<String, Object> checkApprover(AuthUser user, WorkerRole role) {
        if (!needsApprovalChain(user, role)) {
            return check("APPROVER", "审批人", PASS, "该类型不产生审批单，无需配置审批人");
        }
        // 自己就是终审人（平台/租户管理员）：不存在"上游审批人缺失"的问题
        if (PermissionCatalog.isAdmin(user)) {
            return check("APPROVER", "审批人", PASS, "您本人为该租户终审人，产生的申请将由您直接受理");
        }
        OrgDepartment dept = user.getDepartmentId() == null ? null
                : departmentMapper.selectById(user.getDepartmentId());
        if (dept != null && dept.getLeaderUserId() != null) {
            String leader = dept.getLeaderName() == null ? ("用户#" + dept.getLeaderUserId()) : dept.getLeaderName();
            return check("APPROVER", "审批人", PASS,
                    "本部门负责人：" + leader + "（" + dept.getName() + "）");
        }
        // 本部门无负责人时，审批链会落到企业管理员；能落上就不算阻断，但必须如实告知改派
        OrgMember orgAdmin = findOrgAdmin(user.getInstitutionId());
        if (orgAdmin != null) {
            return check("APPROVER", "审批人", WARN,
                    (dept == null ? "您未绑定部门" : "本部门（" + dept.getName() + "）未设置负责人")
                            + "，审批将上移到企业管理员：" + orgAdmin.getName(),
                    "可先由企业管理员代审，或请管理员设置部门负责人",
                    "该成员所在部门未设负责人，其提交的申请将直接进入您的待办。"
                            + "建议在「管理端 → 组织架构」设置部门负责人，让审批链回到正常层级。");
        }
        return check("APPROVER", "审批人", BLOCKED,
                "找不到可用审批人：本部门未设负责人，且本机构未指定企业管理员",
                "请管理员先指定审批人，再创建该数字员工",
                "请先在「管理端 → 组织架构」为该成员所在部门指定负责人，"
                        + "或在「机构管理」中指定企业管理员；否则任何申请都会卡住无人可审。");
    }

    private OrgMember findOrgAdmin(Long institutionId) {
        if (institutionId == null) {
            return null;
        }
        List<OrgMember> admins = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId)
                .eq(OrgMember::getIsOrgAdmin, true)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByAsc(OrgMember::getId));
        return admins.isEmpty() ? null : admins.get(0);
    }

    /** ④ 表单：该类型需要的输入参数是否已有模板。表单设计器属下一阶段（V39），当前只如实告知。 */
    private Map<String, Object> checkForm(AuthUser user, WorkerRole role) {
        if (role == WorkerRole.GENERAL || role == WorkerRole.DOC_DRAFTER) {
            return check("FORM", "表单", PASS, "无需表单参数模板");
        }
        return check("FORM", "表单", WARN,
                "该类型建议按「" + String.join(" / ", formFieldsOf(role)) + "」采集参数，"
                        + "当前使用系统预置参数表单（表单设计器将在后续版本提供）",
                "可直接使用预置参数表单，无需额外配置",
                "表单模板功能尚未上线，当前该类型使用系统预置参数表单，不影响使用。");
    }

    private static List<String> formFieldsOf(WorkerRole role) {
        return switch (role) {
            case LEAVE_APPROVER -> List.of("假种", "起止时间", "请假事由", "证明材料");
            case KB_ASSISTANT -> List.of("检索范围", "关键词");
            default -> List.of();
        };
    }

    /** ⑤ 审批流：会产生审批单的类型，其 bizType 是否已有可用流程定义。 */
    private Map<String, Object> checkFlow(AuthUser user, WorkerRole role) {
        if (!needsApprovalChain(user, role)) {
            return check("FLOW", "审批流", PASS, "该类型不产生审批单，无需审批流");
        }
        String bizType = role == WorkerRole.LEAVE_APPROVER ? LeaveService.BIZ_TYPE : BIZ_PERMISSION_GRANT;
        Long institutionId = user.getInstitutionId();
        boolean instDef = hasDef(user.getTenantId(), institutionId, bizType);
        boolean tenantDef = hasDef(user.getTenantId(), 0L, bizType);
        if (instDef) {
            return check("FLOW", "审批流", PASS, "使用本机构专属流程（" + bizType + "）");
        }
        if (tenantDef) {
            return check("FLOW", "审批流", PASS, "使用租户默认流程（" + bizType + "）");
        }
        return check("FLOW", "审批流", WARN,
                "未配置「" + bizType + "」专属流程，将使用系统内置单级审批兜底",
                "如需多级审批，请租户管理员在「审批流定义」中配置",
                "该租户尚未为「" + bizType + "」配置审批流，当前走系统内置单级兜底。"
                        + "如需部门→租户管理员两级审批，请在「管理端 → 审批流定义」中配置。");
    }

    private boolean hasDef(Long tenantId, Long institutionId, String bizType) {
        if (institutionId == null) {
            return false;
        }
        return approvalFlowService.listDefs(tenantId, institutionId).stream()
                .anyMatch(d -> bizType.equals(d.getBizType()) && "ACTIVE".equals(d.getStatus()));
    }

    /** ⑥ 计费：额度是否足以支撑该数字人运行。 */
    private Map<String, Object> checkQuota(AuthUser user) {
        BillingService.QuotaView q = billingService.current(user.getTenantId(), user.getUserId());
        if (q.exhausted()) {
            return check("QUOTA", "计费", BLOCKED,
                    "词元额度已用完（剩余 " + q.left() + "），数字员工无法运行",
                    "购买词元包或申请扩容后再创建",
                    "该成员额度已耗尽，请为其扩容或购买词元包（管理端 → 配额管理），"
                            + "否则数字员工创建后立即不可用。");
        }
        return check("QUOTA", "计费", PASS,
                "额度充足（剩余 " + q.left() + " / 共 " + q.quota() + " 词元，已用 " + q.percent() + "%）");
    }

    // ================================================================== 工具

    private static Map<String, Object> check(String key, String label, String status, String message) {
        return check(key, label, status, message, null, null);
    }

    private static Map<String, Object> check(String key, String label, String status, String message,
                                             String nextAction, String adminScript) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("key", key);
        m.put("label", label);
        m.put("status", status);
        m.put("message", message);
        if (nextAction != null) {
            m.put("nextAction", nextAction);
        }
        if (adminScript != null) {
            m.put("adminScript", adminScript);
        }
        return m;
    }

    private static String str(Object v) {
        return v == null ? null : String.valueOf(v);
    }

    private static List<String> toStringList(JsonNode node) {
        if (node == null || !node.isArray()) {
            return List.of();
        }
        List<String> out = new ArrayList<>();
        node.forEach(n -> out.add(n.asText()));
        return out;
    }
}
