package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.service.SysConfigResolver;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * 面向 C 端（用户端 H5）的公开配置读取。
 *
 * <p>背景：`/api/v1/admin/configs` 只对平台/租户管理员开放，用户端拿不到任何运营配置，
 * 于是「内容由后端配置」的需求只能靠前端写死。本控制器提供一条**只读、白名单**的通路。</p>
 *
 * <p><b>安全口径</b>：白名单只登记「展示型」配置（文案、场景清单等）。
 * 额度阈值、安全策略等运营参数一律不对外 —— 它们会暴露风控口径。</p>
 *
 * <p><b>机构覆盖值的回落口径</b>：本控制器不再持有任何解析逻辑，统一委托
 * {@link SysConfigResolver#effectiveValue}（机构覆盖值 → 租户值 → 平台默认 → 空串）。
 * 唯一解析入口在那一处，本类只是调用方，避免「再复制一份回落链」。</p>
 */
@RestController
@RequestMapping("/api/v1/configs")
@RequiredArgsConstructor
public class ConfigController {

    /**
     * 对外公开的配置键白名单。
     *
     * <p>新增对外配置时必须在此登记；未登记的键直接 403，避免「顺手把整表开放出去」。</p>
     */
    private static final Set<String> USER_VISIBLE_KEYS = Set.of(
            // 词元包购买页「适用场景」（V33）
            "billing.package.scenes");

    private final SysConfigResolver sysConfigResolver;

    /**
     * 批量读取公开配置。
     *
     * <p>示例：{@code GET /api/v1/configs?keys=billing.package.scenes}
     * → {@code {"billing.package.scenes": "[{\"title\":\"个人试用\",...}]"}}</p>
     */
    @GetMapping
    public ApiResponse<Map<String, String>> read(@RequestParam(name = "keys") String keys) {
        AuthUser user = AuthUserContext.require();
        Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        Long institutionId = user.getInstitutionId();
        Map<String, String> out = new LinkedHashMap<>();
        for (String raw : keys.split(",")) {
            String key = raw.trim();
            if (key.isEmpty()) {
                continue;
            }
            if (!USER_VISIBLE_KEYS.contains(key)) {
                throw BizException.forbidden("配置项不对外开放：" + key);
            }
            out.put(key, sysConfigResolver.effectiveValue(tenantId, institutionId, key));
        }
        return ApiResponse.ok(out);
    }
}
