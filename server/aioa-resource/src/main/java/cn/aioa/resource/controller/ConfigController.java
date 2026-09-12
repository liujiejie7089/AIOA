package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
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

    private final SysConfigMapper configMapper;

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
        Map<String, String> out = new LinkedHashMap<>();
        for (String raw : keys.split(",")) {
            String key = raw.trim();
            if (key.isEmpty()) {
                continue;
            }
            if (!USER_VISIBLE_KEYS.contains(key)) {
                throw BizException.forbidden("配置项不对外开放：" + key);
            }
            out.put(key, resolve(tenantId, key));
        }
        return ApiResponse.ok(out);
    }

    /**
     * 配置解析：租户值 → 平台默认（tenant_id=0）→ 空串。
     *
     * <p>必须带回落：`sys_config` 只在租户**首次访问**管理端时才克隆平台默认，
     * 因此新增的键在老租户里根本没有行；不回落到 tenant_id=0 就会「管理端配了、用户端看不到」。</p>
     */
    private String resolve(Long tenantId, String key) {
        Set<Long> scopes = new LinkedHashSet<>();
        scopes.add(tenantId);
        scopes.add(0L);
        for (Long scope : scopes) {
            SysConfig row = configMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                    .eq(SysConfig::getTenantId, scope)
                    .eq(SysConfig::getConfigKey, key)
                    .last("LIMIT 1"));
            if (row == null) {
                continue;
            }
            String value = row.getConfigValue();
            if (value == null || value.isBlank()) {
                value = row.getDefaultValue();
            }
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }
}
