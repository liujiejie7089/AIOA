package cn.aioa.admin.controller;

import cn.aioa.admin.entity.AppRegistry;
import cn.aioa.admin.entity.SysPermission;
import cn.aioa.admin.entity.SysRole;
import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.entity.SysUserRole;
import cn.aioa.admin.mapper.AppRegistryMapper;
import cn.aioa.admin.mapper.SysPermissionMapper;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.admin.mapper.SysUserRoleMapper;
import cn.aioa.admin.service.AppService;
import cn.aioa.admin.service.AuthService;
import cn.aioa.admin.service.PersonnelService;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 系统管理接口：人员/角色/权限列表 + 用户角色分配（即时生效）。
 *
 * <h3>权限分两层，不再一刀切</h3>
 * <ul>
 *   <li><b>人员管理</b>（{@code /personnel}、{@code /users}）：平台 / 租户 / 机构 / 部门四级管理员均可读，
 *       数据范围由 {@link PersonnelService} 按调用者档位收窄（平台全平台、租户本租户、
 *       机构本机构、部门本部门）。此前整块绑死 {@code ROLE_ADMIN}，导致机构管理员
 *       「菜单看不到 + 路由被重定向 + 接口 403」三重封闭，页面自然全空。</li>
 *   <li><b>平台级配置</b>（角色、权限点、功能模块、模型、角色分配、账号启停）：仍然仅平台管理员。
 *       这些是平台基线数据与高权写操作，租户侧只读展示即可（{@code capability} 标记在
 *       人员管理响应里回给前端，用于按钮显隐）。</li>
 * </ul>
 *
 * <p>权限用手动检查而非 {@code @PreAuthorize}：{@code aioa-common} 不引入 spring-security，
 * {@code GlobalExceptionHandler} 的 {@code Exception} 兜底会把 AccessDeniedException 吞成 500；
 * 统一抛 {@code BizException(403)} 由 {@code handleBiz} 映射为 HTTP 403。</p>
 */
@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {

    private final SysUserMapper userMapper;
    private final SysRoleMapper roleMapper;
    private final SysPermissionMapper permissionMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final AuthService authService;
    private final AppService appService;
    private final AppRegistryMapper appRegistryMapper;
    private final PersonnelService personnelService;

    public AdminController(SysUserMapper userMapper, SysRoleMapper roleMapper,
                           SysPermissionMapper permissionMapper, SysUserRoleMapper userRoleMapper,
                           AuthService authService, AppService appService,
                           AppRegistryMapper appRegistryMapper, PersonnelService personnelService) {
        this.userMapper = userMapper;
        this.roleMapper = roleMapper;
        this.permissionMapper = permissionMapper;
        this.userRoleMapper = userRoleMapper;
        this.authService = authService;
        this.appService = appService;
        this.appRegistryMapper = appRegistryMapper;
        this.personnelService = personnelService;
    }

    /** 平台级配置与写操作的闸门：仅系统管理员。 */
    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (user.getRoles() == null || !user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("该功能仅平台管理员可访问");
        }
        return user;
    }

    /**
     * 人员管理：按调用者权限作用域取数，并按 租户 / 机构 / 档位 自动分类返回。
     *
     * <p>返回体结构见 {@link PersonnelService#personnel}：包含 {@code scope / scopeName / groupBy /
     * groups / classCounts / capability}，前端据此渲染分组表格并决定是否显示操作按钮。</p>
     */
    @GetMapping("/personnel")
    public ApiResponse<Map<String, Object>> personnel(@RequestParam(required = false) String keyword,
                                                     @RequestParam(required = false) Long tenantId) {
        return ApiResponse.ok(personnelService.personnel(keyword, tenantId));
    }

    /**
     * 人员平铺列表（分页）。
     *
     * <p>与 {@code /personnel} 共用同一作用域内核 —— 修复了历史实现「全表无过滤分页」的
     * 作用域缺失（任何持有平台令牌的调用方都能翻到全部租户账号）。保留分页形态是为了
     * 兼容已有调用方。</p>
     */
    @GetMapping("/users")
    public ApiResponse<Map<String, Object>> users(@RequestParam(defaultValue = "1") long page,
                                                 @RequestParam(defaultValue = "20") long size,
                                                 @RequestParam(required = false) String keyword,
                                                 @RequestParam(required = false) Long tenantId) {
        List<Map<String, Object>> all = personnelService.visibleRows(keyword, tenantId);
        long current = Math.max(1, page);
        long pageSize = Math.max(1, size);
        int from = (int) Math.min(all.size(), (current - 1) * pageSize);
        int to = (int) Math.min(all.size(), from + pageSize);
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        result.put("records", all.subList(from, to));
        result.put("total", all.size());
        result.put("current", current);
        result.put("size", pageSize);
        result.put("pages", pageSize == 0 ? 0 : (all.size() + pageSize - 1) / pageSize);
        return ApiResponse.ok(result);
    }

    /** 分配角色：整体覆盖用户角色集合；生效机制 = JwtAuthenticationFilter 每请求实时查库。 */
    @PutMapping("/users/{id}/roles")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<Map<String, Object>> assignRoles(@PathVariable Long id,
                                                        @RequestBody Map<String, List<Long>> body) {
        AuthUser admin = requireAdmin();
        SysUser target = userMapper.selectById(id);
        if (target == null) {
            throw BizException.notFound("用户不存在：" + id);
        }
        List<Long> roleIds = body == null || body.get("roleIds") == null ? List.of() : body.get("roleIds");
        if (roleIds == null) roleIds = List.of();
        // 校验角色合法 + 禁止移除自己的管理员角色（防自锁）
        List<Long> validIds = roleMapper.selectBatchIds(roleIds == null ? List.of() : roleIds)
                .stream().map(SysRole::getId).toList();
        boolean stillAdmin = validIds.stream().anyMatch(rid -> {
            SysRole r = roleMapper.selectById(rid);
            return r != null && "ROLE_ADMIN".equals(r.getRoleCode());
        });
        if (Objects.equals(admin.getUserId(), id) && !stillAdmin) {
            throw BizException.badRequest("不能移除自己的管理员角色");
        }
        userRoleMapper.delete(new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, id));
        for (Long rid : validIds) {
            SysUserRole ur = new SysUserRole();
            ur.setUserId(id);
            ur.setRoleId(rid);
            userRoleMapper.insert(ur);
        }
        List<String> codes = authService.roleCodesOf(id);
        return ApiResponse.ok(Map.of("userId", id, "roles", codes));
    }

    /** 调整账号状态（启用/停用）：停用后登录被拒，存量 token 每请求实时校验角色时感知停用。 */
    @PutMapping("/users/{id}/status")
    public ApiResponse<Map<String, Object>> changeStatus(@PathVariable Long id,
                                                         @RequestBody Map<String, String> body) {
        requireAdmin();
        SysUser target = userMapper.selectById(id);
        if (target == null) {
            throw BizException.notFound("用户不存在：" + id);
        }
        String status = body == null ? null : body.get("status");
        if (!"ENABLED".equals(status) && !"DISABLED".equals(status)) {
            throw BizException.badRequest("status 仅支持 ENABLED / DISABLED");
        }
        // 保护：不能停用管理员角色账号（避免租户管理断链）
        if ("DISABLED".equals(status) && authService.roleCodesOf(id).contains("ROLE_ADMIN")) {
            throw BizException.badRequest("不能停用管理员账号");
        }
        SysUser patch = new SysUser();
        patch.setId(id);
        patch.setStatus(status);
        userMapper.updateById(patch);
        return ApiResponse.ok(Map.of("userId", id, "status", status));
    }

    @GetMapping("/roles")
    public ApiResponse<List<SysRole>> roles() {
        requireAdmin();
        return ApiResponse.ok(roleMapper.selectList(null));
    }

    @GetMapping("/permissions")
    public ApiResponse<List<SysPermission>> permissions() {
        requireAdmin();
        return ApiResponse.ok(permissionMapper.selectList(null));
    }

    // ---------- 功能管理（应用/模块开关与可见范围） ----------

    /** 全量应用列表（含禁用），供管理端功能管理页面。 */
    @GetMapping("/apps")
    public ApiResponse<List<cn.aioa.admin.entity.AppRegistry>> apps() {
        requireAdmin();
        return ApiResponse.ok(appService.allApps());
    }

    /** 更新功能配置：启用/禁用 + 可见范围（ALL/ADMIN）+ 名称/排序。 */
    @PutMapping("/apps/{code}")
    public ApiResponse<cn.aioa.admin.entity.AppRegistry> updateApp(@PathVariable String code,
                                                                   @RequestBody Map<String, Object> body) {
        requireAdmin();
        cn.aioa.admin.entity.AppRegistry app = appService.byCode(code);
        if (app == null) {
            throw BizException.notFound("功能模块不存在：" + code);
        }
        if (body.get("enabled") instanceof Boolean b) {
            app.setEnabled(b);
        }
        if (body.get("visibleScope") instanceof String scope && !scope.isBlank()) {
            if (!"ALL".equals(scope) && !"ADMIN".equals(scope)) {
                throw BizException.badRequest("visibleScope 仅支持 ALL / ADMIN");
            }
            app.setVisibleScope(scope);
        }
        if (body.get("name") instanceof String name && !name.isBlank()) {
            app.setName(name);
        }
        if (body.get("sort") instanceof Number n) {
            app.setSort(n.intValue());
        }
        appRegistryMapper.updateById(app);
        return ApiResponse.ok(app);
    }
}
