package cn.aioa.org.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.service.OrgScopeStatsService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 用户端首页「本组织数据」（V63）。
 *
 * <p>与 {@code aioa-chat} 的 {@code StatsController}（{@code /api/v1/stats/home|me}）同前缀不同路径，
 * 各管一摊：那个管<b>管理端首页</b>与<b>个人</b>统计，本类管<b>按角色放大的组织口径</b>。
 * 之所以放在 {@code aioa-org} 而不是合并进 {@code StatsController}：
 * 组织数据的口径（谁属于哪个机构/部门）只有 org 模块有裁决权
 * （{@code OrgGuard} + {@code org_member}），搬到别处就会变成第二份口径。</p>
 */
@RestController
@RequestMapping("/api/v1/stats")
@RequiredArgsConstructor
public class OrgScopeStatsController {

    private final OrgScopeStatsService orgScopeStatsService;

    /**
     * 本组织数据。
     *
     * <p>返回 {@code scope}（TENANT / INSTITUTION / DEPARTMENT / NONE）与 {@code canSeeOrg}。
     * 前端据此决定是否渲染该卡 —— <b>范围由后端说了算，前端不参与判定</b>。</p>
     */
    @GetMapping("/org")
    public ApiResponse<Map<String, Object>> org() {
        return ApiResponse.ok(orgScopeStatsService.orgScope());
    }

    /** 范围口径说明（前端用于在卡片上解释「为什么我看到的是这个范围」）。 */
    @GetMapping("/org/scopes")
    public ApiResponse<List<Map<String, Object>>> scopes() {
        return ApiResponse.ok(orgScopeStatsService.scopeCatalog());
    }
}
