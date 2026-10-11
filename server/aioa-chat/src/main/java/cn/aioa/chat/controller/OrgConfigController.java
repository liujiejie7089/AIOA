package cn.aioa.chat.controller;

import cn.aioa.chat.service.OrgConfigService;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 机构作用域系统参数（需求二 · 管理端菜单权限，docs/44 §2.5 B 案）。
 *
 * <pre>
 *   GET    /api/v1/admin/org-configs?institutionId={id}   读某机构的参数（含继承状态）
 *   PUT    /api/v1/admin/org-configs                       body {institutionId?, configKey, configValue} → upsert 覆盖值
 *   DELETE /api/v1/admin/org-configs?institutionId=&configKey=   删除覆盖值 → 恢复继承
 * </pre>
 *
 * <p><b>为什么在 aioa-chat 而不是 aioa-resource</b>：{@link OrgConfigService} 要同时访问
 * aioa-resource（{@code sys_config} / {@code sys_org_config}）与 aioa-org（{@code org_institution}），
 * 而这两个模块互不依赖，只有 aioa-chat 同时依赖二者 —— 与 {@code WorkerIntakeController} 同一理由
 * （其 javadoc 已写明这条约束）。端点路径仍是 {@code /api/v1/admin/org-configs}，归属语义不变。</p>
 *
 * <p><b>独立表、零回归</b>：本控制器读写 {@code sys_org_config}，完全不碰 {@code sys_config} 的
 * 既有读写（除 {@code ConfigController#resolve} 的回落口径，那里仅新增「机构覆盖值优先」一层，
 * 无任何机构覆盖行时行为逐字节不变）。机构管理员被后端钉死本机构，杜绝「只放开菜单 = 改到全租户」的越权。</p>
 */
@Tag(name = "机构参数配置")
@RestController
@RequestMapping("/api/v1/admin/org-configs")
@RequiredArgsConstructor
public class OrgConfigController {

    private final OrgConfigService orgConfigService;

    @Operation(summary = "读取某机构的参数（含继承状态）")
    @GetMapping
    public ApiResponse<OrgConfigService.OrgConfigReadResult> read(
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(orgConfigService.read(user, institutionId));
    }

    @Operation(summary = "upsert 机构参数覆盖值")
    @PutMapping
    public ApiResponse<Void> upsert(@RequestBody OrgConfigService.OrgConfigUpsertReq req) {
        AuthUser user = AuthUserContext.require();
        orgConfigService.upsert(user, req);
        return ApiResponse.ok();
    }

    @Operation(summary = "删除机构参数覆盖值（恢复继承）")
    @DeleteMapping
    public ApiResponse<Void> delete(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "configKey", required = false) String configKey) {
        AuthUser user = AuthUserContext.require();
        orgConfigService.delete(user, institutionId, configKey);
        return ApiResponse.ok();
    }
}
