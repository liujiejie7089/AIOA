package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.mapper.ClientActivityLogMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 操作审计（管理端，技术方案 5.2 权限管理「权限变更审计」一期要求）：
 * 租户内操作日志倒序展示（谁在什么时间做了什么、结果如何）。
 *   GET /api/v1/admin/audit-logs?limit=100
 */
@RestController
@RequestMapping("/api/v1/admin/audit-logs")
@RequiredArgsConstructor
public class AdminAuditController {

    private final ClientActivityLogMapper logMapper;

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(@RequestParam(name = "limit", defaultValue = "100") int limit) {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("操作审计仅租户管理员可查看");
        }
        int size = Math.max(1, Math.min(limit, 500));
        return ApiResponse.ok(logMapper.selectRecentAudit(user.getTenantId(), size));
    }
}
