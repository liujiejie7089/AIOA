package cn.aioa.resource.service;

import cn.aioa.resource.entity.ClientActivityLog;
import cn.aioa.resource.mapper.ClientActivityLogMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 用户端操作记录：写入失败不影响主流程（记录是审计性质的旁路）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ActivityLogService {

    private final ClientActivityLogMapper activityLogMapper;

    public List<ClientActivityLog> list(Long tenantId, Long userId, int limit) {
        return activityLogMapper.selectList(new LambdaQueryWrapper<ClientActivityLog>()
                .eq(ClientActivityLog::getTenantId, tenantId == null ? 0L : tenantId)
                .in(ClientActivityLog::getUserId, BillingService.scopeUsers(userId))
                .orderByDesc(ClientActivityLog::getCreatedAt)
                .last("limit " + Math.max(1, Math.min(limit, 200))));
    }

    public void record(Long tenantId, Long userId, String action) {
        record(tenantId, userId, action, "ok", "成功");
    }

    public void record(Long tenantId, Long userId, String action, String status, String label) {
        try {
            ClientActivityLog row = new ClientActivityLog();
            row.setTenantId(tenantId == null ? 0L : tenantId);
            row.setUserId(userId == null ? 0L : userId);
            row.setAction(action);
            row.setStatus(status == null ? "ok" : status);
            row.setLabel(label == null ? "成功" : label);
            row.setCreatedAt(LocalDateTime.now());
            row.setCreatedBy(userId);
            activityLogMapper.insert(row);
        } catch (Exception e) {
            log.warn("write client activity log failed: {}", e.getMessage());
        }
    }
}
