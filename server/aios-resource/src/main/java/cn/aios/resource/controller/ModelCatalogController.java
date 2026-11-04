package cn.aios.resource.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 平台模型目录（2026-11-04）：给用户端「顶部模型选择」列出**后台已启用的模型**。
 *
 * <p>为什么需要单独一个接口：用户端此前只能选自己注册的账号，看不到平台侧配了哪些模型；
 * 而 {@code /api/v1/admin/models} 是管理员专属，不可能让普通用户去读。
 * 这里只回「可展示字段」（不包含 base_url、密钥、环境变量名），
 * 选中后前端把 key 当 {@code model_ref} 随对话下发即可。</p>
 */
@RestController
@RequestMapping("/api/v1/model-catalog")
@RequiredArgsConstructor
public class ModelCatalogController {

    private final JdbcTemplate jdbc;

    @GetMapping
    public ApiResponse<Map<String, Object>> catalog() {
        AuthUserContext.require();
        List<Map<String, Object>> models = jdbc.query(
                "SELECT provider_key, name, model_name, provider_type, is_default "
                        + "FROM model_config WHERE enabled = 1 "
                        + "ORDER BY is_default DESC, sort ASC, id ASC",
                (rs, i) -> {
                    Map<String, Object> o = new LinkedHashMap<>();
                    o.put("key", rs.getString("provider_key"));
                    o.put("name", rs.getString("name"));
                    o.put("model", rs.getString("model_name"));
                    o.put("providerType", rs.getString("provider_type"));
                    o.put("isDefault", rs.getBoolean("is_default"));
                    return o;
                });
        String defaultKey = "";
        for (Map<String, Object> m : new ArrayList<>(models)) {
            if (Boolean.TRUE.equals(m.get("isDefault"))) {
                defaultKey = String.valueOf(m.get("key"));
                break;
            }
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("models", models);
        data.put("default", defaultKey);
        return ApiResponse.ok(data);
    }
}
