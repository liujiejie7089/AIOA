package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.FormSubmission;
import cn.aioa.resource.entity.FormTemplate;
import cn.aioa.resource.service.FormSubmissionService;
import cn.aioa.resource.service.FormSubmissionService.SubmitBody;
import cn.aioa.resource.service.FormTemplateService;
import cn.aioa.resource.service.FormTemplateService.FormRender;
import cn.aioa.resource.service.FormTemplateService.FormSave;
import cn.aioa.resource.service.FormSubmissionService.SubmitResult;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.metadata.IPage;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 表单域控制器（docs/52 P1/P4）。
 *
 * <pre>
 *   GET    /api/v1/forms/{code}                  渲染用定义（登录即可）
 *   GET    /api/v1/forms                         列表/筛选（form:manage）
 *   POST   /api/v1/forms                         新建定义（form:manage，自动升版）
 *   PUT    /api/v1/forms/{code}                  更新定义（form:manage，自动升版）
 *   POST   /api/v1/forms/{code}/submit           独立入口提交（登录即可）
 *   GET    /api/v1/form-submissions              我的/全租户提交记录（登录即可；form:manage 看全租户）
 * </pre>
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class FormController {

    private final FormTemplateService templateService;
    private final FormSubmissionService submissionService;

    /** 取渲染用定义（ACTIVE 版本，含解析后的 options）。 */
    @GetMapping("/forms/{code}")
    public ApiResponse<FormRender> getForm(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(templateService.resolveForRender(user.getTenantId(), code));
    }

    /** 列表/筛选（管理端）。 */
    @GetMapping("/forms")
    public ApiResponse<IPage<FormTemplate>> listForms(
            @RequestParam(name = "moduleCode", required = false) String moduleCode,
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "20") int size) {
        AuthUser user = AuthUserContext.require();
        requireManage(user, "查看表单定义列表");
        return ApiResponse.ok(templateService.list(user.getTenantId(), moduleCode, status, page, size));
    }

    /** 新建表单定义（version=1）。 */
    @PostMapping("/forms")
    public ApiResponse<FormTemplate> createForm(@RequestBody FormSave req) {
        AuthUser user = AuthUserContext.require();
        requireManage(user, "新建表单定义");
        return ApiResponse.ok(templateService.create(user, req));
    }

    /** 更新表单定义（自动升版并写快照）。 */
    @PutMapping("/forms/{code}")
    public ApiResponse<FormTemplate> updateForm(@PathVariable String code, @RequestBody FormSave req) {
        AuthUser user = AuthUserContext.require();
        requireManage(user, "更新表单定义");
        return ApiResponse.ok(templateService.update(user, code, req));
    }

    /** 独立入口提交。 */
    @PostMapping("/forms/{code}/submit")
    public ApiResponse<SubmitResult> submitForm(@PathVariable String code,
                                               @RequestBody SubmitBody body) {
        AuthUser user = AuthUserContext.require();
        Map<String, Object> data = body == null || body.data() == null ? Map.of() : body.data();
        SubmitResult result = submissionService.submit(user.getTenantId(), user.getUserId(), code,
                data, body == null ? null : body.conversationId(),
                body == null ? null : body.runId());
        return ApiResponse.ok(result);
    }

    /** 提交记录：默认看自己的；持有 form:manage 看全租户。按申请人过滤只在此一处判定。 */
    @GetMapping("/form-submissions")
    public ApiResponse<IPage<FormSubmission>> listSubmissions(
            @RequestParam(name = "code", required = false) String code,
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "20") int size) {
        AuthUser user = AuthUserContext.require();
        boolean admin = PermissionCatalog.holds(user, PermissionCatalog.FORM_MANAGE);
        Long applicantId = admin ? null : user.getUserId();
        return ApiResponse.ok(submissionService.list(user.getTenantId(), applicantId, admin,
                code, status, page, size));
    }

    private static void requireManage(AuthUser user, String action) {
        if (!PermissionCatalog.holds(user, PermissionCatalog.FORM_MANAGE)) {
            throw BizException.forbidden(action + "需要权限（" + PermissionCatalog.rolesText(PermissionCatalog.FORM_MANAGE)
                    + "）；当前账号角色为「" + roleText(user) + "」。表单定义属管理配置，请联系本租户管理员。");
        }
    }

    private static String roleText(AuthUser user) {
        return user.getRoles() == null || user.getRoles().isEmpty() ? "无角色"
                : String.join("、", user.getRoles());
    }
}
