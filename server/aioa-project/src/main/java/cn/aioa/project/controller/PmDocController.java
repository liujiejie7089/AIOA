package cn.aioa.project.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.service.PmDocService;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 项目 / 企业文档接口（PM 批次 3，V72）。
 *
 * <p>路径收敛在 {@code /api/v1/pm} 下，与 {@code PmProjectController} 同前缀；
 * 权限一律在 {@link PmDocService} 内判定（{@code requireVisible} + {@code requireWrite}），
 * 控制器不做二次鉴权（两处判定迟早漂移）。</p>
 *
 * <p><b>字节实体不在这里</b>：上传先走既有 {@code POST /api/v1/files/upload} 拿 {@code fileId}，
 * 再调本控制器的 {@code /documents} 登记索引。删除只软删索引，不动 {@code sys_file} 字节（BR-07）。</p>
 */
@RestController
@RequestMapping("/api/v1/pm")
@RequiredArgsConstructor
public class PmDocController {

    private final OrgGuard guard;
    private final PmDocService docService;

    // ======================================================================
    // 树
    // ======================================================================

    /** 项目文档树：企业级公共（只读挂载）+ 项目专属（可写）。 */
    @GetMapping("/projects/{id}/docs/tree")
    public ApiResponse<Map<String, Object>> tree(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(docService.tree(u, id));
    }

    /** 企业文档树（跨项目，供「企业文档」页）。 */
    @GetMapping("/docs/enterprise")
    public ApiResponse<Map<String, Object>> enterpriseTree() {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(docService.enterpriseTree(u));
    }

    // ======================================================================
    // 文件夹
    // ======================================================================

    @PostMapping("/projects/{id}/docs/folders")
    public ApiResponse<Map<String, Object>> createFolder(@PathVariable Long id,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(docService.createFolder(u, id, body));
    }

    @DeleteMapping("/projects/{id}/docs/folders/{folderId}")
    public ApiResponse<Void> deleteFolder(@PathVariable Long id, @PathVariable Long folderId) {
        AuthUser u = guard.requireOrgUser();
        docService.deleteFolder(u, id, folderId);
        return ApiResponse.ok();
    }

    // ======================================================================
    // 文档
    // ======================================================================

    /** 登记文档：{@code source=UPLOAD}（带 fileId）或 {@code source=AI}（带 contentText）。 */
    @PostMapping("/projects/{id}/docs/documents")
    public ApiResponse<Map<String, Object>> createDocument(@PathVariable Long id,
                                                           @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(docService.createDocument(u, id, body));
    }

    @GetMapping("/projects/{id}/docs/documents/{docId}")
    public ApiResponse<Map<String, Object>> documentDetail(@PathVariable Long id, @PathVariable Long docId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(docService.documentDetail(u, id, docId));
    }

    @DeleteMapping("/projects/{id}/docs/documents/{docId}")
    public ApiResponse<Void> deleteDocument(@PathVariable Long id, @PathVariable Long docId) {
        AuthUser u = guard.requireOrgUser();
        docService.deleteDocument(u, id, docId);
        return ApiResponse.ok();
    }
}
