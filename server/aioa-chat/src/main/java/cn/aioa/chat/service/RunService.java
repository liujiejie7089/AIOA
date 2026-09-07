package cn.aioa.chat.service;

import cn.aioa.chat.config.AgentProperties;
import cn.aioa.chat.dto.AgentRunRequest;
import cn.aioa.chat.dto.AgentUserContext;
import cn.aioa.chat.entity.AgentRun;
import cn.aioa.chat.entity.ChatConversation;
import cn.aioa.chat.entity.ChatMessage;
import cn.aioa.chat.mapper.AgentRunMapper;
import cn.aioa.chat.mapper.ChatConversationMapper;
import cn.aioa.chat.mapper.ChatMessageMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.trace.TraceId;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.ServiceTokenProvider;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.time.Duration;
import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Random;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Agent 运行：发起 run（落 user 消息 + agent_run），并把 Python 的 SSE 帧逐帧转发给前端。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RunService {

    private static final DateTimeFormatter RUN_ID_TS = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");
    private static final String EVENT_MESSAGE_DELTA = "message.delta";
    private static final String EVENT_MESSAGE_COMPLETED = "message.completed";
    private static final String EVENT_ERROR = "error";
    private static final String EVENT_PING = "ping";
    private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_TYPE =
            new ParameterizedTypeReference<>() {
            };

    private final ChatConversationMapper conversationMapper;
    private final ChatMessageMapper messageMapper;
    private final AgentRunMapper agentRunMapper;
    private final WebClient agentWebClient;
    private final ServiceTokenProvider serviceTokenProvider;
    private final ObjectMapper objectMapper;
    private final ScheduledExecutorService sseHeartbeatExecutor;
    private final AgentProperties agentProperties;

    /**
     * 发起一轮对话：落 user 消息 + 创建 agent_run（RUNNING），返回 runId。
     */
    public String start(Long conversationId, String text, Map<String, Object> context, List<Long> attachments) {
        AuthUser user = AuthUserContext.require();
        if (text == null || text.isBlank()) {
            throw BizException.badRequest("text 不能为空");
        }
        ChatConversation conversation = conversationMapper.selectById(conversationId);
        if (conversation == null) {
            throw BizException.notFound("会话不存在");
        }
        if (!Objects.equals(conversation.getUserId(), user.getUserId())) {
            throw BizException.forbidden("无权访问该会话");
        }

        String runId = newRunId();
        long seq = nextSeq(conversationId);

        ChatMessage userMessage = new ChatMessage();
        userMessage.setTenantId(user.getTenantId() == null ? 0L : user.getTenantId());
        userMessage.setConversationId(conversationId);
        userMessage.setRunId(runId);
        userMessage.setRole(ChatMessage.ROLE_USER);
        userMessage.setContent(text);
        userMessage.setContentType("text");
        userMessage.setContextSnapshot(context);
        userMessage.setStatus(ChatMessage.STATUS_OK);
        userMessage.setSeq(seq);
        userMessage.setCreatedAt(LocalDateTime.now());
        userMessage.setCreatedBy(user.getUserId());
        messageMapper.insert(userMessage);

        AgentRun run = new AgentRun();
        run.setTenantId(user.getTenantId() == null ? 0L : user.getTenantId());
        run.setRunId(runId);
        run.setConversationId(conversationId);
        run.setUserId(user.getUserId());
        run.setStatus(AgentRun.STATUS_RUNNING);
        run.setCurrentStep(0);
        run.setTokensIn(0);
        run.setTokensOut(0);
        run.setStartedAt(LocalDateTime.now());
        run.setCreatedAt(LocalDateTime.now());
        run.setCreatedBy(user.getUserId());
        agentRunMapper.insert(run);

        conversationMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ChatConversation>()
                .eq(ChatConversation::getId, conversationId)
                .setSql("msg_count = COALESCE(msg_count, 0) + 1")
                .set(ChatConversation::getLastMsgAt, LocalDateTime.now()));

        return runId;
    }

    /**
     * 订阅 run 事件流：WebClient 调 Python，逐帧转发；流结束落 assistant 消息并置 SUCCEEDED。
     */
    public SseEmitter subscribe(String runId, String lastEventId) {
        AuthUser user = AuthUserContext.require();
        AgentRun run = findRun(runId);
        if (!Objects.equals(run.getUserId(), user.getUserId())) {
            throw BizException.forbidden("无权访问该运行");
        }
        ChatMessage userMessage = messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getRunId, runId)
                .eq(ChatMessage::getRole, ChatMessage.ROLE_USER)
                .orderByAsc(ChatMessage::getId)
                .last("limit 1"));
        String text = userMessage == null ? "" : userMessage.getContent();
        Map<String, Object> context = userMessage == null ? null : userMessage.getContextSnapshot();

        SseEmitter emitter = new SseEmitter(0L);
        StringBuilder assistant = new StringBuilder();
        AtomicReference<String> lastId = new AtomicReference<>(lastEventId);
        long heartbeatSeconds = Math.max(1, agentProperties.getHeartbeatSeconds());

        ScheduledFuture<?> heartbeat = sseHeartbeatExecutor.scheduleAtFixedRate(
                () -> safeSend(emitter, EVENT_PING, lastId.get(), "{}"),
                heartbeatSeconds, heartbeatSeconds, TimeUnit.SECONDS);
        Disposable[] subscription = new Disposable[1];
        Runnable cleanup = () -> {
            heartbeat.cancel(true);
            if (subscription[0] != null) {
                subscription[0].dispose();
            }
        };
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(thrown -> cleanup.run());

        AgentRunRequest request = buildRequest(run, user, text, context);
        try {
            subscription[0] = agentWebClient.post()
                    .uri("/internal/v1/runs")
                    .accept(MediaType.TEXT_EVENT_STREAM)
                    .contentType(MediaType.APPLICATION_JSON)
                    .header(HttpHeaders.AUTHORIZATION,
                            "Bearer " + serviceTokenProvider.generate(ServiceTokenProvider.SVC_SERVER))
                    .bodyValue(request)
                    .retrieve()
                    .bodyToFlux(SSE_TYPE)
                    .subscribe(
                            event -> forward(emitter, event, assistant, lastId),
                            error -> {
                                log.warn("agent run {} failed: {}", runId, error.getMessage());
                                markFailed(run, error.getMessage());
                                safeSend(emitter, EVENT_ERROR, lastId.get(), errorJson(error));
                                cleanup.run();
                                emitter.completeWithError(error);
                            },
                            () -> {
                                try {
                                    finish(run, assistant.toString());
                                } catch (Exception e) {
                                    log.error("finish run {} failed", runId, e);
                                }
                                cleanup.run();
                                emitter.complete();
                            });
        } catch (Exception e) {
            log.error("subscribe agent run {} failed", runId, e);
            markFailed(run, e.getMessage());
            safeSend(emitter, EVENT_ERROR, lastId.get(), errorJson(e));
            cleanup.run();
            emitter.completeWithError(e);
        }
        return emitter;
    }

    /**
     * 中断运行（M1 简化：仅置 CANCELLED；真实中断 M2 实现）。
     */
    public void cancel(String runId) {
        AuthUser user = AuthUserContext.require();
        AgentRun run = findRun(runId);
        if (!Objects.equals(run.getUserId(), user.getUserId())) {
            throw BizException.forbidden("无权访问该运行");
        }
        AgentRun patch = new AgentRun();
        patch.setId(run.getId());
        patch.setStatus(AgentRun.STATUS_CANCELLED);
        patch.setEndedAt(LocalDateTime.now());
        patch.setDurationMs(elapsedMillis(run.getStartedAt()));
        agentRunMapper.updateById(patch);
    }

    public AgentRun findRun(String runId) {
        AgentRun run = agentRunMapper.selectOne(new LambdaQueryWrapper<AgentRun>()
                .eq(AgentRun::getRunId, runId));
        if (run == null) {
            throw BizException.notFound("运行不存在：" + runId);
        }
        return run;
    }

    private AgentRunRequest buildRequest(AgentRun run, AuthUser user, String text, Map<String, Object> context) {
        AgentUserContext userContext = new AgentUserContext();
        userContext.setUserId(user.getUserId());
        userContext.setTenantId(user.getTenantId() == null ? 0L : user.getTenantId());
        userContext.setUsername(user.getUsername());
        userContext.setRoles(user.getRoles() == null ? List.of() : user.getRoles());
        userContext.setTraceId(TraceId.get());

        AgentRunRequest request = new AgentRunRequest();
        request.setRunId(run.getRunId());
        request.setConversationId(run.getConversationId());
        request.setText(text);
        request.setContext(context);
        request.setUserContext(userContext);
        return request;
    }

    private void forward(SseEmitter emitter,
                         ServerSentEvent<String> event,
                         StringBuilder assistant,
                         AtomicReference<String> lastId) {
        String name = event.event() == null ? "message" : event.event();
        String data = event.data() == null ? "" : event.data();
        if (event.id() != null) {
            lastId.set(event.id());
        }
        try {
            emitter.send(SseEmitter.event().id(event.id()).name(name).data(data));
        } catch (IOException e) {
            log.debug("forward sse frame failed: {}", e.getMessage());
            return;
        }
        if (EVENT_MESSAGE_DELTA.equals(name)) {
            String piece = readField(data, "text");
            if (piece != null) {
                assistant.append(piece);
            }
        } else if (EVENT_MESSAGE_COMPLETED.equals(name)) {
            String content = readField(data, "content");
            if (content != null) {
                assistant.setLength(0);
                assistant.append(content);
            }
        }
    }

    private void finish(AgentRun run, String content) {
        LocalDateTime endedAt = LocalDateTime.now();
        if (content != null && !content.isBlank()) {
            ChatMessage message = new ChatMessage();
            message.setTenantId(run.getTenantId());
            message.setConversationId(run.getConversationId());
            message.setRunId(run.getRunId());
            message.setRole(ChatMessage.ROLE_ASSISTANT);
            message.setContent(content);
            message.setContentType("text");
            message.setStatus(ChatMessage.STATUS_OK);
            message.setSeq(nextSeq(run.getConversationId()));
            message.setCreatedAt(endedAt);
            message.setCreatedBy(run.getUserId());
            messageMapper.insert(message);
            conversationMapper.update(null,
                    new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ChatConversation>()
                            .eq(ChatConversation::getId, run.getConversationId())
                            .setSql("msg_count = COALESCE(msg_count, 0) + 1")
                            .set(ChatConversation::getLastMsgAt, endedAt));
        }
        AgentRun patch = new AgentRun();
        patch.setId(run.getId());
        patch.setStatus(AgentRun.STATUS_SUCCEEDED);
        patch.setEndedAt(endedAt);
        patch.setDurationMs(elapsedMillis(run.getStartedAt()));
        agentRunMapper.updateById(patch);
    }

    private void markFailed(AgentRun run, String message) {
        AgentRun patch = new AgentRun();
        patch.setId(run.getId());
        patch.setStatus(AgentRun.STATUS_FAILED);
        patch.setError(message == null ? "unknown" : (message.length() > 500 ? message.substring(0, 500) : message));
        patch.setEndedAt(LocalDateTime.now());
        patch.setDurationMs(elapsedMillis(run.getStartedAt()));
        agentRunMapper.updateById(patch);
    }

    private long nextSeq(Long conversationId) {
        ChatMessage last = messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getConversationId, conversationId)
                .orderByDesc(ChatMessage::getSeq)
                .last("limit 1"));
        return last == null || last.getSeq() == null ? 1L : last.getSeq() + 1;
    }

    private long elapsedMillis(LocalDateTime startedAt) {
        if (startedAt == null) {
            return 0L;
        }
        return Duration.between(startedAt, LocalDateTime.now()).toMillis();
    }

    private void safeSend(SseEmitter emitter, String name, String id, String data) {
        try {
            emitter.send(SseEmitter.event().id(id).name(name).data(data));
        } catch (Exception e) {
            log.debug("send sse event {} failed: {}", name, e.getMessage());
        }
    }

    private String errorJson(Throwable error) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "code", "AGENT_STREAM_ERROR",
                    "message", String.valueOf(error.getMessage()),
                    "retryable", true));
        } catch (Exception e) {
            return "{\"code\":\"AGENT_STREAM_ERROR\",\"message\":\"agent stream error\",\"retryable\":true}";
        }
    }

    private String readField(String data, String field) {
        if (data == null || data.isBlank()) {
            return null;
        }
        try {
            Map<?, ?> map = objectMapper.readValue(data, Map.class);
            Object value = map.get(field);
            return value == null ? null : String.valueOf(value);
        } catch (Exception e) {
            log.debug("unable to parse sse data as json: {}", data);
            return null;
        }
    }

    private static String newRunId() {
        String random = String.format("%06d", new Random().nextInt(1_000_000));
        return "run_" + LocalDateTime.now().format(RUN_ID_TS) + "_" + random;
    }
}
