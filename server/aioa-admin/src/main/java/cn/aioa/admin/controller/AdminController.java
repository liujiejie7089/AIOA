package cn.aioa.admin.controller;

import cn.aioa.admin.entity.SysPermission;
import cn.aioa.admin.entity.SysRole;
import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.mapper.SysPermissionMapper;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 管理只读接口（M1 骨架）：用户/角色/权限列表。
 * 完整 CRUD 与角色授权 M3 交付。
 * 权限：仅租户管理员可访问（手动检查而非 @PreAuthorize，避免 AccessDeniedException
 * 被 GlobalExceptionHandler 兜底为 500；BizException(403) 由 handleBiz 映射为 HTTP 403）。
 */
@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {

    private final SysUserMapper userMapper;
    private final SysRoleMapper roleMapper;
    private final SysPermissionMapper permissionMapper;

    public AdminController(SysUserMapper userMapper, SysRoleMapper roleMapper,
                           SysPermissionMapper permissionMapper) {
        this.userMapper = userMapper;
        this.roleMapper = roleMapper;
        this.permissionMapper = permissionMapper;
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
        result.getRecords().forEach(u -> u.setPasswordHash(null)); // 不外泄哈希
        return ApiResponse.ok(result);
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
}
