package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.KbDocument;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.resource.service.KbService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 用户端知识库：资料清单 + 登记上传。
 * M1 只登记元信息（state=WAIT），解析入库由 agent 侧异步完成后回写状态。
 */
@RestController
@RequestMapping("/api/v1/kb")
@RequiredArgsConstructor
public class KbController {

    private final KbService kbService;
    private final ActivityLogService activityLogService;

    public record DocView(Long id, String name, String icon, String state, Long sizeBytes, String createdAt) {

        static DocView from(KbDocument d) {
            return new DocView(d.getId(), d.getDocName(), d.getIcon(),
                    d.getState() == null ? "wait" : d.getState().toLowerCase(),
                    d.getSizeBytes(),
                    d.getCreatedAt() == null ? null : d.getCreatedAt().toString());
        }
    }

    public record UploadRequest(String name, String icon, Long sizeBytes) {
    }

    @GetMapping("/documents")
    public ApiResponse<List<DocView>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(kbService.list(user.getTenantId(), user.getUserId())
                .stream().map(DocView::from).toList());
    }

    @PostMapping("/documents")
    public ApiResponse<DocView> upload(@RequestBody(required = false) UploadRequest body) {
        AuthUser user = AuthUserContext.require();
        if (body == null || body.name() == null || body.name().isBlank()) {
            throw BizException.badRequest("资料名称不能为空");
        }
        KbDocument doc = kbService.register(user.getTenantId(), user.getUserId(),
                body.name().trim(), body.icon(), body.sizeBytes());
        activityLogService.record(user.getTenantId(), user.getUserId(),
                "上传资料（" + doc.getDocName() + "）", "ok", "成功");
        return ApiResponse.ok(DocView.from(doc));
    }
}
