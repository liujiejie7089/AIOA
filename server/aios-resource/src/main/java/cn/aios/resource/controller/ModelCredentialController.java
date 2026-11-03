package cn.aios.resource.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.service.ModelCredentialService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 模型账号与共享（2026-11-03，docs/71）。
 *
 * <p><b>权限口径</b>：除公司账号的建/改（需租户管理员）外，全部按
 * 「本人」判定 —— 谁能动这个账号由 {@link ModelCredentialService#loadOwned} 一处裁决，
 * 控制器不再各写一份，避免出现「A 接口查了属主、B 接口忘了查」这种越权面。</p>
 *
 * <p><b>回执绝不含明文 Key</b>：统一走 {@code CredentialView}（只有掩码）。
 * 明文 Key 只在服务内解析后直接下发给 agent 的那条链路上存在。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/model-credentials")
@RequiredArgsConstructor
public class ModelCredentialController {

    private final ModelCredentialService credentialService;

    /** 我的账号三类：mine 自己持有 / company 公司账号 / shared 邀请给我的。 */
    @GetMapping
    public ApiResponse<Map<String, Object>> myAccounts() {
        return ApiResponse.ok(credentialService.myAccounts(AuthUserContext.require()));
    }

    /** 新建账号。body: {ownerType, providerKey, name, apiKey, baseUrl?, modelName?, shareEnabled?, remark?} */
    @PostMapping
    public ApiResponse<ModelCredentialService.CredentialView> create(
            @RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.ok(credentialService.create(AuthUserContext.require(), body));
    }

    /** 修改。body 里出现的字段才改，未传的字段保持原值。 */
    @PutMapping("/{id}")
    public ApiResponse<ModelCredentialService.CredentialView> update(
            @PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.ok(credentialService.update(AuthUserContext.require(), id, body));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        credentialService.delete(AuthUserContext.require(), id);
        return ApiResponse.ok();
    }

    /** 我发出的邀请。 */
    @GetMapping("/invites")
    public ApiResponse<java.util.List<ModelCredentialService.ShareView>> myInvites() {
        return ApiResponse.ok(credentialService.myInvites(AuthUserContext.require()));
    }

    /** 邀请给我的（含已撤销 / 已过期的历史，前端据此区分状态）。 */
    @GetMapping("/invites/incoming")
    public ApiResponse<java.util.List<ModelCredentialService.ShareView>> incomingInvites() {
        return ApiResponse.ok(credentialService.invitesToMe(AuthUserContext.require()));
    }

    /**
     * 邀请同事共用。body: {granteeUserId | granteeUsername, quotaTokens?, expiresAt?}
     *
     * <p>被邀请人消耗的词元记在邀请者头上（{@code charge_user_id = ownerUserId}），
     * 这是「由邀请者承担」在数据上的唯一体现。</p>
     */
    @PostMapping("/{id}/shares")
    public ApiResponse<ModelCredentialService.ShareView> invite(
            @PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.ok(credentialService.invite(AuthUserContext.require(), id, body));
    }

    /** 接受邀请（按邀请码；邀请时已直接置 ACTIVE，本接口给「待确认」流程留口）。 */
    @PostMapping("/shares/{shareId}/accept")
    public ApiResponse<ModelCredentialService.ShareView> accept(
            @PathVariable Long shareId, @RequestBody(required = false) Map<String, Object> body) {
        String code = body == null ? null : String.valueOf(body.getOrDefault("inviteCode", ""));
        return ApiResponse.ok(credentialService.accept(AuthUserContext.require(), shareId, code));
    }

    /** 撤销共享（邀请人，或公司账号的管理员）。 */
    @DeleteMapping("/shares/{shareId}")
    public ApiResponse<Void> revoke(@PathVariable Long shareId) {
        AuthUser user = AuthUserContext.require();
        credentialService.revoke(user, shareId);
        return ApiResponse.ok();
    }

    /** 被邀请人主动退出。 */
    @PostMapping("/shares/{shareId}/leave")
    public ApiResponse<Void> leave(@PathVariable Long shareId) {
        credentialService.leave(AuthUserContext.require(), shareId);
        return ApiResponse.ok();
    }

    /**
     * 校验「这个 id 是不是本租户的账号」。前端选号后调一次，把不可用（已删除/跨租户）
     * 提前暴露，而不是等到对话发出去才报错。
     */
    @GetMapping("/{id}/check")
    public ApiResponse<Map<String, Object>> check(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        ModelCredentialService.Resolved resolved = credentialService.resolve(user, id);
        return ApiResponse.ok(Map.of(
                "credentialId", resolved.credentialId(),
                "providerKey", resolved.providerKey(),
                "chargeUserId", resolved.chargeUserId() == null ? 0L : resolved.chargeUserId(),
                "ownerType", resolved.ownerType(),
                "companyCharged", resolved.companyCharged()));
    }

    /** 明文 Key 不外泄：本接口只返回掩码与掩码规则说明，便于前端展示。 */
    @GetMapping("/key-policy")
    public ApiResponse<Map<String, Object>> keyPolicy() {
        return ApiResponse.ok(Map.of(
                "storage", "AES-256-GCM（enc: 前缀），与连接器凭据同口径",
                "exposure", "任何接口都不返回明文 Key，只返回前 3 后 4 的掩码"));
    }

    /** 统一兜底：路径变量非法时给出明确文案，而不是 500。 */
    @org.springframework.web.bind.annotation.ExceptionHandler(IllegalArgumentException.class)
    public ApiResponse<Void> badId(IllegalArgumentException e) {
        throw BizException.badRequest("参数非法：" + e.getMessage());
    }
}
