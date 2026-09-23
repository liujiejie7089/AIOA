package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgFeedback;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgFeedbackMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 投诉与建议服务（V63）。
 *
 * <p>核心是<b>接收人解析</b>这一件事：用户只表达「我要反馈」，系统负责找到「谁来接」。</p>
 *
 * <h3>为什么是逐级上溯，而不是直接找租户管理员</h3>
 * <p>用户的原话是「反馈给<b>本部门的管理员</b>」——部门管理员最了解本部门的事，
 * 由他处理质量最高。但现实里部门经常没配负责人，机构也可能没配管理员。
 * 若在「找不到部门管理员」时直接报错或静默成功，用户会以为反馈送达了 ——
 * 这是最坏的结果（<b>不可逆动作绝不静默成功</b>）。因此设计为：</p>
 * <pre>
 *   本部门负责人 → 本部门正职 → 本机构管理员 → 租户管理员 → 无（NONE，待人工指派）
 * </pre>
 * <p>并把命中的层级与原因写进记录、把「无」也作为一等状态返回给用户。</p>
 *
 * <h3>通知为什么要落 notification 表，而不是调 NotificationService</h3>
 * <p>{@code aioa-org} 刻意不依赖 {@code aioa-resource}（模块边界，见 {@code OrgStatMapper} 注释），
 * 所以这里走既有的 {@code insertNotification} 原始写入 —— 用户端通知列表读的就是这张表，
 * 站内送达成立。代价是不走 {@code NotificationService} 的通道分发（邮件/Webhook），
 * 本阶段未启用那类通道，不构成缺口。</p>
 */
@Service
@RequiredArgsConstructor
public class FeedbackService {

    /** 内容长度上限 —— 与表结构 VARCHAR(2000) 一致，超长在校验期就拒绝，不留给数据库报错。 */
    public static final int MAX_CONTENT = 2000;
    public static final int MAX_REPLY = 2000;

    private final OrgFeedbackMapper mapper;
    private final OrgStatMapper statMapper;
    private final OrgMemberMapper memberMapper;
    private final OrgDepartmentMapper deptMapper;
    private final OrgGuard guard;
    private final AuditRecorder audit;

    // ==================== 接收人解析 ====================

    /**
     * 一条反馈的接收人及其命中层级。
     *
     * @param userId 接收人；为 null 表示逐级上溯到底仍无人可派
     * @param scope  {@link OrgFeedback#SCOPE_DEPT} / {@link OrgFeedback#SCOPE_INSTITUTION}
     *               / {@link OrgFeedback#SCOPE_TENANT} / {@link OrgFeedback#SCOPE_NONE}
     * @param reason 命中原因（可读，便于追责与排障）
     */
    public record Assignee(Long userId, String name, String scope, String reason) {

        public boolean resolved() {
            return userId != null;
        }
    }

    /**
     * 逐级上溯解析接收人。
     *
     * <p>顺序不可调换：越靠前越贴近提交人，处理质量越高。</p>
     */
    public Assignee resolveAssignee(Long departmentId, Long institutionId, Long tenantId) {
        if (departmentId != null && departmentId > 0) {
            Long leader = mapper.selectDeptLeaderUserId(departmentId);
            if (leader != null) {
                return new Assignee(leader, nameOf(leader), OrgFeedback.SCOPE_DEPT, "本部门负责人");
            }
            Long principal = mapper.selectDeptPrincipalUserId(departmentId);
            if (principal != null) {
                return new Assignee(principal, nameOf(principal), OrgFeedback.SCOPE_DEPT,
                        "本部门正职（duty_code=DEPT_PRINCIPAL）");
            }
        }
        if (institutionId != null && institutionId > 0) {
            Long admin = mapper.selectInstitutionAdminUserId(institutionId);
            if (admin != null) {
                return new Assignee(admin, nameOf(admin), OrgFeedback.SCOPE_INSTITUTION,
                        "本部门未配置负责人，上溯至本机构管理员");
            }
        }
        Long tenantAdmin = statMapper.selectFirstUserIdOfRole(tenantId, OrgGuard.ROLE_TENANT_ADMIN);
        if (tenantAdmin != null) {
            return new Assignee(tenantAdmin, nameOf(tenantAdmin), OrgFeedback.SCOPE_TENANT,
                    "本部门与本机构均未配置管理员，上溯至租户管理员");
        }
        return new Assignee(null, null, OrgFeedback.SCOPE_NONE,
                "本部门、本机构、本租户均无管理员可派，待平台人工指派");
    }

    // ==================== 提交 ====================

    /**
     * 提交一条投诉 / 建议。
     *
     * <p>返回体里<b>必须</b>包含 {@code delivered} 与 {@code assigneeReason} ——
     * 用户有权知道这条反馈到底有没有送到人手上、送给了谁。
     * 只回一句「提交成功」而实际无人接收，是不可接受的。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> submit(AuthUser actor, Map<String, Object> body) {
        guard.requireOrgUser();
        long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();

        String content = Vals.require(body, "content", "反馈内容").trim();
        if (content.length() > MAX_CONTENT) {
            throw BizException.badRequest("反馈内容不得超过 " + MAX_CONTENT + " 字，当前 " + content.length() + " 字");
        }
        String category = normalizeCategory(Vals.str(body, "category"));
        String contact = Vals.str(body, "contact");
        boolean anonymous = Vals.bool(body, "anonymous", false);

        // 归属取登录人的主身份；未归属机构/部门时降级上溯（而不是直接拒绝 ——
        // 未纳管账号也可能有真实诉求，拒绝只会让人无处说）
        OrgMember me = primaryMemberOf(actor.getUserId());
        Long institutionId = me == null || me.getInstitutionId() == null ? 0L : me.getInstitutionId();
        Long departmentId = me == null || me.getDepartmentId() == null ? 0L : me.getDepartmentId();
        String deptName = departmentId > 0 ? nameOfDept(departmentId) : null;

        Assignee assignee = resolveAssignee(departmentId, institutionId, tenantId);

        OrgFeedback f = new OrgFeedback();
        f.setTenantId(tenantId);
        f.setInstitutionId(institutionId);
        f.setDepartmentId(departmentId);
        f.setCategory(category);
        f.setContent(content);
        f.setContact(contact);
        f.setAnonymous(anonymous);
        f.setStatus(OrgFeedback.STATUS_PENDING);
        f.setSubmitterUserId(actor.getUserId());
        f.setSubmitterName(displayNameOf(actor.getUserId(), actor));
        f.setSubmitterDeptName(deptName);
        f.setAssigneeUserId(assignee.userId());
        f.setAssigneeName(assignee.name());
        f.setAssigneeScope(assignee.scope());
        f.setAssigneeReason(assignee.reason());
        f.setCreatedAt(LocalDateTime.now());
        f.setCreatedBy(actor.getUserId());
        mapper.insert(f);

        if (assignee.resolved()) {
            notifyAssignee(tenantId, f, assignee, anonymous);
        }

        audit.record(tenantId, institutionId, actor, "FEEDBACK_SUBMIT", "ORG_FEEDBACK", f.getId(),
                "提交" + categoryLabel(category) + "（派给 " + assignee.scope()
                        + (assignee.name() == null ? "" : "：" + assignee.name()) + "）",
                null, f);

        Map<String, Object> out = view(f, false);
        out.put("delivered", assignee.resolved());
        out.put("deliveryNote", assignee.resolved()
                ? "已送达" + scopeLabel(assignee.scope()) + "：" + assignee.name()
                : "已记录，但逐级上溯后暂无可派管理员，待平台人工指派");
        return out;
    }

    /** 通知接收人「有新反馈」。通知内容不含匿名提交者的姓名。 */
    private void notifyAssignee(long tenantId, OrgFeedback f, Assignee assignee, boolean anonymous) {
        String who = anonymous ? "匿名用户" : f.getSubmitterName();
        String title = "新的" + categoryLabel(f.getCategory()) + "待处理";
        String content = who + (f.getSubmitterDeptName() == null ? "" : "（" + f.getSubmitterDeptName() + "）")
                + "提交了" + categoryLabel(f.getCategory()) + "：" + brief(f.getContent());
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("tenantId", tenantId);
        row.put("userId", assignee.userId());
        row.put("type", "FEEDBACK");
        row.put("title", title);
        row.put("content", content);
        row.put("refId", f.getId());
        statMapper.insertNotification(row);
    }

    // ==================== 查询 ====================

    /** 我提交过的反馈（含答复）。 */
    public Map<String, Object> mine(AuthUser actor) {
        guard.requireOrgUser();
        long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();
        List<OrgFeedback> rows = mapper.selectMine(tenantId, actor.getUserId());
        List<Map<String, Object>> items = new ArrayList<>();
        for (OrgFeedback f : rows) {
            items.add(view(f, false));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", items.size());
        out.put("pending", items.stream().filter(i -> OrgFeedback.STATUS_PENDING.equals(i.get("status"))).count());
        out.put("items", items);
        out.put("note", "提交人可看到完整记录与答复；对上级是否匿名由提交时选择决定。");
        return out;
    }

    /**
     * 派给我的反馈（「收到的建议」）。
     *
     * <p>只有接收人本人能看到这条清单 —— 名单是按 {@code assignee_user_id} 过滤的，
     * 不做「机构内互相可见」：反馈里可能含敏感内容，可见面越小越安全。</p>
     */
    public Map<String, Object> inbox(AuthUser actor, String status) {
        guard.requireOrgUser();
        long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();
        String st = status == null || status.isBlank() ? null : status.trim().toUpperCase();
        List<OrgFeedback> rows = mapper.selectMyInbox(tenantId, actor.getUserId(), st);
        List<Map<String, Object>> items = new ArrayList<>();
        for (OrgFeedback f : rows) {
            // 上级查看时按匿名规则遮蔽姓名
            items.add(view(f, true));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", items.size());
        out.put("pending", mapper.countMyPending(tenantId, actor.getUserId()));
        out.put("items", items);
        out.put("status", st);
        return out;
    }

    // ==================== 回复 ====================

    /** 回复一条反馈。提交人将收到站内通知，并在「我的提交」看到答复。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> reply(AuthUser actor, Long id, Map<String, Object> body) {
        guard.requireOrgUser();
        long tenantId = actor.getTenantId() == null ? 0L : actor.getTenantId();
        String content = Vals.require(body, "content", "答复内容").trim();
        if (content.length() > MAX_REPLY) {
            throw BizException.badRequest("答复内容不得超过 " + MAX_REPLY + " 字，当前 " + content.length() + " 字");
        }

        OrgFeedback f = mapper.selectById(id);
        // 跨租户 / 不存在的 id 一律 404，不泄露存在性（与 OrgAdminController 同口径）
        if (f == null || f.getDeletedAt() != null || !Long.valueOf(tenantId).equals(f.getTenantId())) {
            throw BizException.notFound("反馈不存在或无权访问");
        }
        if (OrgFeedback.STATUS_CLOSED.equals(f.getStatus())) {
            throw BizException.badRequest("该反馈已关闭，不能再回复");
        }
        assertCanReply(actor, f);

        f.setStatus(OrgFeedback.STATUS_REPLIED);
        f.setReplyContent(content);
        f.setRepliedBy(actor.getUserId());
        f.setRepliedByName(displayNameOf(actor.getUserId(), actor));
        f.setRepliedAt(LocalDateTime.now());
        f.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(f);

        // 答复送还给提交人 —— 这是「闭环」的最后一跳，缺了它用户永远看不到结果
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("tenantId", tenantId);
        row.put("userId", f.getSubmitterUserId());
        row.put("type", "FEEDBACK");
        row.put("title", "你的" + categoryLabel(f.getCategory()) + "已被回复");
        row.put("content", brief(content));
        row.put("refId", f.getId());
        statMapper.insertNotification(row);

        audit.record(tenantId, f.getInstitutionId(), actor, "FEEDBACK_REPLY", "ORG_FEEDBACK", f.getId(),
                "回复" + categoryLabel(f.getCategory()) + "（提交人 " + f.getSubmitterName() + "）", null, f);
        return view(f, false);
    }

    /**
     * 谁可以回复。
     *
     * <p>三类人：<b>接收人本人</b>（正常路径）；<b>同租户的管理员</b>（接收人休假/离职时的督办口子，
     * 否则反馈会永久卡住）；<b>同机构的企业管理员</b>（本机构内的兜底）。
     * 其余一律 404，不区分「不存在」与「无权」。</p>
     */
    private void assertCanReply(AuthUser actor, OrgFeedback f) {
        if (actor.getUserId() != null && actor.getUserId().equals(f.getAssigneeUserId())) {
            return;
        }
        if (OrgGuard.hasRole(actor, OrgGuard.ROLE_TENANT_ADMIN) || OrgGuard.hasRole(actor, OrgGuard.ROLE_ADMIN)) {
            return;
        }
        if (OrgGuard.hasRole(actor, OrgGuard.ROLE_ORG_ADMIN)) {
            Long myInst = guard.resolveInstitutionId(actor.getUserId());
            if (myInst != null && myInst.equals(f.getInstitutionId())) {
                return;
            }
        }
        throw BizException.notFound("反馈不存在或无权访问");
    }

    // ==================== 组装 ====================

    /**
     * 视图化。
     *
     * @param forAssignee 以「接收人/上级」视角渲染：此时匿名记录不展示提交人姓名。
     *                    提交人自己的视角永远看得到自己（匿名是对上级匿名，不是对自己）。
     */
    private Map<String, Object> view(OrgFeedback f, boolean forAssignee) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", f.getId());
        m.put("category", f.getCategory());
        m.put("categoryLabel", categoryLabel(f.getCategory()));
        m.put("content", f.getContent());
        m.put("status", f.getStatus());
        m.put("statusLabel", statusLabel(f.getStatus()));
        boolean anon = Boolean.TRUE.equals(f.getAnonymous());
        m.put("anonymous", anon);
        m.put("submitterName", anon && forAssignee ? "匿名用户" : f.getSubmitterName());
        m.put("submitterDeptName", f.getSubmitterDeptName());
        m.put("departmentId", f.getDepartmentId());
        m.put("institutionId", f.getInstitutionId());
        m.put("assigneeName", f.getAssigneeName());
        m.put("assigneeScope", f.getAssigneeScope());
        m.put("assigneeScopeLabel", scopeLabel(f.getAssigneeScope()));
        m.put("assigneeReason", f.getAssigneeReason());
        m.put("replyContent", f.getReplyContent());
        m.put("repliedByName", f.getRepliedByName());
        m.put("repliedAt", f.getRepliedAt() == null ? null : f.getRepliedAt().toString());
        m.put("createdAt", f.getCreatedAt() == null ? null : f.getCreatedAt().toString());
        // 联系方式只给接收方——避免在清单里把用户联系方式扩散给无关的人
        if (forAssignee) {
            m.put("contact", f.getContact());
        }
        return m;
    }

    // ==================== 小工具 ====================

    /** 取登录人的「主身份」成员行：is_primary=1 优先，其次 id 最小，保证同一人结果确定。 */
    private OrgMember primaryMemberOf(Long userId) {
        if (userId == null) {
            return null;
        }
        List<OrgMember> rows = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getUserId, userId)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByDesc(OrgMember::getIsPrimary)
                .orderByAsc(OrgMember::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private String nameOf(Long userId) {
        if (userId == null) {
            return null;
        }
        Map<String, Object> u = statMapper.selectUserName(userId);
        return u == null ? null : String.valueOf(u.get("name"));
    }

    /**
     * 「这个人叫什么」——组织域的姓名口径。
     *
     * <p><b>为什么不用 {@code AuditRecorder.displayName(actor)}</b>：它读的是
     * {@link AuthUser#getNickname()}，而本系统签发的令牌<b>不携带 nickname 声明</b>
     * （{@code aioa-security} 从不设置该字段），因此请求期它恒为 null，最终回落成
     * <b>登录名</b>。把登录名当作「提交人姓名」展示在用户面前，是把内部标识当业务数据的典型错误
     * （新人账号 name=「李思远」而 username=「fagai_li」，反馈记录会显示后者）。</p>
     *
     * <p>组织域里姓名的权威来源是 {@code org_member.name}（用工时录入的那个）；
     * 没有成员行时（如租户管理员不在任何机构）才回落到账号名。</p>
     */
    private String displayNameOf(Long userId, AuthUser fallbackActor) {
        OrgMember m = primaryMemberOf(userId);
        if (m != null && m.getName() != null && !m.getName().isBlank()) {
            return m.getName();
        }
        return AuditRecorder.displayName(fallbackActor);
    }

    private String nameOfDept(Long departmentId) {
        OrgDepartment d = deptMapper.selectById(departmentId);
        return d == null ? null : d.getName();
    }

    private static String normalizeCategory(String raw) {
        if (raw == null || raw.isBlank()) {
            return OrgFeedback.CATEGORY_ADVICE;
        }
        String c = raw.trim().toUpperCase();
        return switch (c) {
            case OrgFeedback.CATEGORY_COMPLAINT, OrgFeedback.CATEGORY_ADVICE, OrgFeedback.CATEGORY_BUG,
                 OrgFeedback.CATEGORY_SERVICE, OrgFeedback.CATEGORY_OTHER -> c;
            // 中文直接传进来也认（用户端就是中文标签），但只认全等，不做模糊猜测
            default -> switch (c) {
                case "投诉" -> OrgFeedback.CATEGORY_COMPLAINT;
                case "建议" -> OrgFeedback.CATEGORY_ADVICE;
                case "功能异常", "故障" -> OrgFeedback.CATEGORY_BUG;
                case "服务态度" -> OrgFeedback.CATEGORY_SERVICE;
                case "其他" -> OrgFeedback.CATEGORY_OTHER;
                default -> OrgFeedback.CATEGORY_ADVICE;
            };
        };
    }

    public static String categoryLabel(String category) {
        if (category == null) {
            return "建议";
        }
        return switch (category) {
            case OrgFeedback.CATEGORY_COMPLAINT -> "投诉";
            case OrgFeedback.CATEGORY_BUG -> "功能异常";
            case OrgFeedback.CATEGORY_SERVICE -> "服务态度";
            case OrgFeedback.CATEGORY_OTHER -> "其他";
            default -> "建议";
        };
    }

    public static String statusLabel(String status) {
        if (status == null) {
            return "待处理";
        }
        return switch (status) {
            case OrgFeedback.STATUS_REPLIED -> "已回复";
            case OrgFeedback.STATUS_CLOSED -> "已关闭";
            default -> "待处理";
        };
    }

    public static String scopeLabel(String scope) {
        if (scope == null) {
            return "未指派";
        }
        return switch (scope) {
            case OrgFeedback.SCOPE_DEPT -> "本部门管理员";
            case OrgFeedback.SCOPE_INSTITUTION -> "本机构管理员";
            case OrgFeedback.SCOPE_TENANT -> "租户管理员";
            default -> "待人工指派";
        };
    }

    private static String brief(String s) {
        if (s == null) {
            return "";
        }
        String t = s.replace('\n', ' ').replace('\r', ' ').replaceAll("\\s+", " ").trim();
        return t.length() > 60 ? t.substring(0, 60) + "…" : t;
    }
}
