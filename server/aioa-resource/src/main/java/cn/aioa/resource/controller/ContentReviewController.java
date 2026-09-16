package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.ExpertConfig;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.ExpertConfigMapper;
import cn.aioa.resource.service.ContentReviewService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 内容审核台（V34）+ 审核记录中心（V36 需求④）。
 *
 * <pre>
 * GET  /api/v1/admin/content-reviews?status=PENDING&amp;type=all   —— 待审清单（跨租户，平台管理员）
 * POST /api/v1/admin/content-reviews/{type}/{id}/review         —— 通过 / 驳回（body: {approve, note}）
 * GET  /api/v1/admin/review-records?type=&amp;status=&amp;keyword=     —— 审核记录（提交方 + 处理方双边留痕）
 * </pre>
 *
 * <p>覆盖四类内容：数字员工 {@code worker}、AI 专家 {@code expert}、
 * 专家配置片段 {@code expert_config}（V36 需求⑤）、权限授权单 {@code permission_grant}（V36 需求①）。</p>
 *
 * <p><b>审核 vs 记录的分工</b>：{@code content-reviews} 是「待办台」，只处理待审项、仅平台管理员可用；
 * {@code review-records} 是「档案库」，把提交时间、提交人、审核人、审核时间、意见一并列出，
 * 平台管理员看全量、租户管理员看本租户 —— 需求④要的是后者。</p>
 *
 * <p>驳回必填意见：没有理由的驳回会让提交者反复试错，与其事后靠猜，不如在接口层强制给一句说明。</p>
 */
@RestController
@RequestMapping("/api/v1/admin")
@RequiredArgsConstructor
public class ContentReviewController {

    private static final String TYPE_WORKER = "worker";
    private static final String TYPE_EXPERT = "expert";
    private static final String TYPE_EXPERT_CONFIG = "expert_config";
    private static final String TYPE_PERMISSION_GRANT = "permission_grant";
    private static final String TYPE_ALL = "all";

    private static final int MAX_PAGE_SIZE = 100;

    private final AgentWorkerMapper workerMapper;
    private final AiExpertMapper expertMapper;
    private final ExpertConfigMapper expertConfigMapper;
    private final ContentReviewService reviewService;
    private final JdbcTemplate jdbc;

    // ================================================================== 待审清单

    @GetMapping("/content-reviews")
    public ApiResponse<Map<String, Object>> list(
            @RequestParam(name = "status", defaultValue = ContentReviewService.PENDING) String status,
            @RequestParam(name = "type", defaultValue = TYPE_ALL) String type) {
        AuthUser u = requirePlatformAdmin();
        String want = (status == null || status.isBlank() || "ALL".equalsIgnoreCase(status.trim()))
                ? null : status.trim().toUpperCase();
        String typeWanted = (type == null || type.isBlank()) ? TYPE_ALL : type.trim().toLowerCase();

        List<Map<String, Object>> items = new ArrayList<>();
        if (TYPE_ALL.equals(typeWanted) || TYPE_WORKER.equals(typeWanted)) {
            collectWorkers(want, items);
        }
        if (TYPE_ALL.equals(typeWanted) || TYPE_EXPERT.equals(typeWanted)) {
            collectExperts(want, items);
        }
        if (TYPE_ALL.equals(typeWanted) || TYPE_EXPERT_CONFIG.equals(typeWanted)) {
            collectExpertConfigs(want, items);
        }
        items.sort(Comparator.comparing(m -> String.valueOf(m.get("createdAt") == null ? "" : m.get("createdAt")),
                Comparator.reverseOrder()));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        out.put("status", want == null ? "ALL" : want);
        out.put("type", typeWanted);
        out.put("switchOn", reviewService.enabled());
        out.put("reviewer", u.getUsername());
        return ApiResponse.ok(out);
    }

    private void collectWorkers(String want, List<Map<String, Object>> items) {
        LambdaQueryWrapper<AgentWorker> w = new LambdaQueryWrapper<AgentWorker>()
                .orderByDesc(AgentWorker::getId);
        if (want != null) {
            w.eq(AgentWorker::getAuditStatus, want);
        }
        workerMapper.selectList(w).forEach(x -> {
            Map<String, Object> m = baseRow(TYPE_WORKER, x.getId(), x.getTenantId(), x.getName(),
                    x.getDescription(), x.getAuditStatus(), x.getAuditNote(), x.getCreatedBy(),
                    x.getCreatedAt(), x.getReviewedBy(), x.getReviewedAt());
            items.add(m);
        });
    }

    private void collectExperts(String want, List<Map<String, Object>> items) {
        LambdaQueryWrapper<AiExpert> w = new LambdaQueryWrapper<AiExpert>()
                .orderByDesc(AiExpert::getId);
        if (want != null) {
            w.eq(AiExpert::getAuditStatus, want);
        }
        expertMapper.selectList(w).forEach(x -> {
            Map<String, Object> m = baseRow(TYPE_EXPERT, x.getId(), x.getTenantId(), x.getName(),
                    x.getSummary(), x.getAuditStatus(), x.getAuditNote(), x.getCreatedBy(),
                    x.getCreatedAt(), x.getReviewedBy(), x.getReviewedAt());
            items.add(m);
        });
    }

    private void collectExpertConfigs(String want, List<Map<String, Object>> items) {
        LambdaQueryWrapper<ExpertConfig> w = new LambdaQueryWrapper<ExpertConfig>()
                .isNull(ExpertConfig::getDeletedAt)
                .orderByDesc(ExpertConfig::getId);
        if (want != null) {
            w.eq(ExpertConfig::getAuditStatus, want);
        }
        expertConfigMapper.selectList(w).forEach(x -> {
            // 「名称」用「专家key / 作用域」拼，配置片段没有自然名称
            String name = x.getExpertKey() + " · " + x.getScopeType()
                    + (x.getScopeId() != null && x.getScopeId() > 0 ? "#" + x.getScopeId() : "");
            Map<String, Object> m = baseRow(TYPE_EXPERT_CONFIG, x.getId(), x.getTenantId(), name,
                    summarizeConfig(x.getConfigJson()), x.getAuditStatus(), x.getAuditNote(),
                    x.getCreatedBy(), x.getCreatedAt(), x.getReviewedBy(), x.getReviewedAt());
            m.put("scopeType", x.getScopeType());
            m.put("scopeId", x.getScopeId());
            m.put("expertKey", x.getExpertKey());
            items.add(m);
        });
    }

    /** 统一行结构：提交方（createdBy）+ 处理方（reviewedBy）双边留痕。 */
    private Map<String, Object> baseRow(String type, Long id, Long tenantId, String name, String summary,
                                        String auditStatus, String auditNote, Long createdBy,
                                        LocalDateTime createdAt, Long reviewedBy, LocalDateTime reviewedAt) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("type", type);
        m.put("id", id);
        m.put("tenantId", tenantId);
        m.put("name", name);
        m.put("summary", summary);
        m.put("auditStatus", auditStatus);
        m.put("auditNote", auditNote);
        m.put("createdBy", createdBy);
        m.put("createdByName", userName(createdBy));
        m.put("createdAt", createdAt == null ? null : createdAt.toString());
        m.put("reviewedBy", reviewedBy);
        m.put("reviewerName", userName(reviewedBy));
        m.put("reviewedAt", reviewedAt == null ? null : reviewedAt.toString());
        return m;
    }

    // ================================================================== 审核记录（需求④）

    /**
     * 审核记录中心：内容审核（数字员工 / 专家 / 专家配置）+ 权限授权单。
     *
     * <p>平台管理员看全量；租户管理员只看本租户（含本租户各机构），跨租户数据一律不可见。</p>
     */
    @GetMapping("/review-records")
    public ApiResponse<Map<String, Object>> records(
            @RequestParam(name = "type", defaultValue = TYPE_ALL) String type,
            @RequestParam(name = "status", defaultValue = "ALL") String status,
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "tenantId", required = false) Long tenantId,
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "20") int size) {
        AuthUser u = requireReviewRecordReader();
        boolean platform = cn.aioa.security.PermissionCatalog.isPlatformAdmin(u);
        // 租户管理员硬绑本租户；平台管理员可显式切换，缺省全量。
        // 注意：这里**不能**写成三元表达式 —— `cond ? Long : (x == null ? 0L : x)` 会触发
        // 二元数值提升，把 Long 拆箱成 long，平台管理员不传 tenantId 时直接 NPE（实测 500）。
        Long scopeTenant;
        if (platform) {
            scopeTenant = tenantId;                      // null = 全量，不做租户过滤
        } else {
            scopeTenant = u.getTenantId() == null ? 0L : u.getTenantId();
        }
        String typeWanted = (type == null || type.isBlank()) ? TYPE_ALL : type.trim().toLowerCase();
        String statusWanted = (status == null || status.isBlank() || "ALL".equalsIgnoreCase(status.trim()))
                ? null : status.trim().toUpperCase();
        String kw = keyword == null || keyword.isBlank() ? null : keyword.trim().toLowerCase();

        List<Map<String, Object>> items = new ArrayList<>();
        if (TYPE_ALL.equals(typeWanted) || TYPE_WORKER.equals(typeWanted)
                || TYPE_EXPERT.equals(typeWanted) || TYPE_EXPERT_CONFIG.equals(typeWanted)) {
            collectRecords(items, scopeTenant, TYPE_WORKER, statusWanted);
            collectRecords(items, scopeTenant, TYPE_EXPERT, statusWanted);
            collectRecords(items, scopeTenant, TYPE_EXPERT_CONFIG, statusWanted);
        }
        if (TYPE_ALL.equals(typeWanted) || TYPE_PERMISSION_GRANT.equals(typeWanted)) {
            collectGrants(items, scopeTenant, statusWanted);
        }

        if (kw != null) {
            items.removeIf(m -> !contains(m, kw));
        }
        Map<String, Object> stats = new LinkedHashMap<>();
        for (Map<String, Object> m : items) {
            String st = String.valueOf(m.get("auditStatus"));
            stats.merge(st, 1, (a, b) -> (Integer) a + (Integer) b);
        }
        items.sort(Comparator.comparing(m -> String.valueOf(m.get("sortAt") == null ? "" : m.get("sortAt")),
                Comparator.reverseOrder()));

        int total = items.size();
        int p = Math.max(1, page);
        int s = Math.max(1, Math.min(MAX_PAGE_SIZE, size));
        int from = Math.min((p - 1) * s, total);
        int to = Math.min(from + s, total);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items.subList(from, to));
        out.put("total", total);
        out.put("page", p);
        out.put("size", s);
        out.put("stats", stats);
        out.put("scope", platform ? "ALL_TENANTS" : "TENANT");
        out.put("tenantId", scopeTenant);
        return ApiResponse.ok(out);
    }

    /** 复用待审清单的装配逻辑，再抽成「记录」语义（带 sortAt 供排序）。 */
    private void collectRecords(List<Map<String, Object>> out, Long scopeTenant, String type, String status) {
        List<Map<String, Object>> tmp = new ArrayList<>();
        switch (type) {
            case TYPE_WORKER -> collectWorkers(status, tmp);
            case TYPE_EXPERT -> collectExperts(status, tmp);
            case TYPE_EXPERT_CONFIG -> collectExpertConfigs(status, tmp);
            default -> {
                return;
            }
        }
        for (Map<String, Object> m : tmp) {
            if (scopeTenant != null && !scopeTenant.equals(asLong(m.get("tenantId")))) {
                continue;
            }
            // 记录视图下「已终态」才叫审核记录；PENDING 也保留，供「待处理」筛选
            m.put("source", "content_review");
            m.put("sortAt", m.get("reviewedAt") != null ? m.get("reviewedAt") : m.get("createdAt"));
            out.add(m);
        }
    }

    /** 权限授权单（需求①）转成统一的审核记录结构。跨模块只读查询，表格小、字段稳定。 */
    private void collectGrants(List<Map<String, Object>> out, Long scopeTenant, String status) {
        StringBuilder sql = new StringBuilder(
                "SELECT id, tenant_id, institution_id, department_id, user_id, applicant_name, "
                        + "permission_code, target_worker_type, reason, status, order_id, audit_note, "
                        + "granted_by, granted_at, created_at FROM permission_grant WHERE deleted_at IS NULL");
        List<Object> args = new ArrayList<>();
        if (scopeTenant != null) {
            sql.append(" AND tenant_id = ?");
            args.add(scopeTenant);
        }
        if (status != null) {
            sql.append(" AND status = ?");
            args.add(status);
        }
        sql.append(" ORDER BY id DESC LIMIT 500");
        for (Map<String, Object> r : jdbc.queryForList(sql.toString(), args.toArray())) {
            Map<String, Object> m = new LinkedHashMap<>();
            Long id = asLong(r.get("id"));
            m.put("type", TYPE_PERMISSION_GRANT);
            m.put("id", id);
            m.put("tenantId", asLong(r.get("tenant_id")));
            m.put("institutionId", asLong(r.get("institution_id")));
            m.put("departmentId", asLong(r.get("department_id")));
            m.put("name", String.valueOf(r.get("applicant_name") == null ? "" : r.get("applicant_name"))
                    + " 申请 " + r.get("permission_code"));
            m.put("summary", r.get("reason"));
            m.put("permissionCode", r.get("permission_code"));
            m.put("targetWorkerType", r.get("target_worker_type"));
            // 授权单的状态机与内容审核不同（PENDING/ACTIVE/REJECTED/REVOKED），统一挂到 auditStatus 便于前端复用
            m.put("auditStatus", r.get("status"));
            m.put("auditNote", r.get("audit_note"));
            m.put("orderId", asLong(r.get("order_id")));
            m.put("createdBy", asLong(r.get("user_id")));
            m.put("createdByName", r.get("applicant_name"));
            m.put("createdAt", str(r.get("created_at")));
            m.put("reviewedBy", asLong(r.get("granted_by")));
            m.put("reviewerName", userName(asLong(r.get("granted_by"))));
            m.put("reviewedAt", str(r.get("granted_at")));
            m.put("source", "permission_grant");
            m.put("sortAt", r.get("granted_at") != null ? str(r.get("granted_at")) : str(r.get("created_at")));
            out.add(m);
        }
    }

    // ================================================================== 审核动作

    /** 通过 / 驳回。驳回必须给意见，便于提交者据此修改而不是反复试。 */
    @PostMapping("/content-reviews/{type}/{id}/review")
    public ApiResponse<Map<String, Object>> review(@PathVariable String type, @PathVariable Long id,
                                                   @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = requirePlatformAdmin();
        boolean approve = body == null || !Boolean.FALSE.equals(body.get("approve"));
        Object noteObj = body == null ? null : body.get("note");
        String note = noteObj == null ? null : String.valueOf(noteObj).trim();
        if (!approve && (note == null || note.isEmpty())) {
            throw BizException.badRequest("驳回必须填写审核意见");
        }
        String next = approve ? ContentReviewService.APPROVED : ContentReviewService.REJECTED;
        LocalDateTime now = LocalDateTime.now();

        Map<String, Object> out = new LinkedHashMap<>();
        if (TYPE_WORKER.equals(type)) {
            AgentWorker w = workerMapper.selectById(id);
            if (w == null) {
                throw BizException.notFound("数字员工不存在：" + id);
            }
            w.setAuditStatus(next);
            w.setAuditNote(note);
            w.setReviewedBy(u.getUserId());
            w.setReviewedAt(now);
            workerMapper.updateById(w);
            out.put("name", w.getName());
        } else if (TYPE_EXPERT.equals(type)) {
            AiExpert e = expertMapper.selectById(id);
            if (e == null) {
                throw BizException.notFound("专家不存在：" + id);
            }
            e.setAuditStatus(next);
            e.setAuditNote(note);
            e.setReviewedBy(u.getUserId());
            e.setReviewedAt(now);
            expertMapper.updateById(e);
            out.put("name", e.getName());
        } else if (TYPE_EXPERT_CONFIG.equals(type)) {
            ExpertConfig c = expertConfigMapper.selectById(id);
            if (c == null || c.getDeletedAt() != null) {
                throw BizException.notFound("专家配置不存在：" + id);
            }
            c.setAuditStatus(next);
            c.setAuditNote(note);
            c.setReviewedBy(u.getUserId());
            c.setReviewedAt(now);
            expertConfigMapper.updateById(c);
            out.put("name", c.getExpertKey() + " · " + c.getScopeType());
        } else {
            throw BizException.badRequest("未知内容类型：" + type
                    + "（可选 worker / expert / expert_config）");
        }
        out.put("type", type);
        out.put("id", id);
        out.put("auditStatus", next);
        out.put("auditNote", note);
        out.put("reviewer", u.getUsername());
        out.put("reviewedAt", now.toString());
        return ApiResponse.ok(out);
    }

    // ================================================================== 内部

    private static AuthUser requirePlatformAdmin() {
        AuthUser u = AuthUserContext.require();
        if (!cn.aioa.security.PermissionCatalog.isPlatformAdmin(u)) {
            throw BizException.forbidden("内容审核仅平台管理员可执行");
        }
        return u;
    }

    /** 审核记录的读权限：平台管理员（全量）或租户管理员（本租户）。 */
    private static AuthUser requireReviewRecordReader() {
        AuthUser u = AuthUserContext.require();
        if (cn.aioa.security.PermissionCatalog.isPlatformAdmin(u)
                || cn.aioa.security.PermissionCatalog.hasRole(u, "ROLE_TENANT_ADMIN")) {
            return u;
        }
        throw BizException.forbidden("审核记录仅平台管理员或租户管理员可查看");
    }

    /** userId → 显示名（跨模块只读，回查 sys_user）。 */
    private String userName(Long userId) {
        if (userId == null || userId <= 0) {
            return null;
        }
        try {
            List<Map<String, Object>> rows = jdbc.queryForList(
                    "SELECT nickname, username FROM sys_user WHERE id = ? LIMIT 1", userId);
            if (rows.isEmpty()) {
                return "用户#" + userId;
            }
            Object nick = rows.get(0).get("nickname");
            Object uname = rows.get(0).get("username");
            return nick != null && !String.valueOf(nick).isBlank() ? String.valueOf(nick)
                    : (uname == null ? "用户#" + userId : String.valueOf(uname));
        } catch (Exception e) {
            return "用户#" + userId;
        }
    }

    private static boolean contains(Map<String, Object> m, String lowerKeyword) {
        for (String k : List.of("name", "summary", "auditNote", "permissionCode", "createdByName", "reviewerName")) {
            Object v = m.get(k);
            if (v != null && String.valueOf(v).toLowerCase().contains(lowerKeyword)) {
                return true;
            }
        }
        return false;
    }

    /** 配置片段摘要：只给前若干字符，避免记录页把大 JSON 铺开。 */
    private static String summarizeConfig(String json) {
        if (json == null) {
            return null;
        }
        String s = json.replaceAll("\\s+", " ").trim();
        return s.length() > 160 ? s.substring(0, 160) + "…" : s;
    }

    private static Long asLong(Object v) {
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

    private static String str(Object v) {
        return v == null ? null : String.valueOf(v);
    }
}
