package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.ExpertConfig;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.service.ExpertConfigService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
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

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 多租户专家配置（方案 P1 / B2–B6）。
 *
 * <pre>
 * GET    /api/v1/expert-config/experts                 —— 当前用户可见的专家（全局模板 + 本租户副本，带生效配置）
 * GET    /api/v1/expert-config/experts/{key}           —— 单个专家详情（含覆盖链路与来源）
 * GET    /api/v1/expert-config/experts/{key}/resolve   —— 只返回解析结果（验证「配置真实生效」用）
 * POST   /api/v1/expert-config/experts/{key}/config    —— 写入某层配置片段（merge=false 整体替换）
 * PUT    /api/v1/expert-config/experts/{key}/config    —— 局部更新某层配置片段（merge=true）
 * DELETE /api/v1/expert-config/experts/{key}/config    —— 删除某层配置片段
 * POST   /api/v1/expert-config/templates/{key}/import  —— 从全局模板导入为租户副本
 * GET    /api/v1/expert-config/templates               —— 全局模板清单
 * </pre>
 *
 * <p>权限：读接口对所有登录用户开放（按可见范围过滤）；写接口要求
 * ROLE_ADMIN 或 ROLE_TENANT_ADMIN，且只能改自己租户的配置。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/expert-config")
@RequiredArgsConstructor
public class ExpertConfigController {

    private final ExpertConfigService configService;
    private final AiExpertMapper expertMapper;

    // ---------- 读 ----------

    /** 当前用户可见的专家列表（全局模板 + 本租户副本，按 enabled/visibleScope/sort 过滤）。 */
    @GetMapping("/experts")
    public ApiResponse<List<Map<String, Object>>> experts() {
        AuthUser user = AuthUserContext.get();
        if (user == null) {
            throw new BizException(401, "未登录");
        }
        Long tenantId = user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;

        List<AiExpert> rows = expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                .and(w -> w.eq(AiExpert::getTenantId, 0L).or().eq(AiExpert::getTenantId, tid))
                .orderByAsc(AiExpert::getSort));

        // 租户副本覆盖同名全局模板
        Map<String, AiExpert> byKey = new LinkedHashMap<>();
        for (AiExpert e : rows) {
            AiExpert exist = byKey.get(e.getExpertKey());
            if (exist == null || (e.getTenantId() != null && e.getTenantId() > 0)) {
                byKey.put(e.getExpertKey(), e);
            }
        }

        List<Map<String, Object>> out = new ArrayList<>();
        for (AiExpert e : byKey.values()) {
            ExpertConfigService.ResolvedConfig rc = configService.resolve(
                    tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(), e.getExpertKey());
            if (!Boolean.TRUE.equals(rc.settings().getEnabled()) && !isAdmin(user)) {
                continue; // 关闭的专家对普通用户不可见（管理员仍可见以便配置）
            }
            if (!visible(rc.settings().getVisibleScope(), user)) {
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>(rc.toPayload());
            m.put("id", e.getId());
            m.put("name", e.getName());
            m.put("icon", e.getIcon());
            m.put("summary", e.getSummary());
            m.put("intro", e.getIntro());
            m.put("category", e.getCategory());
            m.put("templateVersion", e.getTemplateVersion());
            m.put("isTenantCopy", e.getTenantId() != null && e.getTenantId() > 0);
            out.add(m);
        }
        out.sort((a, b) -> Integer.compare(asInt(a.get("sort")), asInt(b.get("sort"))));
        return ApiResponse.ok(out);
    }

    /** 单个专家：详情 + 覆盖链路（每层片段）。 */
    @GetMapping("/experts/{key}")
    public ApiResponse<Map<String, Object>> detail(@PathVariable("key") String key) {
        AuthUser user = requireUser();
        Long tenantId = user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;
        ExpertConfigService.ResolvedConfig rc = configService.resolve(
                tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(), key);
        Map<String, Object> m = new LinkedHashMap<>(rc.toPayload());
        m.put("layers", rc.layers());
        m.put("fragments", configService.list(tid, key));
        return ApiResponse.ok(m);
    }

    /** 只返回解析结果：供 agent 与自检脚本核对「配置是否真实生效」。 */
    @GetMapping("/experts/{key}/resolve")
    public ApiResponse<Map<String, Object>> resolve(@PathVariable("key") String key,
                                                    @RequestParam(value = "userId", required = false) Long userId,
                                                    @RequestParam(value = "deptId", required = false) Long deptId,
                                                    @RequestParam(value = "institutionId", required = false) Long institutionId) {
        AuthUser user = requireUser();
        Long tenantId = user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;
        ExpertConfigService.ResolvedConfig rc = configService.resolve(
                tid, institutionId, deptId, userId, key);
        return ApiResponse.ok(rc.toPayload());
    }

    /** 全局模板清单（tenant_id=0）。 */
    @GetMapping("/templates")
    public ApiResponse<List<AiExpert>> templates() {
        requireUser();
        return ApiResponse.ok(expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .orderByAsc(AiExpert::getSort)));
    }

    // ---------- 写 ----------

    public record ConfigBody(String scopeType, Long scopeId, Map<String, Object> config) {
    }

    /** 写入/替换某层配置片段。 */
    @PostMapping("/experts/{key}/config")
    public ApiResponse<Map<String, Object>> save(@PathVariable("key") String key,
                                                 @RequestBody ConfigBody body) {
        AuthUser user = requireAdmin();
        ExpertConfig row = configService.save(user.getTenantId(), body.scopeType(), body.scopeId(),
                key, body.config(), false, user.getUserId());
        return ApiResponse.ok(Map.of("id", row.getId(), "scopeType", row.getScopeType(),
                "scopeId", row.getScopeId(), "expertKey", row.getExpertKey()));
    }

    /** 局部更新某层配置片段（只覆盖传入的键）。 */
    @PutMapping("/experts/{key}/config")
    public ApiResponse<Map<String, Object>> patch(@PathVariable("key") String key,
                                                  @RequestBody ConfigBody body) {
        AuthUser user = requireAdmin();
        ExpertConfig row = configService.save(user.getTenantId(), body.scopeType(), body.scopeId(),
                key, body.config(), true, user.getUserId());
        return ApiResponse.ok(Map.of("id", row.getId(), "scopeType", row.getScopeType(),
                "scopeId", row.getScopeId(), "expertKey", row.getExpertKey()));
    }

    /** 删除某层配置片段。 */
    @DeleteMapping("/experts/{key}/config")
    public ApiResponse<Boolean> delete(@PathVariable("key") String key,
                                       @RequestParam("scopeType") String scopeType,
                                       @RequestParam(value = "scopeId", required = false) Long scopeId) {
        AuthUser user = requireAdmin();
        configService.delete(user.getTenantId(), scopeType, scopeId, key);
        return ApiResponse.ok(true);
    }

    /** 从全局模板导入为租户副本（已存在则更新，不重复创建）。 */
    @PostMapping("/templates/{key}/import")
    public ApiResponse<Map<String, Object>> importTemplate(@PathVariable("key") String key) {
        AuthUser user = requireAdmin();
        Long tenantId = user.getTenantId();
        if (tenantId == null || tenantId <= 0) {
            throw BizException.badRequest("平台级账号无租户上下文，无法导入租户副本");
        }
        AiExpert tpl = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .eq(AiExpert::getExpertKey, key));
        if (tpl == null) {
            throw BizException.notFound("全局模板不存在：" + key);
        }
        AiExpert copy = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, tenantId)
                .eq(AiExpert::getExpertKey, key));
        boolean created = copy == null;
        if (created) {
            copy = new AiExpert();
            copy.setTenantId(tenantId);
            copy.setExpertKey(key);
            copy.setCreatedBy(user.getUserId());
        }
        copy.setName(tpl.getName());
        copy.setIcon(tpl.getIcon());
        copy.setSummary(tpl.getSummary());
        copy.setIntro(tpl.getIntro());
        copy.setTags(tpl.getTags());
        copy.setRecs(tpl.getRecs());
        copy.setAgentCode(tpl.getAgentCode());
        copy.setCategory(tpl.getCategory());
        copy.setTemplateVersion(tpl.getTemplateVersion());
        copy.setSourceTemplateId(tpl.getId());
        copy.setVisibleScope(tpl.getVisibleScope());
        copy.setKbScope(tpl.getKbScope());
        copy.setDefaultEnabled(tpl.getDefaultEnabled());
        copy.setEnabled(true);
        copy.setSort(tpl.getSort());
        if (created) {
            expertMapper.insert(copy);
        } else {
            expertMapper.updateById(copy);
        }
        log.info("expert template imported: tenant={} key={} created={}", tenantId, key, created);
        return ApiResponse.ok(Map.of("id", copy.getId(), "expertKey", key, "created", created));
    }

    // ---------- 内部 ----------

    private AuthUser requireUser() {
        AuthUser user = AuthUserContext.get();
        if (user == null) {
            throw new BizException(401, "未登录");
        }
        return user;
    }

    private AuthUser requireAdmin() {
        AuthUser user = requireUser();
        if (!isAdmin(user)) {
            throw BizException.forbidden("专家配置仅平台管理员或租户管理员可操作");
        }
        return user;
    }

    private static boolean isAdmin(AuthUser user) {
        List<String> roles = user.getRoles();
        return roles != null && (roles.contains("ROLE_ADMIN") || roles.contains("ROLE_TENANT_ADMIN"));
    }

    /** 可见范围判定：ALL 全员；其余按层级比对当前用户所属作用域。 */
    private static boolean visible(String scope, AuthUser user) {
        if (scope == null || scope.isBlank() || "ALL".equalsIgnoreCase(scope)) {
            return true;
        }
        String s = scope.toUpperCase();
        Long v = switch (s) {
            case "TENANT" -> user.getTenantId();
            case "INSTITUTION" -> user.getInstitutionId();
            case "DEPT" -> user.getDepartmentId();
            case "USER" -> user.getUserId();
            default -> null;
        };
        return v != null && v > 0;
    }

    private static int asInt(Object v) {
        return v instanceof Number n ? n.intValue() : 100;
    }
}
