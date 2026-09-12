package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.service.ContentReviewService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 内容审核台（V34）：平台管理员审核租户管理员创建的数字员工 / 专家。
 *
 * <pre>
 * GET  /api/v1/admin/content-reviews?status=PENDING   —— 待审清单（跨租户）
 * POST /api/v1/admin/content-reviews/{type}/{id}/review  —— 通过 / 驳回（body: {approve, note}）
 * </pre>
 *
 * <p>驳回必填意见：没有理由的驳回会让租户管理员反复试错，
 * 与其事后靠猜，不如在接口层强制给一句说明。</p>
 */
@RestController
@RequestMapping("/api/v1/admin/content-reviews")
@RequiredArgsConstructor
public class ContentReviewController {

    private static final String TYPE_WORKER = "worker";
    private static final String TYPE_EXPERT = "expert";

    private final AgentWorkerMapper workerMapper;
    private final AiExpertMapper expertMapper;
    private final ContentReviewService reviewService;

    @GetMapping
    public ApiResponse<Map<String, Object>> list(
            @RequestParam(name = "status", defaultValue = ContentReviewService.PENDING) String status) {
        AuthUser u = requirePlatformAdmin();
        String want = (status == null || status.isBlank())
                ? ContentReviewService.PENDING : status.trim().toUpperCase();

        List<Map<String, Object>> items = new ArrayList<>();
        workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                        .eq(AgentWorker::getAuditStatus, want)
                        .orderByDesc(AgentWorker::getId))
                .forEach(w -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("type", TYPE_WORKER);
                    m.put("id", w.getId());
                    m.put("tenantId", w.getTenantId());
                    m.put("name", w.getName());
                    m.put("summary", w.getDescription());
                    m.put("auditStatus", w.getAuditStatus());
                    m.put("auditNote", w.getAuditNote());
                    m.put("createdBy", w.getCreatedBy());
                    m.put("createdAt", w.getCreatedAt() == null ? null : w.getCreatedAt().toString());
                    items.add(m);
                });
        expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                        .eq(AiExpert::getAuditStatus, want)
                        .orderByDesc(AiExpert::getId))
                .forEach(e -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("type", TYPE_EXPERT);
                    m.put("id", e.getId());
                    m.put("tenantId", e.getTenantId());
                    m.put("name", e.getName());
                    m.put("summary", e.getSummary());
                    m.put("auditStatus", e.getAuditStatus());
                    m.put("auditNote", e.getAuditNote());
                    m.put("createdBy", e.getCreatedBy());
                    m.put("createdAt", e.getCreatedAt() == null ? null : e.getCreatedAt().toString());
                    items.add(m);
                });

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        out.put("status", want);
        out.put("switchOn", reviewService.enabled());
        out.put("reviewer", u.getUsername());
        return ApiResponse.ok(out);
    }

    /** 通过 / 驳回。驳回必须给意见，便于创建者据此修改而不是反复试。 */
    @PostMapping("/{type}/{id}/review")
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

        Map<String, Object> out = new LinkedHashMap<>();
        if (TYPE_WORKER.equals(type)) {
            AgentWorker w = workerMapper.selectById(id);
            if (w == null) {
                throw BizException.notFound("数字员工不存在：" + id);
            }
            w.setAuditStatus(next);
            w.setAuditNote(note);
            w.setReviewedBy(u.getUserId());
            w.setReviewedAt(LocalDateTime.now());
            workerMapper.updateById(w);
            out.put("type", TYPE_WORKER);
            out.put("name", w.getName());
        } else if (TYPE_EXPERT.equals(type)) {
            AiExpert e = expertMapper.selectById(id);
            if (e == null) {
                throw BizException.notFound("专家不存在：" + id);
            }
            e.setAuditStatus(next);
            e.setAuditNote(note);
            e.setReviewedBy(u.getUserId());
            e.setReviewedAt(LocalDateTime.now());
            expertMapper.updateById(e);
            out.put("type", TYPE_EXPERT);
            out.put("name", e.getName());
        } else {
            throw BizException.badRequest("未知内容类型：" + type + "（可选 worker / expert）");
        }
        out.put("id", id);
        out.put("auditStatus", next);
        out.put("auditNote", note);
        return ApiResponse.ok(out);
    }

    private static AuthUser requirePlatformAdmin() {
        AuthUser u = AuthUserContext.require();
        if (!cn.aioa.resource.support.PermissionCatalog.isPlatformAdmin(u)) {
            throw BizException.forbidden("内容审核仅平台管理员可执行");
        }
        return u;
    }
}
