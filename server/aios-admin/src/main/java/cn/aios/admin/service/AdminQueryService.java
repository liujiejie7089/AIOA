package cn.aios.admin.service;

import cn.aios.admin.entity.SysPermission;
import cn.aios.admin.entity.SysRole;
import cn.aios.admin.entity.SysUser;
import cn.aios.admin.mapper.SysPermissionMapper;
import cn.aios.admin.mapper.SysRoleMapper;
import cn.aios.admin.mapper.SysUserMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 系统管理只读查询（M1）。
 */
@Service
@RequiredArgsConstructor
public class AdminQueryService {

    private final SysUserMapper userMapper;
    private final SysRoleMapper roleMapper;
    private final SysPermissionMapper permissionMapper;

    public List<SysUser> users() {
        return userMapper.selectList(new LambdaQueryWrapper<SysUser>().orderByAsc(SysUser::getId));
    }

    public List<SysRole> roles() {
        return roleMapper.selectList(new LambdaQueryWrapper<SysRole>().orderByAsc(SysRole::getId));
    }

    public List<SysPermission> permissions() {
        return permissionMapper.selectList(new LambdaQueryWrapper<SysPermission>()
                .orderByAsc(SysPermission::getSort)
                .orderByAsc(SysPermission::getId));
    }
}
