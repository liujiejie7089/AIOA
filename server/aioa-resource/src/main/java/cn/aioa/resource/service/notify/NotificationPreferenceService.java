package cn.aioa.resource.service.notify;

import cn.aioa.resource.entity.NotificationPreference;
import cn.aioa.resource.mapper.NotificationPreferenceMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 用户级通知通道偏好：查询与保存。
 *
 * <p>偏好按 (tenant_id, user_id, type) 唯一；type 为 NULL 即默认行。
 * 精确匹配 type 优先于默认行（解析在 {@code NotificationDispatcher} 完成）。</p>
 */
@Service
@RequiredArgsConstructor
public class NotificationPreferenceService {

    private final NotificationPreferenceMapper preferenceMapper;

    /** 返回 {defaultChannels:[...], byType:{type:[...]}}。 */
    public Map<String, Object> get(Long tenantId, Long userId) {
        List<NotificationPreference> rows = preferenceMapper.selectList(new LambdaQueryWrapper<NotificationPreference>()
                .eq(NotificationPreference::getTenantId, tenantId)
                .eq(NotificationPreference::getUserId, userId));

        Set<String> defaultChannels = null;
        Map<String, Object> byType = new LinkedHashMap<>();
        for (NotificationPreference p : rows) {
            List<String> ch = parseChannels(p.getChannels());
            if (p.getType() == null) {
                defaultChannels = new LinkedHashSet<>(ch);
            } else {
                byType.put(p.getType(), ch);
            }
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("defaultChannels", defaultChannels == null ? List.of() : new ArrayList<>(defaultChannels));
        m.put("byType", byType);
        return m;
    }

    /** 保存默认偏好 + 按类型偏好，返回最新偏好视图。 */
    public Map<String, Object> put(Long tenantId, Long userId, List<String> defaultChannels,
                                   Map<String, Object> byType, Long actorUserId) {
        upsert(tenantId, userId, null, defaultChannels, actorUserId);
        if (byType != null) {
            for (Map.Entry<String, Object> e : byType.entrySet()) {
                upsert(tenantId, userId, e.getKey(), parseChannels(e.getValue()), actorUserId);
            }
        }
        return get(tenantId, userId);
    }

    private void upsert(Long tenantId, Long userId, String type, List<String> channels, Long actorUserId) {
        LambdaQueryWrapper<NotificationPreference> q = new LambdaQueryWrapper<NotificationPreference>()
                .eq(NotificationPreference::getTenantId, tenantId)
                .eq(NotificationPreference::getUserId, userId);
        if (type == null) {
            q.isNull(NotificationPreference::getType);
        } else {
            q.eq(NotificationPreference::getType, type);
        }
        // 取 1 行收口：type=NULL 的默认行不受唯一键约束（MySQL 唯一键不约束 NULL），
        // 并发双击保存理论上可插入两行默认偏好；此时 selectOne 会抛 TooManyResultsException
        // 把接口打成 500 且此后永久失败。limit 1 让读取始终可用（与 GiteeTenantInitService.findRow 同款）。
        q.last("limit 1");
        NotificationPreference existing = preferenceMapper.selectOne(q);
        String channelsStr = (channels == null || channels.isEmpty()) ? null : String.join(",", channels);
        if (existing == null) {
            NotificationPreference p = new NotificationPreference();
            p.setTenantId(tenantId);
            p.setUserId(userId);
            p.setType(type);
            p.setChannels(channelsStr);
            p.setCreatedBy(actorUserId);
            p.setCreatedAt(LocalDateTime.now());
            preferenceMapper.insert(p);
        } else {
            existing.setChannels(channelsStr);
            existing.setUpdatedBy(actorUserId);
            existing.setUpdatedAt(LocalDateTime.now());
            preferenceMapper.updateById(existing);
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> parseChannels(Object v) {
        if (v == null) {
            return List.of();
        }
        if (v instanceof List<?> list) {
            return list.stream().map(String::valueOf).filter(s -> !s.isBlank()).toList();
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) {
            return List.of();
        }
        return java.util.Arrays.stream(s.split(","))
                .map(String::trim).filter(x -> !x.isEmpty()).toList();
    }
}
