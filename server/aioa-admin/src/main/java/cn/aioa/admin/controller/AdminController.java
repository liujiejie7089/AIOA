package cn.aioa.admin.controller;

import cn.aioa.admin.entity.SysPermission;
import cn.aioa.admin.entity.SysRole;
import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.mapper.SysPermissionMapper;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.common.resp.ApiResponse;
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

    @GetMapping("/users")
    public ApiResponse<IPage<SysUser>> users(@RequestParam(defaultValue = "1") long page,
                                             @RequestParam(defaultValue = "20") long size) {
        IPage<SysUser> result = userMapper.selectPage(new Page<>(page, size), null);
        result.getRecords().forEach(u -> u.setPasswordHash(null)); // 不外泄哈希
        return ApiResponse.ok(result);
    }

    @GetMapping("/roles")
    public ApiResponse<List<SysRole>> roles() {
        return ApiResponse.ok(roleMapper.selectList(null));
    }

    @GetMapping("/permissions")
    public ApiResponse<List<SysPermission>> permissions() {
        return ApiResponse.ok(permissionMapper.selectList(null));
    }
}
