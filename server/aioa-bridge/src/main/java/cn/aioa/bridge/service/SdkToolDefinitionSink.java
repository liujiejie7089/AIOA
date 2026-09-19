package cn.aioa.bridge.service;

import cn.aioa.bridge.entity.ToolDefinition;
import cn.aioa.bridge.mapper.ToolDefinitionMapper;
import cn.aioa.tool.sdk.LocalToolRegistry;
import cn.aioa.tool.sdk.ToolDefinitionSink;
import cn.aioa.tool.sdk.ToolSpec;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 把 SDK 的 {@code @AioaTool} 声明落成平台工具定义（{@link ToolDefinitionSink} 的实现）。
 *
 * <p>两件事：写进程内注册表（供本地调用）、upsert 一行 {@code tool_definition}
 * （供清单展示、权限配置、审批配置、调用审计引用）。</p>
 *
 * <p><b>为什么是 upsert 而不是 insert</b>：同一个 code 在开发期会被反复注册
 * （改描述、改风险级别），若用 insert 会撞唯一键、或留下多份不一致的定义。
 * 以 (tenant_id=0, tool_code, version) 为键覆盖，保证「代码即真相」。</p>
 *
 * <p><b>status 恒为 ACTIVE</b>：注解里的工具就是当前代码里存在的工具。
 * 要临时下线应该走管理端改 status（此时注解仍会覆盖回去）——
 * 若要真正移除，就删掉注解方法：这是刻意的「声明优先」口径，
 * 避免出现「代码删了、定义还在、调用报错」的幽灵工具。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SdkToolDefinitionSink implements ToolDefinitionSink {

    private final ToolDefinitionMapper definitionMapper;
    private final LocalToolRegistry localToolRegistry;

    @Override
    public void register(ToolSpec spec) {
        localToolRegistry.put(spec);
        try {
            upsert(spec);
        } catch (RuntimeException e) {
            // 落库失败不阻断启动：本地注册表已可用，工具仍能通过本地路径被调用
            log.error("SDK 工具定义落库失败：code={}", spec.toolCode(), e);
        }
    }

    private void upsert(ToolSpec spec) {
        List<ToolDefinition> existing = definitionMapper.selectList(new LambdaQueryWrapper<ToolDefinition>()
                .eq(ToolDefinition::getTenantId, ToolRegistryService.GLOBAL_TENANT_ID)
                .eq(ToolDefinition::getToolCode, spec.toolCode())
                .eq(ToolDefinition::getVersion, spec.version())
                .isNull(ToolDefinition::getDeletedAt));
        ToolDefinition def = existing.isEmpty() ? new ToolDefinition() : existing.get(0);
        boolean creating = existing.isEmpty();

        def.setTenantId(ToolRegistryService.GLOBAL_TENANT_ID);
        def.setToolCode(spec.toolCode());
        def.setVersion(spec.version());
        def.setName(spec.displayName());
        def.setDescription(spec.description());
        def.setDomain(spec.domain() == null || spec.domain().isBlank() ? "sdk" : spec.domain());
        def.setSystemCode(spec.systemCode());
        def.setEndpoint(spec.endpoint());
        def.setHttpMethod("LOCAL");
        def.setInputSchema(spec.inputSchema());
        def.setRiskLevel(spec.riskLevel());
        def.setRequiresApproval(spec.requiresApproval());
        def.setIdempotencyRequired(spec.idempotencyRequired());
        def.setStatus("ACTIVE");
        def.setOwner(spec.owner());
        def.setUpdatedAt(LocalDateTime.now());
        if (creating) {
            def.setCreatedAt(LocalDateTime.now());
            def.setCreatedBy(0L);
            definitionMapper.insert(def);
        } else {
            definitionMapper.updateById(def);
        }
    }
}
