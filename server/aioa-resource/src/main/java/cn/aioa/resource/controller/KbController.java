package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.resource.service.KbFileParser;
import cn.aioa.resource.service.KbService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.PermissionCatalog;
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

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 用户端知识库（FR-F）：上传入库、三态清单、失败重试、删除留痕、检索测试。
 *
 * GET    /api/v1/kb/documents              —— 我的资料（默认）
 * GET    /api/v1/kb/documents?scope=tenant —— 租户全部资料（仅租户管理员，含平台管理员）
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
                          String stage, Integer progress, Integer retryCount, String createdAt) {

        static DocView from(KbDocument d) {
            return new DocView(d.getId(), d.getDocName(), d.getIcon(),
                    d.getState() == null ? "wait" : d.getState().toLowerCase(),
                    d.getSizeBytes(), d.getUserId(),
                    d.getScope() == null ? "PERSONAL" : d.getScope(),
                    d.getChunkCount(), d.getErrorMsg(),
                    d.getStage(), d.getProgress(), d.getRetryCount(),
                    d.getCreatedAt() == null ? null : d.getCreatedAt().toString());
        }
    }

    public record UploadRequest(String name, String icon, Long sizeBytes, String content, String scope) {
    }

    /** 检索命中：docId/docName/snippet/chunkIndex 为既有字段（前端在用），score 为新增的相似度（可空）。 */
    public record HitView(Long docId, String docName, String snippet, Integer chunkIndex, Float score) {
    }

    /**
     * 诊断：当前知识库档位（存储实现 / 嵌入 provider / 维度）。
     *
     * <p>不含任何敏感信息，登录即可读。存在意义有两个：运维排查「到底走的是哪一档」，
     * 以及 E2E 双跑矩阵（store × mode）据此判断本次跑在哪个档位。</p>
     */
    @GetMapping("/store")
    public ApiResponse<Map<String, Object>> storeInfo() {
        AuthUserContext.require();
        return ApiResponse.ok(Map.of(
                "store", kbService.storeType(),
                "embeddingProvider", kbService.embeddingProviderName(),
                "embeddingDims", kbService.embeddingDims()));
    }

    @GetMapping("/documents")
    public ApiResponse<List<DocView>> list(@RequestParam(name = "scope", required = false) String scope) {
        AuthUser user = AuthUserContext.require();
        List<KbDocument> docs;
        if ("tenant".equalsIgnoreCase(scope)) {
            // 租户视角：租户管理员（含系统管理员）。
            //
            // 判据必须走 PermissionCatalog.isAdmin —— 它才是「谁来管本租户」的唯一入口
            // （AdminQuota/AdminConfig/AdminAudit/AdminBizSystem 等管理端控制器全部按此口径）。
            // 此处曾是全仓唯一一处裸判 ROLE_ADMIN 的知识库入口，后果有两个，且互相印证：
            //   1) 租户管理员点「知识库」页（默认 tab 就是本分支）拿到 403，
            //      列表渲染成「租户内暂无资料」，而他刚刚共享出去的资料在上面一条都看不到；
            //   2) 提示语「仅租户管理员可访问」把租户管理员本人拒之门外 —— 自相矛盾。
            // 这与 PermissionCatalog#isAdmin 注释里记载的历史缺陷是同一类，此处属复发。
            if (!PermissionCatalog.isAdmin(user)) {
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

    /**
     * 修改资料：重命名 / 可见范围（PERSONAL 个人、TENANT 租户共享）。
     *
     * <p>「谁能改别人的资料」与「谁能看租户全部资料」是**同一个决策点**，必须同源
     * （{@link PermissionCatalog#isAdmin}）。两处若各写一套，就会出现「列表里看得到、
     * 想改可见范围却被 403」——而改可见范围正是「共享/取消共享」这个动作本身。</p>
     */
    @PutMapping("/documents/{id}")
    public ApiResponse<DocView> update(@PathVariable Long id, @RequestBody(required = false) Map<String, String> body) {
        AuthUser user = AuthUserContext.require();
        boolean admin = PermissionCatalog.isAdmin(user);
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
        boolean admin = PermissionCatalog.isAdmin(user);
        KbDocument doc = kbService.findOne(id);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + id);
        }
        // 跨租户隔离：禁止删除其他租户的资料
        if (doc.getTenantId() == null || doc.getTenantId().longValue() != user.getTenantId().longValue()) {
            throw BizException.forbidden("无权操作其他租户的资料");
        }
        // 租户管理员（含平台管理员）可删除本租户任意资料；普通用户只能删自己的。
        // 与 list(scope=tenant) / update 同一判据（PermissionCatalog.isAdmin），勿分叉。
        if (!admin && !doc.getUserId().equals(user.getUserId())) {
            throw BizException.forbidden("只能删除本人上传的资料");
        }
        kbService.remove(id);
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "删除资料（" + doc.getDocName() + "）", "ok", "成功");
        return ApiResponse.ok(Map.of("id", id, "deleted", true));
    }

    /**
     * 检索测试（FR-F3 配套）：返回命中的原文片段，验证入库内容可被检索到。
     *
     * <p>2026-09-19（docs/32）新增四个**可选**参数，用于在 mysql / milvus 两档下做同一批用例的双跑对齐
     * （topK / threshold / mode / kbScope 四个参数在两种实现下语义一致）。不传时行为与改造前**逐字一致**
     * （等效 mode=bm25、topk=limit、threshold=0、不限范围），存量调用方零影响。</p>
     *
     * @param mode      vector / bm25 / hybrid，缺省 bm25（与既有行为一致）
     * @param topk      返回条数，缺省取 limit
     * @param threshold 相似度阈值（仅作用于向量召回），缺省 0
     * @param docScope  知识库范围：逗号分隔的文档 ID，缺省不限
     */
    @GetMapping("/search")
    public ApiResponse<List<HitView>> search(@RequestParam(name = "q") String q,
                                             @RequestParam(name = "limit", defaultValue = "5") int limit,
                                             @RequestParam(name = "mode", required = false) String mode,
                                             @RequestParam(name = "topk", required = false) Integer topk,
                                             @RequestParam(name = "threshold", required = false) Double threshold,
                                             @RequestParam(name = "docScope", required = false) String docScope) {
        AuthUser user = AuthUserContext.require();
        if (q == null || q.isBlank()) {
            throw BizException.badRequest("检索词不能为空");
        }
        List<Long> scopeIds = parseDocScope(docScope);
        String m = (mode == null || mode.isBlank()) ? "bm25" : mode.trim().toLowerCase();
        if (!VALID_MODES.contains(m)) {
            throw BizException.badRequest("mode 只能是 " + VALID_MODES + " 之一，收到：" + mode);
        }
        int k = (topk != null && topk > 0) ? topk : Math.max(1, limit);
        List<HitView> hits = kbService.search(user.getTenantId(), user.getUserId(), q.trim(),
                        k, threshold == null ? 0.0 : threshold, m, scopeIds)
                .stream().map(h -> new HitView(h.docId(), h.docName(), h.snippet(), h.chunkIndex(), h.score()))
                .toList();
        return ApiResponse.ok(hits);
    }

    private static final List<String> VALID_MODES = List.of("vector", "bm25", "hybrid");

    /** 解析逗号分隔的文档范围；空白一律视为「不限范围」。 */
    private static List<Long> parseDocScope(String docScope) {
        if (docScope == null || docScope.isBlank()) {
            return null;
        }
        List<Long> ids = new ArrayList<>();
        for (String part : docScope.split(",")) {
            String t = part.trim();
            if (t.isEmpty()) {
                continue;
            }
            try {
                ids.add(Long.parseLong(t));
            } catch (NumberFormatException e) {
                throw BizException.badRequest("docScope 非法（应为逗号分隔的数字 ID）：" + t);
            }
        }
        return ids.isEmpty() ? null : ids;
    }

    private boolean isVisible(AuthUser user, KbDocument doc) {
        if (doc == null) {
            return false;
        }
        boolean admin = PermissionCatalog.isAdmin(user);
        boolean sameTenant = doc.getTenantId() != null
                && user.getTenantId() != null
                && doc.getTenantId().longValue() == user.getTenantId().longValue();
        boolean owns = doc.getUserId().equals(user.getUserId());
        boolean tenantShared = KbService.SCOPE_TENANT.equals(doc.getScope());
        return admin || (sameTenant && (owns || tenantShared));
    }
}
