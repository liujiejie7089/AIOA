package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.resource.service.KbFileParser;
import cn.aioa.resource.service.KbService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.MediaType;

import java.util.List;
import java.util.Map;

/**
 * 用户端知识库（FR-F）：上传入库、三态清单、失败重试、删除留痕、检索测试。
 *
 * GET    /api/v1/kb/documents              —— 我的资料（默认）
 * GET    /api/v1/kb/documents?scope=tenant —— 租户全部资料（仅租户管理员）
 * POST   /api/v1/kb/documents              —— 上传（携带正文则同步切片入库）
 * POST   /api/v1/kb/documents/{id}/retry   —— 失败重试
 * DELETE /api/v1/kb/documents/{id}         —— 删除资料（留痕）
 * GET    /api/v1/kb/search?q=              —— 检索测试（返回原文片段）
 */
@RestController
@RequestMapping("/api/v1/kb")
@RequiredArgsConstructor
public class KbController {

    private final KbService kbService;
    private final KbFileParser fileParser;
    private final ActivityLogService activityLogService;

    public record DocView(Long id, String name, String icon, String state, Long sizeBytes,
                          Long ownerUserId, String scope, Integer chunkCount, String errorMsg,
                          String createdAt) {

        static DocView from(KbDocument d) {
            return new DocView(d.getId(), d.getDocName(), d.getIcon(),
                    d.getState() == null ? "wait" : d.getState().toLowerCase(),
                    d.getSizeBytes(), d.getUserId(),
                    d.getScope() == null ? "PERSONAL" : d.getScope(),
                    d.getChunkCount(), d.getErrorMsg(),
                    d.getCreatedAt() == null ? null : d.getCreatedAt().toString());
        }
    }

    public record UploadRequest(String name, String icon, Long sizeBytes, String content, String scope) {
    }

    public record HitView(Long docId, String docName, String snippet, Integer chunkIndex) {
    }

    @GetMapping("/documents")
    public ApiResponse<List<DocView>> list(@RequestParam(name = "scope", required = false) String scope) {
        AuthUser user = AuthUserContext.require();
        List<KbDocument> docs;
        if ("tenant".equalsIgnoreCase(scope)) {
            // 租户视角：仅租户管理员（手动检查，同 ApprovalController 的 403 语义）
            if (!user.getRoles().contains("ROLE_ADMIN")) {
                throw BizException.forbidden("租户资料总览仅租户管理员可访问");
            }
            docs = kbService.listTenant(user.getTenantId());
        } else {
            docs = kbService.list(user.getTenantId(), user.getUserId());
        }
        return ApiResponse.ok(docs.stream().map(DocView::from).toList());
    }

    @PostMapping("/documents")
    public ApiResponse<DocView> upload(@RequestBody(required = false) UploadRequest body) {
        AuthUser user = AuthUserContext.require();
        if (body == null || body.name() == null || body.name().isBlank()) {
            throw BizException.badRequest("资料名称不能为空");
        }
        KbDocument doc = kbService.register(user.getTenantId(), user.getUserId(),
                body.name().trim(), body.icon(), body.sizeBytes(), body.content(), body.scope());
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "上传资料（" + doc.getDocName() + "）", "ok", "成功");
        return ApiResponse.ok(DocView.from(doc));
    }

    /**
     * 文件上传入库（FR-F1）：接收 pdf/docx/doc/xlsx/xls/txt 等文件，解析正文后切片入库。
     * 解析成功置 OK，失败置 FAILED 并带 errorMsg（用户端可重试或重新上传）。
     */
    @PostMapping(value = "/documents/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<DocView> uploadFile(@RequestPart("file") MultipartFile file,
                                           @RequestParam(name = "scope", required = false) String scope) {
        AuthUser user = AuthUserContext.require();
        if (file == null || file.isEmpty()) {
            throw BizException.badRequest("请选择要上传的文件");
        }
        String name = file.getOriginalFilename();
        if (name == null || name.isBlank()) {
            throw BizException.badRequest("文件名无效");
        }
        byte[] bytes;
        try {
            bytes = file.getBytes();
        } catch (Exception e) {
            throw BizException.badRequest("读取文件失败：" + e.getMessage());
        }
        if (bytes.length > KbFileParser.MAX_BYTES) {
            throw BizException.badRequest("文件超过 50MB 上限，请拆分后上传");
        }
        String text = fileParser.parse(name, bytes);
        KbDocument doc = kbService.register(user.getTenantId(), user.getUserId(),
                name.trim(), null, (long) bytes.length, text, scope);
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "上传资料（" + doc.getDocName() + "）", doc.getState(), doc.getErrorMsg());
        return ApiResponse.ok(DocView.from(doc));
    }

    /** 修改资料：重命名 / 可见范围（PERSONAL 个人、TENANT 租户共享）。 */
    @PutMapping("/documents/{id}")
    public ApiResponse<DocView> update(@PathVariable Long id, @RequestBody(required = false) Map<String, String> body) {
        AuthUser user = AuthUserContext.require();
        boolean admin = user.getRoles().contains("ROLE_ADMIN");
        KbDocument exist0 = kbService.findOne(id);
        if (exist0 == null) {
            throw BizException.notFound("资料不存在：" + id);
        }
        if (exist0.getTenantId() == null || exist0.getTenantId().longValue() != user.getTenantId().longValue()) {
            throw BizException.forbidden("无权操作其他租户的资料");
        }
        if (!admin && !exist0.getUserId().equals(user.getUserId())) {
            throw BizException.forbidden("只能修改本人上传的资料");
        }
        String name = body == null ? null : body.get("name");
        String scope = body == null ? null : body.get("scope");
        KbDocument doc = kbService.update(id, name, scope);
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "修改资料（" + doc.getDocName() + "）", "ok", doc.getScope());
        return ApiResponse.ok(DocView.from(doc));
    }

    /** 解析失败后重试入库（FR-F2）。 */
    @PostMapping("/documents/{id}/retry")
    public ApiResponse<DocView> retry(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        KbDocument exist0 = kbService.findOne(id);
        if (exist0 == null) {
            throw BizException.notFound("资料不存在：" + id);
        }
        if (exist0.getTenantId() == null || exist0.getTenantId().longValue() != user.getTenantId().longValue()) {
            throw BizException.forbidden("无权操作其他租户的资料");
        }
        if (!isVisible(user, exist0)) {
            throw BizException.forbidden("只能重试本人或本租户的资料");
        }
        KbDocument doc = kbService.retry(id);
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "重试入库（" + doc.getDocName() + "）", "ok", doc.getState());
        return ApiResponse.ok(DocView.from(doc));
    }

    /** 删除资料（逻辑删除资料与切片，留痕）。 */
    @DeleteMapping("/documents/{id}")
    public ApiResponse<Map<String, Object>> remove(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        boolean admin = user.getRoles().contains("ROLE_ADMIN");
        KbDocument doc = kbService.findOne(id);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + id);
        }
        // 跨租户隔离：禁止删除其他租户的资料
        if (doc.getTenantId() == null || doc.getTenantId().longValue() != user.getTenantId().longValue()) {
            throw BizException.forbidden("无权操作其他租户的资料");
        }
        // 管理员可删除本租户任意资料；普通用户只能删自己的
        if (!admin && !doc.getUserId().equals(user.getUserId())) {
            throw BizException.forbidden("只能删除本人上传的资料");
        }
        kbService.remove(id);
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "删除资料（" + doc.getDocName() + "）", "ok", "成功");
        return ApiResponse.ok(Map.of("id", id, "deleted", true));
    }

    /** 检索测试（FR-F3 配套）：返回命中的原文片段，验证入库内容可被检索到。 */
    @GetMapping("/search")
    public ApiResponse<List<HitView>> search(@RequestParam(name = "q") String q,
                                             @RequestParam(name = "limit", defaultValue = "5") int limit) {
        AuthUser user = AuthUserContext.require();
        if (q == null || q.isBlank()) {
            throw BizException.badRequest("检索词不能为空");
        }
        List<HitView> hits = kbService.searchMine(user.getTenantId(), user.getUserId(), q.trim(), limit)
                .stream().map(h -> new HitView(h.docId(), h.docName(), h.snippet(), h.chunkIndex())).toList();
        return ApiResponse.ok(hits);
    }

    private boolean isVisible(AuthUser user, KbDocument doc) {
        if (doc == null) {
            return false;
        }
        boolean admin = user.getRoles().contains("ROLE_ADMIN");
        boolean sameTenant = doc.getTenantId() != null
                && user.getTenantId() != null
                && doc.getTenantId().longValue() == user.getTenantId().longValue();
        boolean owns = doc.getUserId().equals(user.getUserId());
        boolean tenantShared = KbService.SCOPE_TENANT.equals(doc.getScope());
        return admin || (sameTenant && (owns || tenantShared));
    }
}
