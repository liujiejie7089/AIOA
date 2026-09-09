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
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
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
import java.util.stream.Collectors;

/**
 * 系统管理接口：用户/角色/权限列表 + 用户角色分配（即时生效）。
 * 权限：仅租户管理员可访问（手动检查而非 @PreAuthorize，避免 AccessDeniedException
 * 被 GlobalExceptionHandler 兜底为 500；BizException(403) 由 handleBiz 映射为 HTTP 403）。
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

    public AdminController(SysUserMapper userMapper, SysRoleMapper roleMapper,
                           SysPermissionMapper permissionMapper, SysUserRoleMapper userRoleMapper,
                           AuthService authService, AppService appService,
                           AppRegistryMapper appRegistryMapper) {
        this.userMapper = userMapper;
        this.roleMapper = roleMapper;
        this.permissionMapper = permissionMapper;
        this.userRoleMapper = userRoleMapper;
        this.authService = authService;
        this.appService = appService;
        this.appRegistryMapper = appRegistryMapper;
    }

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("系统管理仅租户管理员可访问");
        }
        return user;
    }

    @GetMapping("/users")
    public ApiResponse<IPage<SysUser>> users(@RequestParam(defaultValue = "1") long page,
                                             @RequestParam(defaultValue = "20") long size) {
        requireAdmin();
        IPage<SysUser> result = userMapper.selectPage(new Page<>(page, size), null);
        List<SysUser> records = result.getRecords();
        if (!records.isEmpty()) {
            // 每个用户补充当前角色码（分配角色界面展示用）
            List<Long> ids = records.stream().map(SysUser::getId).toList();
            Map<Long, List<Long>> uid2RoleIds = userRoleMapper.selectList(
                            new LambdaQueryWrapper<SysUserRole>().in(SysUserRole::getUserId, ids))
                    .stream().collect(Collectors.groupingBy(SysUserRole::getUserId,
                            Collectors.mapping(SysUserRole::getRoleId, Collectors.toList())));
            List<Long> allRoleIds = uid2RoleIds.values().stream().flatMap(List::stream).distinct().toList();
            Map<Long, String> roleId2Code = allRoleIds.isEmpty() ? Map.of()
                    : roleMapper.selectBatchIds(allRoleIds).stream()
                            .collect(Collectors.toMap(SysRole::getId, SysRole::getRoleCode));
            records.forEach(u -> {
                u.setPasswordHash(null); // 不外泄哈希
                u.setRoles(uid2RoleIds.getOrDefault(u.getId(), List.of()).stream()
                        .map(roleId2Code::get).filter(Objects::nonNull).sorted().toList());
            });
        }
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
