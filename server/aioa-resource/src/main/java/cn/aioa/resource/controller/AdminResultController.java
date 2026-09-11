package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.UserResult;
import cn.aioa.resource.mapper.UserResultMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 成果沉淀 —— 管理端查看（V1.2 新增，只读 + 删除）：
 *   GET    /api/v1/admin/results        —— 本租户全部成员成果
 *   DELETE /api/v1/admin/results/{id}   —— 删除（软删）
 */
@RestController
@RequestMapping("/api/v1/admin/results")
@RequiredArgsConstructor
public class AdminResultController {

    private final UserResultMapper resultMapper;

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        // 租户级运营能力：平台管理员可跨租户，租户管理员管本租户；
        // 所有查询均已按 user.getTenantId() 过滤，放开不会跨租户泄露数据。
        if (!user.getRoles().contains("ROLE_ADMIN") && !user.getRoles().contains("ROLE_TENANT_ADMIN")) {
            throw BizException.forbidden("成果查看仅平台管理员或租户管理员可操作");
        }
        return user;
    }

    @GetMapping
    public ApiResponse<List<UserResult>> list() {
        AuthUser user = requireAdmin();
        return ApiResponse.ok(resultMapper.selectList(new LambdaQueryWrapper<UserResult>()
                .eq(UserResult::getTenantId, user.getTenantId())
                .orderByDesc(UserResult::getId)));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Boolean> delete(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        UserResult cur = resultMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("成果不存在：" + id);
        }
        return ApiResponse.ok(resultMapper.deleteById(id) > 0);
    }
}
