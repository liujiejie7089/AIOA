package cn.aioa.resource.service.notify;

import cn.aioa.common.event.NotificationRequested;
import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.Notification;
import cn.aioa.resource.entity.NotificationChannelConfig;
import cn.aioa.resource.entity.NotificationDelivery;
import cn.aioa.resource.entity.NotificationPreference;
import cn.aioa.resource.mapper.NotificationDeliveryMapper;
import cn.aioa.resource.mapper.NotificationPreferenceMapper;
import cn.aioa.resource.mapper.NotificationChannelConfigMapper;
import cn.aioa.resource.mapper.NotificationMapper;
import cn.aioa.resource.mapper.SysUserLiteMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 通知分发器：监听 {@link NotificationRequested} 事件，异步把通知投递到各启用通道。
 *
 * <p>设计纪律：</p>
 * <ul>
 *   <li><b>异步</b>：{@link #onNotificationRequested} 标 {@code @Async}，分发发 HTTP，
 *       绝不阻塞审批主流程（与 GiteeClient 的异步队列同理）。</li>
 *   <li><b>最外层吞异常</b>：任何异常只记日志，绝不抛回调用方（写通知是主流程）。</li>
 *   <li><b>逐通道独立 try/catch</b>：单通道失败不影响其它通道。</li>
 *   <li><b>已知限制如实记录</b>：EMAIL 取不到邮箱 / SMS·PUSH 未建模收件地址 → 记 SKIPPED，
 *       不静默成功、不连坐整条通知。</li>
 * </ul>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationDispatcher {

    private final List<NotificationChannel> channels;
    private final NotificationChannelConfigMapper configMapper;
    private final NotificationDeliveryMapper deliveryMapper;
    private final NotificationPreferenceMapper preferenceMapper;
    private final SysUserLiteMapper userMapper;
    private final NotificationMapper notificationMapper;
    private final ObjectMapper objectMapper;

    // -------------------------------------------------------------- 异步监听

    @EventListener
    @Async
    public void onNotificationRequested(NotificationRequested event) {
        try {
            dispatch(event);
        } catch (Exception e) {
            log.warn("通知分发异常（已吞掉，不影响主流程）tenant={} user={} title={} err={}",
                    event.tenantId(), event.userId(), event.title(), e.getMessage());
        }
    }

    private void dispatch(NotificationRequested event) {
        Long tenantId = event.tenantId();
        Long userId = event.userId();

        Set<String> enabled = enabledChannels(tenantId);
        Set<String> pref = preferredChannels(tenantId, userId, event.type());

        for (NotificationChannel ch : channels) {
            String code = ch.code();
            if (!enabled.contains(code)) {
                continue;
            }
            if (pref != null && !pref.contains(code)) {
                continue; // 用户偏好显式排除该通道
            }
            DeliveryContext ctx = buildContext(event, code);
            String to = resolveTo(ch, ctx);

            String status;
            String error = null;
            LocalDateTime sentAt = null;
            if (to == null && !"INAPP".equals(code)) {
                status = "SKIPPED";
                error = "EMAIL".equals(code)
                        ? "未找到收件邮箱"
                        : "企业未提供该通道的收件地址（手机号/设备令牌尚未建模）";
            } else {
                try {
                    ch.send(ctx);
                    status = "SENT";
                    sentAt = LocalDateTime.now();
                } catch (Exception e) {
                    status = "FAILED";
                    error = truncate(e.getMessage(), 512);
                }
            }
            writeDelivery(tenantId, event.notificationId(), code, status, 1, error, sentAt);
        }
    }

    // -------------------------------------------------------------- 同步重试（控制器调用）

    /**
     * 重投一条投递记录（同步）。仅 FAILED/SKIPPED 可重试；无关联通知（机构侧历史）无法重试。
     */
    public Map<String, Object> retryDelivery(Long tenantId, Long deliveryId, Long actorUserId) {
        NotificationDelivery d = deliveryMapper.selectById(deliveryId);
        if (d == null || !tenantId.equals(d.getTenantId())) {
            throw BizException.notFound("投递记录不存在");
        }
        if (!"FAILED".equals(d.getStatus()) && !"SKIPPED".equals(d.getStatus())) {
            return result(d.getChannelCode(), d.getStatus(), "该投递无需重试", d.getSentAt());
        }
        if (d.getNotificationId() == null) {
            throw BizException.badRequest("该投递记录缺少关联通知（机构侧历史通知），无法重试");
        }
        Notification n = notificationMapper.selectById(d.getNotificationId());
        if (n == null) {
            throw BizException.notFound("关联通知不存在");
        }

        Map<String, Object> cfg = channelConfig(tenantId, d.getChannelCode());
        DeliveryContext ctx = new DeliveryContext();
        ctx.setTenantId(tenantId);
        ctx.setNotificationId(n.getId());
        ctx.setUserId(n.getUserId());
        ctx.setType(n.getType());
        ctx.setTitle(n.getTitle());
        ctx.setContent(n.getContent());
        ctx.setRefId(n.getRefId());
        ctx.setConfig(cfg);

        NotificationChannel ch = channelOf(d.getChannelCode());
        String status;
        String error = null;
        LocalDateTime sentAt = null;
        if ("INAPP".equals(ch.code())) {
            status = "SENT";
            sentAt = LocalDateTime.now();
        } else {
            String to = resolveTo(ch, ctx);
            if (to == null) {
                status = "SKIPPED";
                error = "EMAIL".equals(ch.code())
                        ? "未找到收件邮箱"
                        : "企业未提供该通道的收件地址（手机号/设备令牌尚未建模）";
            } else {
                try {
                    ch.send(ctx);
                    status = "SENT";
                    sentAt = LocalDateTime.now();
                } catch (Exception e) {
                    status = "FAILED";
                    error = truncate(e.getMessage(), 512);
                }
            }
        }

        d.setAttempts((d.getAttempts() == null ? 1 : d.getAttempts()) + 1);
        d.setStatus(status);
        d.setLastError(error);
        d.setSentAt(sentAt);
        d.setUpdatedBy(actorUserId);
        d.setUpdatedAt(LocalDateTime.now());
        deliveryMapper.updateById(d);

        return result(d.getChannelCode(), status, error == null ? "重试完成" : error, sentAt);
    }

    // -------------------------------------------------------------- 内部工具

    private Set<String> enabledChannels(Long tenantId) {
        Set<String> set = new LinkedHashSet<>();
        set.add("INAPP"); // 站内信恒可用
        List<NotificationChannelConfig> rows = configMapper.selectList(new LambdaQueryWrapper<NotificationChannelConfig>()
                .eq(NotificationChannelConfig::getTenantId, tenantId)
                .eq(NotificationChannelConfig::getEnabled, 1));
        for (NotificationChannelConfig r : rows) {
            set.add(r.getChannelCode());
        }
        return set;
    }

    private Set<String> preferredChannels(Long tenantId, Long userId, String type) {
        NotificationPreference exact = selectPref(tenantId, userId, type, false);
        NotificationPreference p = exact != null ? exact : selectPref(tenantId, userId, null, true);
        if (p == null || p.getChannels() == null || p.getChannels().isBlank()) {
            return null; // 沿用租户默认（全部启用通道）
        }
        return Arrays.stream(p.getChannels().split(","))
                .map(String::trim).filter(s -> !s.isEmpty()).collect(Collectors.toSet());
    }

    private NotificationPreference selectPref(Long tenantId, Long userId, String type, boolean isNull) {
        LambdaQueryWrapper<NotificationPreference> q = new LambdaQueryWrapper<NotificationPreference>()
                .eq(NotificationPreference::getTenantId, tenantId)
                .eq(NotificationPreference::getUserId, userId);
        if (isNull) {
            q.isNull(NotificationPreference::getType);
        } else {
            q.eq(NotificationPreference::getType, type);
        }
        // limit 1：type=NULL 的默认行不受唯一键约束（MySQL 唯一键不约束 NULL）。
        // 若因并发写入产生重复默认行，无 limit 的 selectOne 会抛 TooManyResultsException，
        // 它会沿 dispatch 冒泡并在最外层被吞掉 —— 整轮分发（含 INAPP）静默中断，
        // 表现为「通知有记录但无投递」。取 1 行即可保证分发始终可用。
        q.last("limit 1");
        return preferenceMapper.selectOne(q);
    }

    private DeliveryContext buildContext(NotificationRequested event, String code) {
        DeliveryContext ctx = new DeliveryContext();
        ctx.setTenantId(event.tenantId());
        ctx.setNotificationId(event.notificationId());
        ctx.setUserId(event.userId());
        ctx.setType(event.type());
        ctx.setTitle(event.title());
        ctx.setContent(event.content());
        ctx.setRefId(event.refId());
        ctx.setConfig(channelConfig(event.tenantId(), code));
        return ctx;
    }

    private Map<String, Object> channelConfig(Long tenantId, String code) {
        NotificationChannelConfig c = configMapper.selectOne(new LambdaQueryWrapper<NotificationChannelConfig>()
                .eq(NotificationChannelConfig::getTenantId, tenantId)
                .eq(NotificationChannelConfig::getChannelCode, code));
        if (c == null || c.getConfigJson() == null) {
            return null;
        }
        return parse(c.getConfigJson());
    }

    private String resolveTo(NotificationChannel ch, DeliveryContext ctx) {
        return switch (ch.code()) {
            case "EMAIL" -> lookupEmail(ctx.getUserId());
            case "SMS", "PUSH" -> null; // 数据模型尚未建模手机号/设备令牌
            default -> null;             // INAPP 不需要地址
        };
    }

    private String lookupEmail(Long userId) {
        if (userId == null) {
            return null;
        }
        Map<String, Object> u = userMapper.selectLite(userId);
        if (u == null) {
            return null;
        }
        Object e = u.get("email");
        return e == null ? null : String.valueOf(e);
    }

    private NotificationChannel channelOf(String code) {
        return channels.stream()
                .filter(c -> c.code().equals(code))
                .findFirst()
                .orElseThrow(() -> BizException.badRequest("未知通知通道：" + code));
    }

    private void writeDelivery(Long tenantId, Long notificationId, String code, String status,
                               int attempts, String error, LocalDateTime sentAt) {
        NotificationDelivery d = new NotificationDelivery();
        d.setTenantId(tenantId);
        d.setNotificationId(notificationId);
        d.setChannelCode(code);
        d.setStatus(status);
        d.setAttempts(attempts);
        d.setLastError(error);
        d.setSentAt(sentAt);
        d.setCreatedAt(LocalDateTime.now());
        deliveryMapper.insert(d);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parse(String json) {
        try {
            Map<String, Object> m = objectMapper.readValue(json, Map.class);
            return m == null ? new LinkedHashMap<>() : m;
        } catch (Exception e) {
            log.warn("解析通道配置失败：{}", e.getMessage());
            return new LinkedHashMap<>();
        }
    }

    private static Map<String, Object> result(String code, String status, String message, LocalDateTime sentAt) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("channelCode", code);
        m.put("status", status);
        m.put("message", message);
        m.put("sentAt", sentAt == null ? null : sentAt.toString());
        return m;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() > max ? s.substring(0, max) : s;
    }
}
