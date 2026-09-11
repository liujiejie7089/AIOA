package cn.aioa.chat.service;

import cn.aioa.chat.entity.ChatConversation;
import cn.aioa.chat.entity.ChatMessage;
import cn.aioa.chat.mapper.ChatConversationMapper;
import cn.aioa.chat.mapper.ChatMessageMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.PageResult;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * 会话：创建 / 分页 / 详情 / 逻辑删除 / 消息游标分页。
 */
@Service
@RequiredArgsConstructor
public class ConversationService {

    private final ChatConversationMapper conversationMapper;
    private final ChatMessageMapper messageMapper;
    private final AgentWorkerMapper workerMapper;

    public ChatConversation create(String title, String appCode, Long workerId) {
        Long userId = AuthUserContext.requireUserId();
        ChatConversation conversation = new ChatConversation();
        conversation.setTenantId(AuthUserContext.tenantIdOrDefault());
        conversation.setUserId(userId);
        conversation.setTitle(StringUtils.hasText(title) ? title : "新会话");
        conversation.setAppCode(appCode);
        conversation.setAgentCode("main");
        conversation.setStatus(ChatConversation.STATUS_ACTIVE);
        conversation.setContextTurns(10);
        conversation.setMsgCount(0L);
        conversation.setCreatedAt(LocalDateTime.now());
        conversation.setCreatedBy(userId);
        if (workerId != null) {
            bindWorker(conversation, AuthUserContext.require(), workerId);
        }
        conversationMapper.insert(conversation);
        return conversation;
    }

    /**
     * 会话绑定数字员工：**同租户 + 未停用**即可绑定（V22）。
     *
     * <p>准入口径的变更理由：数字员工的**管理**操作（创建/修改/启停/立即执行/删除）已收敛为
     * 仅租户管理员；而**使用**数字员工（例如向请假数字人提交请假申请）本属所有成员的业务需求，
     * 不应再受权限码限制。因此这里只校验租户归属与启用状态，回答边界由
     * {@code RunService.buildScope} 下发的职责范围（scope）约束。</p>
     *
     * <p>即：**能否用** = 同租户且在启用中；**能做什么** = 该员工的职责范围（越界拒答）；
     * **能否改** = 仅租户管理员（见 WorkerController#requireAdmin）。</p>
     */
    private void bindWorker(ChatConversation conversation, AuthUser user, Long workerId) {
        AgentWorker worker = workerMapper.selectById(workerId);
        if (worker == null || !Objects.equals(worker.getTenantId(), user.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + workerId);
        }
        if (Integer.valueOf(0).equals(worker.getEnabled())) {
            throw BizException.badRequest("该数字员工已停用，无法建立会话");
        }
        conversation.setWorkerId(worker.getId());
        conversation.setAgentCode("worker:" + worker.getId());
    }

    public PageResult<ChatConversation> page(long page, long size, String keyword) {
        long p = Math.max(1, page);
        long s = Math.min(Math.max(1, size), 100);
        long total = conversationMapper.selectCount(ownedWrapper(keyword));
        LambdaQueryWrapper<ChatConversation> wrapper = ownedWrapper(keyword);
        wrapper.orderByDesc(ChatConversation::getLastMsgAt)
                .orderByDesc(ChatConversation::getId)
                .last("limit " + s + " offset " + ((p - 1) * s));
        List<ChatConversation> list = conversationMapper.selectList(wrapper);
        return PageResult.of(list, total == 0 ? 0 : total, p, s);
    }

    public ChatConversation getOwned(Long conversationId) {
        ChatConversation conversation = conversationMapper.selectById(conversationId);
        if (conversation == null) {
            throw BizException.notFound("会话不存在");
        }
        if (!Objects.equals(conversation.getUserId(), AuthUserContext.requireUserId())) {
            throw BizException.forbidden("无权访问该会话");
        }
        return conversation;
    }

    public void delete(Long conversationId) {
        getOwned(conversationId);
        conversationMapper.update(null, new LambdaUpdateWrapper<ChatConversation>()
                .eq(ChatConversation::getId, conversationId)
                .setSql("deleted_at = now()"));
    }

    /** FR-D3 会话重命名（仅本人，标题非空，长度上限 60）。 */
    public void rename(Long conversationId, String title) {
        getOwned(conversationId);
        if (title == null || title.isBlank()) {
            throw BizException.badRequest("会话标题不能为空");
        }
        String trimmed = title.trim();
        if (trimmed.length() > 60) {
            trimmed = trimmed.substring(0, 60);
        }
        conversationMapper.update(null, new LambdaUpdateWrapper<ChatConversation>()
                .eq(ChatConversation::getId, conversationId)
                .set(ChatConversation::getTitle, trimmed));
    }

    /**
     * 消息游标分页：beforeSeq 向前翻，返回按 seq 升序。
     */
    public List<ChatMessage> messages(Long conversationId, Long beforeSeq, Integer size) {
        getOwned(conversationId);
        long cursor = beforeSeq == null || beforeSeq <= 0 ? Long.MAX_VALUE : beforeSeq;
        int limit = Math.min(Math.max(size == null ? 30 : size, 1), 200);
        List<ChatMessage> list = messageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getConversationId, conversationId)
                .lt(ChatMessage::getSeq, cursor)
                .orderByDesc(ChatMessage::getSeq)
                .last("limit " + limit));
        Collections.reverse(list);
        return list;
    }

    public long nextSeq(Long conversationId) {
        ChatMessage last = messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getConversationId, conversationId)
                .orderByDesc(ChatMessage::getSeq)
                .last("limit 1"));
        return last == null || last.getSeq() == null ? 1L : last.getSeq() + 1;
    }

    public void touchConversation(Long conversationId, long delta) {
        ChatConversation conversation = conversationMapper.selectById(conversationId);
        if (conversation == null) {
            return;
        }
        ChatConversation patch = new ChatConversation();
        patch.setId(conversationId);
        patch.setMsgCount((conversation.getMsgCount() == null ? 0L : conversation.getMsgCount()) + delta);
        patch.setLastMsgAt(LocalDateTime.now());
        conversationMapper.updateById(patch);
    }

    private LambdaQueryWrapper<ChatConversation> ownedWrapper(String keyword) {
        LambdaQueryWrapper<ChatConversation> wrapper = new LambdaQueryWrapper<ChatConversation>()
                .eq(ChatConversation::getUserId, AuthUserContext.requireUserId());
        if (StringUtils.hasText(keyword)) {
            wrapper.like(ChatConversation::getTitle, keyword);
        }
        return wrapper;
    }
}
