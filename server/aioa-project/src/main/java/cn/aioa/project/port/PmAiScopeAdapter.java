package cn.aioa.project.port;

import cn.aioa.project.service.PmDigitalWorkerService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * {@link PmAiScopePort} 的实现：把跨模块只读调用**转发**到
 * {@link PmDigitalWorkerService}——判定逻辑只在那里实现一份，本类不做任何业务判断
 * （否则又变成第二处口径）。
 */
@Component
@RequiredArgsConstructor
public class PmAiScopeAdapter implements PmAiScopePort {

    private final PmDigitalWorkerService digitalWorkerService;

    @Override
    public boolean isWorkerUsable(Long tenantId, Long projectId, Long workerId) {
        return digitalWorkerService.isWorkerUsable(tenantId, projectId, workerId);
    }

    @Override
    public Map<String, Object> effectiveScope(Long tenantId, Long projectId, Long workerId) {
        return digitalWorkerService.effectiveScopeInternal(tenantId, projectId, workerId);
    }
}
