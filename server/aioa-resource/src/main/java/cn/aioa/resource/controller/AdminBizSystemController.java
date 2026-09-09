package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.BizSystem;
import cn.aioa.resource.mapper.BizSystemMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 业务系统注册与配置管理（管理端，V15）：
 * 录入、查看、维护已接入业务系统的接口地址、认证方式、密钥与接口文档，统一管理。
 *
 * <p>安全约定：authConfig（密钥等敏感字段）出参一律掩码为 {@code ****}，
 * 入参若传掩码值则保留库中原值，避免回显表单覆盖真实密钥。</p>
 *
 * GET    /api/v1/admin/biz-systems[?q=]     列表（含敏感字段掩码）
 * GET    /api/v1/admin/biz-systems/{id}     详情（掩码）
 * POST   /api/v1/admin/biz-systems          注册
 * PUT    /api/v1/admin/biz-systems/{id}     更新
 * POST   /api/v1/admin/biz-systems/{id}/toggle  启用/停用
 * DELETE /api/v1/admin/biz-systems/{id}     删除（逻辑删除）
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/admin/biz-systems")
@RequiredArgsConstructor
public class AdminBizSystemController {

    /** authConfig 中需要掩码的敏感字段 */
    private static final Set<String> SENSITIVE_KEYS = Set.of("apiKey", "api_key", "password", "secret", "token");

    private static final String MASK = "******";

    private final BizSystemMapper mapper;
    private final ObjectMapper objectMapper;

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("业务系统管理仅租户管理员可操作");
        }
        return user;
    }

    @GetMapping
    public ApiResponse<List<BizSystem>> list(@RequestParam(name = "q", required = false) String q) {
        AuthUser user = requireAdmin();
        LambdaQueryWrapper<BizSystem> wrapper = new LambdaQueryWrapper<BizSystem>()
                .eq(BizSystem::getTenantId, user.getTenantId())
                .orderByDesc(BizSystem::getCreatedAt);
        if (q != null && !q.isBlank()) {
            wrapper.and(w -> w.like(BizSystem::getName, q.trim())
                    .or().like(BizSystem::getSystemCode, q.trim()));
        }
        List<BizSystem> rows = mapper.selectList(wrapper);
        rows.forEach(this::maskOut);
        return ApiResponse.ok(rows);
    }

    @GetMapping("/{id}")
    public ApiResponse<BizSystem> detail(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        BizSystem cur = requireOwned(user, id);
        maskOut(cur);
        return ApiResponse.ok(cur);
    }

    @PostMapping
    public ApiResponse<BizSystem> create(@RequestBody BizSystem body) {
        AuthUser user = requireAdmin();
        validate(body);
        BizSystem exist = mapper.selectOne(new LambdaQueryWrapper<BizSystem>()
                .eq(BizSystem::getTenantId, user.getTenantId())
                .eq(BizSystem::getSystemCode, body.getSystemCode().trim()));
        if (exist != null) {
            throw BizException.badRequest("系统编码已存在：" + body.getSystemCode());
        }
        body.setId(null);
        body.setTenantId(user.getTenantId());
        body.setSystemCode(body.getSystemCode().trim());
        body.setCreatedBy(user.getUserId());
        body.setCreatedAt(LocalDateTime.now());
        body.setUpdatedAt(LocalDateTime.now());
        if (body.getAuthType() == null || body.getAuthType().isBlank()) body.setAuthType(BizSystem.AUTH_NONE);
        if (body.getStatus() == null || body.getStatus().isBlank()) body.setStatus(BizSystem.STATUS_ENABLED);
        mapper.insert(body);
        return ApiResponse.ok(maskOut(body));
    }

    @PutMapping("/{id}")
    public ApiResponse<BizSystem> update(@PathVariable Long id, @RequestBody BizSystem body) {
        AuthUser user = requireAdmin();
        BizSystem cur = requireOwned(user, id);
        if (body.getName() != null && !body.getName().isBlank()) {
            cur.setName(body.getName().trim());
        }
        if (body.getDescription() != null) {
            cur.setDescription(body.getDescription());
        }
        if (body.getBaseUrl() != null) {
            cur.setBaseUrl(body.getBaseUrl().trim());
        }
        if (body.getAuthType() != null && !body.getAuthType().isBlank()) {
            cur.setAuthType(body.getAuthType());
        }
        // authConfig 入参含掩码值时保留原值；否则整体替换
        if (body.getAuthConfig() != null) {
            cur.setAuthConfig(mergeAuthConfig(cur.getAuthConfig(), body.getAuthConfig()));
        }
        if (body.getDocUrl() != null) {
            cur.setDocUrl(body.getDocUrl().trim());
        }
        if (body.getDocContent() != null) {
            cur.setDocContent(body.getDocContent());
        }
        if (body.getStatus() != null && !body.getStatus().isBlank()) {
            cur.setStatus(body.getStatus());
        }
        cur.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(cur);
        return ApiResponse.ok(maskOut(cur));
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<BizSystem> toggle(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        BizSystem cur = requireOwned(user, id);
        boolean enable = !BizSystem.STATUS_ENABLED.equals(cur.getStatus());
        cur.setStatus(enable ? BizSystem.STATUS_ENABLED : BizSystem.STATUS_DISABLED);
        cur.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(cur);
        return ApiResponse.ok(maskOut(cur));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Map<String, Object>> delete(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        requireOwned(user, id);
        mapper.deleteById(id);
        return ApiResponse.ok(Map.of("id", id, "deleted", true));
    }

    private BizSystem requireOwned(AuthUser user, Long id) {
        BizSystem cur = mapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("业务系统不存在：" + id);
        }
        return cur;
    }

    private void validate(BizSystem body) {
        if (body.getSystemCode() == null || body.getSystemCode().isBlank()) {
            throw BizException.badRequest("系统编码不能为空");
        }
        if (!body.getSystemCode().matches("[A-Za-z0-9_\\-]{2,64}")) {
            throw BizException.badRequest("系统编码仅支持字母/数字/下划线/中划线，2-64 位");
        }
        if (body.getName() == null || body.getName().isBlank()) {
            throw BizException.badRequest("系统名称不能为空");
        }
        String auth = body.getAuthType() == null ? BizSystem.AUTH_NONE : body.getAuthType();
        if (!Set.of(BizSystem.AUTH_NONE, BizSystem.AUTH_API_KEY, BizSystem.AUTH_BASIC, BizSystem.AUTH_BEARER)
                .contains(auth)) {
            throw BizException.badRequest("认证方式无效：" + auth);
        }
    }

    /** 入参 authConfig 含掩码值时以库中原值回填对应字段，再整体序列化。 */
    private String mergeAuthConfig(String currentJson, String incomingJson) {
        if (incomingJson == null || incomingJson.isBlank()) {
            return incomingJson;
        }
        try {
            Map<String, Object> incoming = objectMapper.readValue(incomingJson, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {
            });
            boolean hasMask = incoming.values().stream().anyMatch(v -> MASK.equals(String.valueOf(v)));
            if (!hasMask) {
                return incomingJson;
            }
            Map<String, Object> current = currentJson == null || currentJson.isBlank()
                    ? Map.of()
                    : objectMapper.readValue(currentJson, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {
                    });
            Map<String, Object> merged = new LinkedHashMap<>(current);
            incoming.forEach((k, v) -> {
                if (!MASK.equals(String.valueOf(v))) {
                    merged.put(k, v);
                }
            });
            return objectMapper.writeValueAsString(merged);
        } catch (Exception e) {
            // 非 JSON 结构（如纯文本密钥）且非掩码值 → 原样保存
            if (MASK.equals(incomingJson)) {
                return currentJson;
            }
            return incomingJson;
        }
    }

    /** 出参掩码：authConfig 里的敏感字段值替换为 ******（原值只留在库中）。 */
    private BizSystem maskOut(BizSystem row) {
        String json = row.getAuthConfig();
        if (json == null || json.isBlank()) {
            return row;
        }
        try {
            Map<String, Object> map = objectMapper.readValue(json, new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {
            });
            map.forEach((k, v) -> {
                if (v != null && SENSITIVE_KEYS.contains(k)) {
                    map.put(k, MASK);
                }
            });
            row.setAuthConfig(objectMapper.writeValueAsString(map));
        } catch (Exception e) {
            // 非 JSON 结构的密钥文本 → 整体掩码
            log.debug("authConfig mask fallback: {}", e.getMessage());
            row.setAuthConfig(MASK);
        }
        return row;
    }
}
