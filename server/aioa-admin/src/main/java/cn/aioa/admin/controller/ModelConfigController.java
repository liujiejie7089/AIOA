package cn.aioa.admin.controller;

import cn.aioa.admin.entity.ModelConfig;
import cn.aioa.admin.service.ModelConfigService;
import cn.aioa.admin.service.ModelConfigView;
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

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 模型管理（管理端）：新增 / 编辑 / 删除 / 启停 / 连通性校验 / 默认模型。
 * 变更即时生效：保存后推送 agent 热加载，无需重启服务。
 *
 * <p>密钥口径：列表与详情**只返回掩码**。明文只存在于「保存时的请求体」与「推送 agent 的内网链路」。
 */
@RestController
@RequestMapping("/api/v1/admin/models")
public class ModelConfigController {

    private static final BigDecimal TEMP_MIN = new BigDecimal("0");
    private static final BigDecimal TEMP_MAX = new BigDecimal("2");

    private final ModelConfigService service;

    public ModelConfigController(ModelConfigService service) {
        this.service = service;
    }

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("模型管理仅管理员可访问");
        }
        return user;
    }

    @GetMapping
    public ApiResponse<List<ModelConfigView>> list() {
        requireAdmin();
        return ApiResponse.ok(service.listViews());
    }

    /** 大模型类型预设：新增表单据此自动带出接入地址 / 模型名 / 密钥环境变量名。 */
    @GetMapping("/presets")
    public ApiResponse<Map<String, Object>> presets() {
        requireAdmin();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("presets", service.presets());
        data.put("keyEncryptionWeak", service.isKeyEncryptionWeak());
        return ApiResponse.ok(data);
    }

    @PostMapping
    public ApiResponse<ModelConfigView> create(@RequestBody ModelConfig body) {
        AuthUser user = requireAdmin();
        validate(body);
        if (service.defaultKey().equals(body.getProviderKey()) || Boolean.TRUE.equals(body.getIsDefault())) {
            body.setIsDefault(true);
        }
        return ApiResponse.ok(service.upsert(body, user.getUserId()));
    }

    @PutMapping("/{key}")
    public ApiResponse<ModelConfigView> update(@PathVariable String key, @RequestBody ModelConfig body) {
        requireAdmin();
        body.setProviderKey(key);
        validate(body);
        return ApiResponse.ok(service.upsert(body, null));
    }

    /** 启停：启用前先做连通性校验，不通过则保持停用并把原因返回给前端。 */
    @PutMapping("/{key}/status")
    public ApiResponse<ModelConfigService.CheckResult> setStatus(@PathVariable String key,
                                                                 @RequestBody StatusRequest body) {
        requireAdmin();
        if (body == null || body.enabled() == null) {
            throw BizException.badRequest("enabled 不能为空");
        }
        return ApiResponse.ok(service.setStatus(key, Boolean.TRUE.equals(body.enabled())));
    }

    /** 只做连通性校验，不改状态。 */
    @PostMapping("/{key}/test")
    public ApiResponse<ModelConfigService.CheckResult> test(@PathVariable String key) {
        requireAdmin();
        return ApiResponse.ok(service.check(key));
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
        if (isBlank(body.getProviderKey())) {
            throw BizException.badRequest("模型标识不能为空");
        }
        if (isBlank(body.getName())) {
            throw BizException.badRequest("模型名称不能为空");
        }
        if (isBlank(body.getBaseUrl())) {
            throw BizException.badRequest("API Base URL 不能为空");
        }
        if (isBlank(body.getModelName())) {
            throw BizException.badRequest("模型名不能为空");
        }
        if (isBlank(body.getApiKeyEnv())) {
            // 没有环境变量名也要有兜底，否则 agent 侧无从读取
            body.setApiKeyEnv("API_KEY_PLACEHOLDER");
        }
        BigDecimal temp = body.getTemperature();
        if (temp != null && (temp.compareTo(TEMP_MIN) < 0 || temp.compareTo(TEMP_MAX) > 0)) {
            throw BizException.badRequest("温度需介于 0 与 2 之间");
        }
        Integer maxContext = body.getMaxContext();
        if (maxContext != null && maxContext < 0) {
            throw BizException.badRequest("最大上下文长度不能为负数");
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    /** 启停请求体。 */
    public record StatusRequest(Boolean enabled) {
    }
}
