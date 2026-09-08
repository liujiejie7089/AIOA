package cn.aioa.resource.service;

import cn.aioa.resource.entity.Notification;
import cn.aioa.resource.mapper.NotificationMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 站内通知服务（审批事件驱动）：
 *   · notifyUser   —— 给单个接收人写一条通知（actor = 操作人，自动跳过自通知）
 *   · notifyAdmins —— 给租户全部 ROLE_ADMIN 写通知（排除操作人自己）
 *   · listMine / unreadCount / markRead / markAllRead
 * 通知为「尽力而为」：写失败只记 warn，不影响审批主流程。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationService {

    private final NotificationMapper notificationMapper;

    public void notifyUser(Long tenantId, Long recipientId, Long actorId,
                           String type, String title, String content, Long refId) {
        if (recipientId == null || (actorId != null && actorId.equals(recipientId))) {
            return; // 无接收人或自己通知自己，跳过
        }
        try {
            Notification n = new Notification();
            n.setTenantId(tenantId == null ? 0L : tenantId);
            n.setUserId(recipientId);
            n.setType(type == null ? Notification.TYPE_APPROVAL : type);
            n.setTitle(title);
            n.setContent(content);
            n.setRefId(refId);
            n.setCreatedAt(LocalDateTime.now());
            n.setCreatedBy(actorId);
            notificationMapper.insert(n);
        } catch (Exception e) {
            log.warn("通知写入失败（不影响主流程）recipient={} title={}", recipientId, title, e);
        }
    }

    public void notifyAdmins(Long tenantId, Long actorId, String title, String content, Long refId) {
        Long tid = tenantId == null ? 0L : tenantId;
        List<Long> adminIds;
        try {
            adminIds = notificationMapper.selectTenantAdminIds(tid);
        } catch (Exception e) {
            log.warn("查询租户管理员失败（跳过通知）tenant={}", tid, e);
            return;
        }
        for (Long adminId : adminIds) {
            notifyUser(tid, adminId, actorId, Notification.TYPE_APPROVAL, title, content, refId);
        }
    }

    public List<Notification> listMine(Long tenantId, Long userId, int limit) {
        return notificationMapper.selectList(new LambdaQueryWrapper<Notification>()
                .eq(Notification::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(Notification::getUserId, userId == null ? 0L : userId)
                .orderByDesc(Notification::getCreatedAt)
                .last("LIMIT " + Math.max(1, Math.min(limit, 50))));
    }

    public long unreadCount(Long tenantId, Long userId) {
        return notificationMapper.selectCount(new LambdaQueryWrapper<Notification>()
                .eq(Notification::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(Notification::getUserId, userId == null ? 0L : userId)
                .isNull(Notification::getReadAt));
    }

    public boolean markRead(Long tenantId, Long userId, Long id) {
        return notificationMapper.update(null, new LambdaUpdateWrapper<Notification>()
                .eq(Notification::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(Notification::getUserId, userId == null ? 0L : userId)
                .eq(Notification::getId, id)
                .isNull(Notification::getReadAt)
                .set(Notification::getReadAt, LocalDateTime.now())
                .set(Notification::getUpdatedAt, LocalDateTime.now())) > 0;
    }

    public int markAllRead(Long tenantId, Long userId) {
        return notificationMapper.update(null, new LambdaUpdateWrapper<Notification>()
                .eq(Notification::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(Notification::getUserId, userId == null ? 0L : userId)
                .isNull(Notification::getReadAt)
                .set(Notification::getReadAt, LocalDateTime.now())
                .set(Notification::getUpdatedAt, LocalDateTime.now()));
    }
}
