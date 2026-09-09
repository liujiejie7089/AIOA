package cn.aioa.admin.controller;

import cn.aioa.admin.entity.ModelConfig;
import cn.aioa.admin.service.ModelConfigService;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 模型管理（管理端）：新增 / 编辑 / 删除 / 启停 / 默认模型。
 * 变更即时生效：保存后推送 agent 热加载，无需重启服务。
 */
@RestController
@RequestMapping("/api/v1/admin/models")
public class ModelConfigController {

    private final ModelConfigService service;

    public ModelConfigController(ModelConfigService service) {
        this.service = service;
    }

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("模型管理仅租户管理员可访问");
        }
        return user;
    }

    @GetMapping
    public ApiResponse<List<ModelConfig>> list() {
        requireAdmin();
        return ApiResponse.ok(service.list());
    }

    @PostMapping
    public ApiResponse<ModelConfig> create(@RequestBody ModelConfig body) {
        AuthUser user = requireAdmin();
        validate(body);
        if (service.defaultKey().equals(body.getProviderKey()) || Boolean.TRUE.equals(body.getIsDefault())) {
            body.setIsDefault(true);
        }
        return ApiResponse.ok(service.upsert(body, user.getUserId()));
    }

    @PutMapping("/{key}")
    public ApiResponse<ModelConfig> update(@PathVariable String key, @RequestBody ModelConfig body) {
        requireAdmin();
        body.setProviderKey(key);
        validate(body);
        return ApiResponse.ok(service.upsert(body, null));
    }

    @PutMapping("/{key}/default")
    public ApiResponse<Map<String, Object>> setDefault(@PathVariable String key) {
        requireAdmin();
        service.setDefault(key);
        return ApiResponse.ok(Map.of("providerKey", key, "isDefault", true));
    }

    @DeleteMapping("/{key}")
    public ApiResponse<Map<String, Object>> delete(@PathVariable String key) {
        requireAdmin();
        if (service.defaultKey().equals(key)) {
            throw BizException.badRequest("默认模型不可删除，请先将其他模型设为默认");
        }
        service.delete(key);
        return ApiResponse.ok(Map.of("providerKey", key, "deleted", true));
    }

    private void validate(ModelConfig body) {
        if (body.getProviderKey() == null || body.getProviderKey().isBlank()) {
            throw BizException.badRequest("providerKey 不能为空");
        }
        if (body.getName() == null || body.getName().isBlank()) {
            throw BizException.badRequest("name 不能为空");
        }
        if (body.getBaseUrl() == null || body.getBaseUrl().isBlank()) {
            throw BizException.badRequest("baseUrl 不能为空");
        }
        if (body.getModelName() == null || body.getModelName().isBlank()) {
            throw BizException.badRequest("modelName 不能为空");
        }
        if (body.getApiKeyEnv() == null || body.getApiKeyEnv().isBlank()) {
            body.setApiKeyEnv("API_KEY_PLACEHOLDER");
        }
    }
}
