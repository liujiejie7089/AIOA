package cn.aios.bridge.controller;

import cn.aios.bridge.entity.ToolDefinition;
import cn.aios.bridge.mapper.ToolDefinitionMapper;
import cn.aios.common.resp.ApiResponse;
import cn.aios.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 用户端「插件」清单（docs/58 §2.2）。数据来自 {@code tool_definition}。
 *
 * <p><b>为什么放在 bridge 而不是 resource</b>：{@code tool_definition} 表归属 bridge 模块，
 * 而 resource 不依赖 bridge（依赖方向为 resource → common/security/org），故插件接口随表所在模块走。</p>
 *
 * <p><b>只暴露用户该看的字段</b>：code / name / description / domain / riskLevel / requiresApproval。
 * <b>绝不</b>返回 endpoint / auth_ref / input_schema 等内部字段（避免泄露内部调用细节）。</p>
 *
 * <p>租户过滤：{@code tenant_id IN (0, 当前租户)}、{@code status='ACTIVE'}、{@code deleted_at IS NULL}，
 * 按 domain / tool_code 排序，上限 300（与 CatalogController#skills 同口径取租户可见行）。</p>
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class PluginCatalogController {

    private final ToolDefinitionMapper toolDefinitionMapper;

    public record PluginView(String code, String name, String description, String domain,
                            String riskLevel, Boolean requiresApproval) {
        static PluginView from(ToolDefinition t) {
            return new PluginView(t.getToolCode(), t.getName(), t.getDescription(), t.getDomain(),
                    t.getRiskLevel(), t.getRequiresApproval());
        }
    }

    @GetMapping("/plugins")
    public ApiResponse<List<PluginView>> plugins() {
        long tenantId = AuthUserContext.tenantIdOrDefault();
        List<ToolDefinition> rows = toolDefinitionMapper.selectList(
                new LambdaQueryWrapper<ToolDefinition>()
                        .in(ToolDefinition::getTenantId, 0L, tenantId)
                        .eq(ToolDefinition::getStatus, "ACTIVE")
                        .isNull(ToolDefinition::getDeletedAt)
                        .orderByAsc(ToolDefinition::getDomain)
                        .orderByAsc(ToolDefinition::getToolCode)
                        .last("LIMIT 300"));
        return ApiResponse.ok(rows.stream().map(PluginView::from).toList());
    }
}
