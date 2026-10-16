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
import cn.aioa.project.port.PmAiScopePort;
import cn.aioa.resource.controller.KbController;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.SysFile;
import cn.aioa.resource.entity.TokenLedger;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.SysFileMapper;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.resource.service.BillingService;
import cn.aioa.resource.service.KbFileParser;
import cn.aioa.resource.support.WorkerRole;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.ServiceTokenProvider;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
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
    private static final String EVENT_RUN_COMPLETED = "run.completed";
    private static final String EVENT_RUN_FAILED = "run.failed";
    private static final String EVENT_ERROR = "error";
    private static final String EVENT_PING = "ping";
    /** Agent 在 ask_user 暂停时补发的澄清事件（SSE 末帧，之后本轮流正常结束）。 */
    private static final String EVENT_NEED_CLARIFICATION = "need_clarification";
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
    private final BillingService billingService;
    private final ActivityLogService activityLogService;
    private final ContentGuardService contentGuard;
    private final AgentWorkerMapper workerMapper;
    /** 项目域只读窄接口：项目会话下发该项目的生效上下文（跨模块单向依赖 chat → project）。 */
    private final PmAiScopePort pmAiScopePort;

    /** 通用上传文件元数据（按 id 查存储名）。 */
    private final SysFileMapper fileMapper;

    /** 纯解析、零持久化（与知识库共用，但不进知识库）。 */
    private final KbFileParser kbFileParser;

    /** 上传落盘根目录：与 FileController 同源（aioa.upload.dir，默认 ./uploads），读取字节时复用同一路径规则。 */
    @Value("${aioa.upload.dir:./uploads}")
    private String uploadDir;

    /** 传给 Agent 的最大历史轮数（FR-C2 多轮会话）。 */
    private static final int HISTORY_TURNS = 10;

    /** 单份多任务计划的子任务上限（与 agent 侧 MAX_SUBTASKS 对齐，Java 侧先拦一次，快速失败）。 */
    private static final int MAX_PLAN_TASKS = 50;

    /**
     * 发起一轮对话：额度准入（FR-B2）→ 输入内容审核（FR-H3）→ 落 user 消息 +
     * 创建 agent_run（RUNNING），返回 runId。
     */
    public String start(Long conversationId, String text, Map<String, Object> context,
                        List<Long> attachments, String modelRef, Boolean kbOn) {
        AuthUser user = AuthUserContext.require();
        if (text == null || text.isBlank()) {
            throw BizException.badRequest("text 不能为空");
        }
        // FR-B2 额度准入前置：余额耗尽则拒绝发起（前端引导购买/次日再试）
        BillingService.QuotaView quota = billingService.current(
                user.getTenantId() == null ? 0L : user.getTenantId(), user.getUserId());
        if (quota.exhausted()) {
            throw BizException.forbidden("今日免费额度已用完，请购买词元套餐或明日再试");
        }
        // FR-H3 输入侧内容审核：命中即中止
        String inputHit = contentGuard.findHit(text);
        if (inputHit != null) {
            throw BizException.forbidden(contentGuard.inputBlockMessage(inputHit));
        }
        ChatConversation conversation = conversationMapper.selectById(conversationId);
        if (conversation == null) {
            throw BizException.notFound("会话不存在");
        }
        if (!Objects.equals(conversation.getUserId(), user.getUserId())) {
            throw BizException.forbidden("无权访问该会话");
        }
        // FR-C4 模型切换：run 级 modelRef 写回会话，subscribe 时透传给 Agent
        if (modelRef != null && !modelRef.isBlank() && !modelRef.equals(conversation.getModelRef())) {
            conversationMapper.update(null,
                    new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ChatConversation>()
                            .eq(ChatConversation::getId, conversationId)
                            .set(ChatConversation::getModelRef, modelRef));
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
        // 对话级知识库开关 kb_on：顶层优先于 context.kb_on（历史写法）；
        // 解析结果保持 null 原样（不补默认值，Agent 侧缺省当「开」）。
        // 合并进 context 快照，使后续独立的 subscribe 请求能回读该值。
        if (kbOn == null && context != null) {
            Object raw = context.get("kb_on");
            if (raw instanceof Boolean b) {
                kbOn = b;
            }
        }
        if (kbOn != null) {
            if (context == null) {
                context = new java.util.LinkedHashMap<>();
            }
            context.put("kb_on", kbOn);
        }

        userMessage.setContextSnapshot(context);
        userMessage.setStatus(ChatMessage.STATUS_OK);
        userMessage.setSeq(seq);
        userMessage.setCreatedAt(LocalDateTime.now());
        userMessage.setCreatedBy(user.getUserId());
        // 对话内上传文档（不进知识库）：解析为参考快照，与本轮 user 消息同一次 insert 落库。
        userMessage.setAttachments(toObjectList(resolveAttachments(attachments)));
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

        activityLogService.record(run.getTenantId(), user.getUserId(),
                "发起会话（" + displayTitle(conversation) + "）", "ok", "成功");

        return runId;
    }

    /**
     * 订阅 run 事件流：WebClient 调 Python，逐帧转发；流结束落 assistant 消息并置 SUCCEEDED。
     * authorization 为发起方用户 token，透传给 agent 供工具回调（工具权限 = 用户权限）。
     */
    public SseEmitter subscribe(String runId, String lastEventId, String authorization) {
        AuthUser user = AuthUserContext.require();
        AgentRun run = findRun(runId);
        if (!Objects.equals(run.getUserId(), user.getUserId())) {
            throw BizException.forbidden("无权访问该运行");
        }
        // 挂起态（HITL 等待澄清）：**绝不**再打 /internal/v1/runs —— 同一 thread_id 会覆盖
        // agent 侧断点，使已完成的工具调用面临重跑风险（HITL 验收判据 Q3）。
        // 澄清只能由 /api/v1/runs/{runId}/resume 回填，重复订阅必须被拦截。
        if (AgentRun.STATUS_WAITING_INPUT.equals(run.getStatus())) {
            return waitingInputNotice(run, lastEventId);
        }
        // 幂等恢复：run 已终结时直接回放缓存帧，不再次触发 Agent 推理，
        // 避免刷新/重进会话后重复回答、重复落库与重复计费
        if (AgentRun.STATUS_SUCCEEDED.equals(run.getStatus())
                || AgentRun.STATUS_FAILED.equals(run.getStatus())
                || AgentRun.STATUS_CANCELLED.equals(run.getStatus())) {
            return replay(run, lastEventId);
        }
        ChatMessage userMessage = messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getRunId, runId)
                .eq(ChatMessage::getRole, ChatMessage.ROLE_USER)
                .orderByAsc(ChatMessage::getId)
                .last("limit 1"));
        String text = userMessage == null ? "" : userMessage.getContent();
        Map<String, Object> context = userMessage == null ? null : userMessage.getContextSnapshot();

        AgentRunRequest request = buildRequest(run, user, text, context);
        request.setUserToken(stripBearer(authorization));
        request.setHistory(loadHistory(run.getConversationId(), userMessage));
        // 本轮上传文档：把已落库的参考正文结构化下发 Agent（不进 content，结构体现在 attachment_docs）。
        List<Map<String, Object>> attachmentDocs = toMapList(userMessage == null ? null : userMessage.getAttachments());
        if (attachmentDocs != null && !attachmentDocs.isEmpty()) {
            request.setAttachmentDocs(attachmentDocs);
        }
        // 会话级模型路由：Agent 按 model_ref 选择 provider（默认走 MODEL_DEFAULT）
        ChatConversation conversation = conversationMapper.selectById(run.getConversationId());
        if (conversation != null && conversation.getModelRef() != null && !conversation.getModelRef().isBlank()) {
            request.setModelRef(conversation.getModelRef());
        }
        // V21 会话绑定数字员工：下发职责范围，Agent 侧据此限定回答边界（越界拒答）
        // V79 项目会话：scope 里并入该项目的生效上下文（项目隔离的「下行」一半；
        //              准入的「上行」硬校验已在 ConversationService.bindWorker 完成）
        if (conversation != null && conversation.getWorkerId() != null) {
            request.setScope(buildScope(conversation.getWorkerId(),
                    conversation.getProjectId(), conversation.getTenantId()));
        }
        // 项目维度与「是否绑定数字员工」解耦：未绑数字人的项目会话同样要告诉 agent 当前项目，
        // 否则 agent 会反问「上传到哪个系统或平台」（实测缺陷）。项目名以库为准，不由前端传入。
        if (conversation != null && conversation.getProjectId() != null && conversation.getProjectId() > 0L) {
            Map<String, Object> brief = pmAiScopePort.projectBrief(conversation.getTenantId(), conversation.getProjectId());
            if (brief != null) {
                request.setProject(brief);
            }
        }
        return proxyAgentRun("/internal/v1/runs", request, run, lastEventId);
    }

    /**
     * 代理一次 agent SSE 流：创建 emitter、起心跳、逐帧转发，流末按既定口径收口
     * （落 assistant 消息 / 计 usage / 记 citations / 故障原因）。
     *
     * subscribe（首发）与 resume（HITL 续跑）共用本方法，确保「续跑后回答的落库口径」
     * 与「首发」逐字一致——否则 resume 后的回答会不一致。唯一差异是「发起哪条 agent 端点」：
     *   · 首发：uri = {@code /internal/v1/runs}，body = 完整 {@link AgentRunRequest}；
     *   · 续跑：uri = {@code /internal/v1/runs/{runId}/resume}，body = {@code {answer}}。
     *
     * clarificationRef 用于识别 ask_user 暂停帧：流末若收到 need_clarification，则本轮
     * 不终结（挂起等待 /resume），天然覆盖多轮澄清。
     */
    private SseEmitter proxyAgentRun(String uri, Object requestBody, AgentRun run, String lastEventId) {
        SseEmitter emitter = new SseEmitter(0L);
        StringBuilder assistant = new StringBuilder();
        AtomicReference<Usage> usageRef = new AtomicReference<>(Usage.ZERO);
        AtomicReference<String> lastId = new AtomicReference<>(lastEventId);
        AtomicReference<List<Object>> citationsRef = new AtomicReference<>(List.of());
        AtomicReference<List<Object>> toolCallsRef = new AtomicReference<>(List.of());
        AtomicReference<String> failureRef = new AtomicReference<>(null);
        AtomicReference<String> clarificationRef = new AtomicReference<>(null);
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
        try {
            subscription[0] = agentWebClient.post()
                    .uri(uri)
                    .accept(MediaType.TEXT_EVENT_STREAM)
                    .contentType(MediaType.APPLICATION_JSON)
                    .header(HttpHeaders.AUTHORIZATION,
                            "Bearer " + serviceTokenProvider.generate(ServiceTokenProvider.SVC_SERVER))
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToFlux(SSE_TYPE)
                    .subscribe(
                            event -> forward(emitter, event, assistant, lastId, usageRef,
                                    citationsRef, toolCallsRef, failureRef, clarificationRef),
                            error -> {
                                log.warn("agent run {} failed: {}", run.getRunId(), error.getMessage());
                                markFailed(run, error.getMessage());
                                safeSend(emitter, EVENT_ERROR, lastId.get(), errorJson(error));
                                cleanup.run();
                                emitter.completeWithError(error);
                            },
                            () -> {
                                try {
                                    completeRun(run, emitter, lastId, assistant, usageRef,
                                            citationsRef, toolCallsRef, failureRef, clarificationRef);
                                } catch (Exception e) {
                                    log.error("finish run {} failed", run.getRunId(), e);
                                }
                                cleanup.run();
                                emitter.complete();
                            });
        } catch (Exception e) {
            log.error("subscribe agent run {} failed", run.getRunId(), e);
            markFailed(run, e.getMessage());
            safeSend(emitter, EVENT_ERROR, lastId.get(), errorJson(e));
            cleanup.run();
            emitter.completeWithError(e);
        }
        return emitter;
    }

    /**
     * 挂起态重复订阅的拦截提示：报告型（恒不抛），发一条 error 帧说明后用
     * code=WAITING_INPUT 收口。绝不再打 /internal/v1/runs，避免覆盖 agent 侧断点导致
     * 已完成工具调用被重跑（HITL 验收判据 Q3）。
     */
    private SseEmitter waitingInputNotice(AgentRun run, String lastEventId) {
        SseEmitter emitter = new SseEmitter(0L);
        String json;
        try {
            json = objectMapper.writeValueAsString(Map.of(
                    "code", "WAITING_INPUT",
                    "message", "该运行正在等待你的选择（澄清），请回填澄清卡；重复订阅不会重跑本轮。",
                    "retryable", false));
        } catch (Exception e) {
            json = "{\"code\":\"WAITING_INPUT\",\"message\":\"该运行正在等待你的选择（澄清），请回填澄清卡；重复订阅不会重跑本轮。\",\"retryable\":false}";
        }
        safeSend(emitter, EVENT_ERROR, lastEventId, json);
        emitter.complete();
        return emitter;
    }

    /**
     * HITL 澄清回填：把澄清卡选择送回 agent，从断点续跑（SSE 事件流）。
     * 续跑用的是**已存在**的 run（不新建、不落 user 消息），因此 completeRun/finish 会在
     * 同一 conversation 上追加 assistant 消息——这是期望行为。
     *
     * 续跑流若**又**收到 need_clarification（多轮澄清），clarificationRef 机制会再次置
     * WAITING_INPUT，天然覆盖。
     */
    public SseEmitter resume(String runId, Map<String, Object> body, String lastEventId, String authorization) {
        AuthUser user = AuthUserContext.require();
        AgentRun run = findRun(runId);
        if (!Objects.equals(run.getUserId(), user.getUserId())) {
            throw BizException.forbidden("无权访问该运行");
        }
        if (!AgentRun.STATUS_WAITING_INPUT.equals(run.getStatus())) {
            throw BizException.badRequest("该运行当前不是等待澄清状态（" + run.getStatus() + "）");
        }
        // answer 可以为 null（用户放弃澄清），由 agent 侧自行处理；不要在这里拦。
        Object answer = body == null ? null
                : (body.containsKey("answer") ? body.get("answer") : body.get("decision"));
        Map<String, Object> resumeBody = new java.util.LinkedHashMap<>();
        resumeBody.put("answer", answer);
        return proxyAgentRun("/internal/v1/runs/" + run.getRunId() + "/resume", resumeBody, run, lastEventId);
    }

    /**
     * 多任务协同：把一份显式计划（子任务 + 依赖）交给 Agent 编排器执行，逐帧转发事件流。
     *
     * 与 {@link #subscribe} 的区别：subscribe 是一次「对话 run」（模型逐步决定调什么工具，
     * 落 agent_run / 计费 / 内容审核）；本方法是**计划执行**——步骤与依赖由调用方给定，
     * 不进会话、不消耗词元（没有模型推理），因此不落 agent_run、不做额度准入。
     *
     * 身份与权限：透传发起方用户 token，Agent 侧以该用户身份调业务工具网关，
     * 工具权限 = 用户权限（Agent 侧不做二次授权）。
     */
    public SseEmitter runTasks(Map<String, Object> body, String authorization) {
        AuthUser user = AuthUserContext.require();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> tasks = body == null ? null : (List<Map<String, Object>>) body.get("tasks");
        if (tasks == null || tasks.isEmpty()) {
            throw BizException.badRequest("tasks 不能为空");
        }
        if (tasks.size() > MAX_PLAN_TASKS) {
            throw BizException.badRequest("子任务过多：" + tasks.size() + " > " + MAX_PLAN_TASKS);
        }

        // run_id 由调用方给定则沿用：SSE 断线重连时浏览器会用同一份 body 重发，
        // Agent 侧据此命中回放缓存，避免把整份计划（可能有副作用）再执行一遍。
        Object givenRunId = body.get("runId");
        String runId = givenRunId instanceof String s && !s.isBlank() ? s : newRunId();
        Map<String, Object> request = new java.util.LinkedHashMap<>();
        request.put("run_id", runId);
        request.put("conversation_id", body.get("conversationId"));
        // 无 Authorization 时不下发 token：Agent 侧会以「缺少用户凭证」拒绝全部任务，
        // 而不是匿名调用业务工具（工具权限 = 用户权限）。
        request.put("user_token", authorization == null ? null : stripBearer(authorization));
        Map<String, Object> userContext = new java.util.LinkedHashMap<>();
        userContext.put("user_id", user.getUserId());
        userContext.put("tenant_id", user.getTenantId() == null ? 0L : user.getTenantId());
        userContext.put("username", user.getUsername());
        userContext.put("roles", user.getRoles() == null ? List.of() : user.getRoles());
        userContext.put("trace_id", TraceId.get());
        request.put("user_context", userContext);
        request.put("tasks", tasks);
        if (body.get("maxConcurrency") != null) {
            request.put("max_concurrency", body.get("maxConcurrency"));
        }

        SseEmitter emitter = new SseEmitter(0L);
        AtomicReference<String> lastId = new AtomicReference<>(null);
        Disposable[] subscription = new Disposable[1];
        Runnable cleanup = () -> {
            if (subscription[0] != null) {
                subscription[0].dispose();
            }
        };
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(thrown -> cleanup.run());
        try {
            subscription[0] = agentWebClient.post()
                    .uri("/internal/v1/tasks")
                    .accept(MediaType.TEXT_EVENT_STREAM)
                    .contentType(MediaType.APPLICATION_JSON)
                    .header(HttpHeaders.AUTHORIZATION,
                            "Bearer " + serviceTokenProvider.generate(ServiceTokenProvider.SVC_SERVER))
                    .bodyValue(request)
                    .retrieve()
                    .bodyToFlux(SSE_TYPE)
                    .subscribe(
                            event -> {
                                String name = event.event() == null ? "message" : event.event();
                                if (event.id() != null) {
                                    lastId.set(event.id());
                                }
                                safeSend(emitter, name, event.id(),
                                        event.data() == null ? "" : event.data());
                            },
                            error -> {
                                log.warn("agent task plan {} failed: {}", runId, error.getMessage());
                                safeSend(emitter, EVENT_ERROR, lastId.get(), errorJson(error));
                                cleanup.run();
                                emitter.completeWithError(error);
                            },
                            () -> {
                                cleanup.run();
                                emitter.complete();
                            });
        } catch (Exception e) {
            log.error("subscribe agent task plan {} failed", runId, e);
            safeSend(emitter, EVENT_ERROR, lastId.get(), errorJson(e));
            cleanup.run();
            emitter.completeWithError(e);
        }
        return emitter;
    }

    /**
     * 已终结 run 的事件回放：SUCCEEDED 回放已落库回答 + run.completed；
     * FAILED/CANCELLED 回放失败原因。供刷新/重进会话时的断线恢复，不触发新推理。
     */
    private SseEmitter replay(AgentRun run, String lastEventId) {
        SseEmitter emitter = new SseEmitter(0L);
        try {
            if (AgentRun.STATUS_SUCCEEDED.equals(run.getStatus())) {
                ChatMessage answer = messageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getRunId, run.getRunId())
                        .eq(ChatMessage::getRole, ChatMessage.ROLE_ASSISTANT)
                        .eq(ChatMessage::getStatus, ChatMessage.STATUS_OK)
                        .orderByAsc(ChatMessage::getId)
                        .last("limit 1"));
                if (answer != null) {
                    Map<String, Object> payload = new java.util.LinkedHashMap<>();
                    payload.put("content", answer.getContent());
                    payload.put("citations", answer.getCitations() == null ? List.of() : answer.getCitations());
                    payload.put("tool_calls", answer.getToolCalls() == null ? List.of() : answer.getToolCalls());
                    payload.put("usage", Map.of(
                            "prompt_tokens", run.getTokensIn() == null ? 0 : run.getTokensIn(),
                            "completion_tokens", run.getTokensOut() == null ? 0 : run.getTokensOut()));
                    emitter.send(SseEmitter.event().id(lastEventId)
                            .name(EVENT_MESSAGE_COMPLETED).data(objectMapper.writeValueAsString(payload)));
                }
                emitter.send(SseEmitter.event().id(lastEventId).name(EVENT_RUN_COMPLETED)
                        .data(objectMapper.writeValueAsString(Map.of("status", "SUCCEEDED"))));
            } else {
                emitter.send(SseEmitter.event().id(lastEventId).name(EVENT_RUN_FAILED)
                        .data(objectMapper.writeValueAsString(Map.of(
                                "reason", run.getError() == null ? "run " + run.getStatus() : run.getError()))));
            }
            emitter.complete();
        } catch (Exception e) {
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

    /**
     * 取本轮 user 消息之前的近 N 条 user/assistant 消息（时间正序）作为多轮历史。
     * 查询不到或异常时返回 null（Agent 侧按无历史处理，不影响本次 run）。
     */
    private List<AgentRunRequest.ChatTurn> loadHistory(Long conversationId, ChatMessage currentUserMessage) {
        try {
            long beforeSeq = currentUserMessage == null || currentUserMessage.getSeq() == null
                    ? Long.MAX_VALUE : currentUserMessage.getSeq();
            List<ChatMessage> recent = messageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                    .eq(ChatMessage::getConversationId, conversationId)
                    .in(ChatMessage::getRole, List.of(ChatMessage.ROLE_USER, ChatMessage.ROLE_ASSISTANT))
                    .lt(ChatMessage::getSeq, beforeSeq)
                    .orderByDesc(ChatMessage::getSeq)
                    .last("limit " + HISTORY_TURNS));
            java.util.Collections.reverse(recent);
            return recent.stream()
                    .map(m -> {
                        String content = m.getContent();
                        List<Object> atts = m.getAttachments();
                        // 历史轮次只能回填文本：把该轮 user 消息已落库的文档正文前置到 content，
                        // 否则「重新打开会话后 AI 看不到文档」不成立。解析/截断已完成于 resolveAttachments，
                        // 这里只做格式化（单一来源，不复制第二份逻辑）。
                        if (atts != null && !atts.isEmpty()) {
                            content = formatAttachmentDocs(atts) + (content == null ? "" : content);
                        }
                        return new AgentRunRequest.ChatTurn(m.getRole(), content);
                    })
                    .toList();
        } catch (Exception e) {
            log.warn("load history failed for conversation {}: {}", conversationId, e.getMessage());
            return null;
        }
    }

    /**
     * 把前端传入的文件 id 列表解析为「文档参考」快照（不进知识库）：
     *   按 id 查 SysFile → 用与 FileController 同源的落盘路径读字节 → KbFileParser.parse 抽取正文
     *   → 每份截断到 {@link KbController#VIEW_MAX_CHARS}（同源，不另写数字）→ 产出
     *   {file_id, name, text, truncated}。失败（文件不存在 / 解析异常）产出 text:"" + error，记 warn，
     *   且不得让整轮对话 500（铁律 2：不得静默，但也不上抛）。
     */
    private List<Map<String, Object>> resolveAttachments(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return null;
        }
        // 与 FileController.init() 同源：Paths.get(uploadDir).toAbsolutePath().normalize()
        Path root = Paths.get(uploadDir).toAbsolutePath().normalize();
        List<Map<String, Object>> out = new ArrayList<>(ids.size());
        for (Long id : ids) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("file_id", id);
            try {
                SysFile rec = fileMapper.selectById(id);
                if (rec == null || rec.getStoredName() == null) {
                    log.warn("resolve attachment: file not found id={}", id);
                    entry.put("name", "");
                    entry.put("text", "");
                    entry.put("truncated", false);
                    entry.put("error", "文件不存在");
                    out.add(entry);
                    continue;
                }
                entry.put("name", rec.getOriginalName() == null ? "" : rec.getOriginalName());
                Path target = root.resolve(rec.getStoredName());
                if (!Files.exists(target) || !Files.isRegularFile(target)) {
                    log.warn("resolve attachment: file missing on disk id={} path={}", id, target);
                    entry.put("text", "");
                    entry.put("truncated", false);
                    entry.put("error", "文件已不存在");
                    out.add(entry);
                    continue;
                }
                byte[] bytes = Files.readAllBytes(target);
                String text = kbFileParser.parse(rec.getOriginalName(), bytes);
                boolean truncated = text.length() > KbController.VIEW_MAX_CHARS;
                if (truncated) {
                    text = text.substring(0, KbController.VIEW_MAX_CHARS);
                }
                entry.put("text", text);
                entry.put("truncated", truncated);
            } catch (Exception e) {
                // 铁律 2：单份失败不得拖垮整轮对话；记录原因供排查，产出 error 项而非静默丢弃。
                log.warn("resolve attachment failed id={} reason={}", id, e.getMessage());
                entry.put("name", entry.getOrDefault("name", ""));
                entry.put("text", "");
                entry.put("truncated", false);
                entry.put("error", e.getMessage() == null ? "解析失败" : e.getMessage());
            }
            out.add(entry);
        }
        return out;
    }

    /**
     * 把已落库的附件快照格式化为拼进历史轮次 content 的前缀（与当前轮走 attachment_docs 结构化下发不同，
     * 历史轮次只能回填文本，故把文档正文前置到该轮 user content）。
     * 解析/截断逻辑已在 {@link #resolveAttachments} 完成，这里只做格式化，单一来源、不复制第二份。
     */
    private static String formatAttachmentDocs(List<?> attachments) {
        if (attachments == null || attachments.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (Object o : attachments) {
            if (!(o instanceof Map<?, ?> doc)) {
                continue;
            }
            Object name = doc.get("name");
            Object text = doc.get("text");
            Object error = doc.get("error");
            String docName = name == null ? "" : String.valueOf(name);
            sb.append("【参考文档】《").append(docName).append("》\n");
            if (error != null) {
                sb.append("（解析失败：").append(error).append("）\n");
            } else {
                sb.append(text == null ? "" : String.valueOf(text)).append("\n");
            }
            sb.append("【以上为参考文档】\n\n");
        }
        return sb.toString();
    }

    /** List<Map> → List<Object>（ChatMessage.attachments 的声明类型），避免泛型不变性编译错误。 */
    private static List<Object> toObjectList(List<Map<String, Object>> src) {
        if (src == null) {
            return null;
        }
        List<Object> out = new ArrayList<>(src.size());
        out.addAll(src);
        return out;
    }

    /** List<Object>（JSON 回读为 LinkedHashMap）→ List<Map<String,Object>>，供 AgentRunRequest 下发。 */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> toMapList(List<Object> src) {
        if (src == null) {
            return null;
        }
        List<Map<String, Object>> out = new ArrayList<>(src.size());
        for (Object o : src) {
            out.add((Map<String, Object>) o);
        }
        return out;
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
        // 对话级知识库开关：回落读取 context.kb_on（已在 start 阶段解析/合并），保持 null 原样。
        Boolean kbOn = null;
        if (context != null) {
            Object raw = context.get("kb_on");
            if (raw instanceof Boolean b) {
                kbOn = b;
            }
        }
        request.setKbOn(kbOn);
        request.setUserContext(userContext);
        return request;
    }

    /**
     * 数字员工职责范围描述（会话绑定时下发）。
     * 职责边界与所需权限均以 {@link WorkerRole} 为唯一定义源：
     * 自定义职责（description）优先，缺省回落到角色预设职责。
     */
    private Map<String, Object> buildScope(Long workerId, Long projectId, Long tenantId) {
        AgentWorker worker = workerMapper.selectById(workerId);
        if (worker == null) {
            return null;
        }
        WorkerRole role = WorkerRole.of(worker.getWorkerType());
        Map<String, Object> scope = new java.util.LinkedHashMap<>();
        scope.put("worker_id", worker.getId());
        scope.put("name", worker.getName());
        scope.put("role", role.code());
        scope.put("role_name", role.displayName());
        scope.put("duty", worker.getDescription() == null || worker.getDescription().isBlank()
                ? role.duty() : worker.getDescription());
        scope.put("permission", role.requiredPermission());
        // V79 项目会话：并入「该项目对该数字人生效的上下文来源」，使其只在所属项目的知识范围内作答。
        // 若查不到来源，effectiveScope 返回空列表（合法的「无项目上下文」），不阻断对话。
        if (projectId != null && projectId > 0L) {
            scope.put("project_id", projectId);
            scope.put("project_scope", pmAiScopePort.effectiveScope(tenantId, projectId, worker.getId()));
        }
        return scope;
    }

    /** "Bearer xxx" -> "xxx"；异常输入返回 null（agent 侧降级为无工具模式）。 */    private static String stripBearer(String authorization) {
        if (authorization == null || authorization.isBlank()) {
            return null;
        }
        String trimmed = authorization.trim();
        return trimmed.regionMatches(true, 0, "Bearer ", 0, 7) ? trimmed.substring(7).trim() : trimmed;
    }

    private void forward(SseEmitter emitter,
                         ServerSentEvent<String> event,
                         StringBuilder assistant,
                         AtomicReference<String> lastId,
                         AtomicReference<Usage> usageRef,
                         AtomicReference<List<Object>> citationsRef,
                         AtomicReference<List<Object>> toolCallsRef,
                         AtomicReference<String> failureRef,
                         AtomicReference<String> clarificationRef) {
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
            citationsRef.set(readListField(data, "citations"));
            toolCallsRef.set(readListField(data, "tool_calls"));
            usageRef.set(readUsage(data));
            // FR-D6 审批卡点演示：输出涉及对外发布场景时注入"提交审批"卡片事件。
            // 一期为演示链路：前端展示卡片，点击走预留工作流通道。
            if (content != null && contentGuard.findPublishScenario(content) != null) {
                safeSend(emitter, "approval.required", lastId.get(),
                        approvalCardJson(contentGuard.findPublishScenario(content)));
            }
        } else if (EVENT_RUN_COMPLETED.equals(name)) {
            // 尾帧同样带 usage，取后到的为准
            usageRef.set(readUsage(data));
        } else if (EVENT_NEED_CLARIFICATION.equals(name)) {
            // ask_user 暂停帧：记下澄清负载，流末由 completeRun 据其置 WAITING_INPUT。
            // 该帧**已**原样转发给前端（上面的 emitter.send），故前端能渲染澄清卡。
            clarificationRef.set(data);
        } else if (EVENT_ERROR.equals(name)) {
            // Agent 流内错误帧（模型未配置/上游报错/流异常）：记录原因供流结束收口
            String code = readField(data, "code");
            String msg = readField(data, "message");
            String reason = (code == null ? "" : code) + (msg == null ? "" : (code == null ? "" : ": ") + msg);
            failureRef.set(reason.isBlank() ? "agent error" : reason);
        } else if (EVENT_RUN_FAILED.equals(name)) {
            // Agent 明确失败收口：优先取 error 帧的具体 message，否则用 run.failed 的 reason
            if (failureRef.get() == null) {
                String reason = readField(data, "reason");
                if (reason == null || reason.isBlank()) {
                    String errorCode = readField(data, "error_code");
                    reason = errorCode == null ? null : errorCode;
                }
                failureRef.set(reason == null || reason.isBlank() ? "agent run failed" : reason);
            }
        }
    }

    /**
     * 流结束收口（FR-H3 输出侧内容审核）：
     *   · 回答全文未命中 → 正常落库（含 citations/tool_calls）
     *   · 命中违规词 → 中止应答：不落正文，落合规提示消息，run 置 FAILED，并向前端发 error 帧
     */
    private void completeRun(AgentRun run, SseEmitter emitter, AtomicReference<String> lastId,
                             StringBuilder assistant, AtomicReference<Usage> usageRef,
                             AtomicReference<List<Object>> citationsRef,
                             AtomicReference<List<Object>> toolCallsRef,
                             AtomicReference<String> failureRef,
                             AtomicReference<String> clarificationRef) {
        // ask_user 暂停：本轮没有回答、没花词元、run 未终结——挂起等 /resume 回填。
        // 不落 assistant 消息、不发 run.completed、不计费（多轮澄清同理）。
        if (clarificationRef != null && clarificationRef.get() != null) {
            markWaitingInput(run);
            return;
        }
        // Agent 侧已宣告失败（模型未配置/上游报错等）：按 FAILED 收口，不落正文不计费
        String failure = failureRef.get();
        if (failure != null && !failure.isBlank()) {
            log.warn("run {} ended with agent failure: {}", run.getRunId(), failure);
            markFailed(run, failure);
            return;
        }
        String content = assistant.toString();
        String hit = contentGuard.findHit(content);
        if (hit != null) {
            String tip = contentGuard.outputBlockMessage(hit);
            log.warn("run {} output blocked by content guard (hit={})", run.getRunId(), hit);
            safeSend(emitter, EVENT_ERROR, lastId.get(), blockedJson(tip));
            finishBlocked(run, tip);
            return;
        }
        finish(run, content, citationsRef.get(), toolCallsRef.get(), usageRef.get());
    }

    /** 输出命中：落合规提示 assistant 消息 + run 置 FAILED。 */
    private void finishBlocked(AgentRun run, String tip) {
        LocalDateTime endedAt = LocalDateTime.now();
        ChatMessage message = new ChatMessage();
        message.setTenantId(run.getTenantId());
        message.setConversationId(run.getConversationId());
        message.setRunId(run.getRunId());
        message.setRole(ChatMessage.ROLE_ASSISTANT);
        message.setContent(tip);
        message.setContentType("text");
        message.setStatus(ChatMessage.STATUS_FAILED);
        message.setSeq(nextSeq(run.getConversationId()));
        message.setCreatedAt(endedAt);
        message.setCreatedBy(run.getUserId());
        messageMapper.insert(message);
        markFailed(run, "输出命中内容安全策略");
    }

    private void finish(AgentRun run, String content, List<Object> citations, List<Object> toolCalls,
                        Usage usage) {
        LocalDateTime endedAt = LocalDateTime.now();
        if (content != null && !content.isBlank()) {
            // 幂等：同一 run 只落一条回答（并发双订阅时后到者跳过，避免重复消息与重复计数）
            Long existing = messageMapper.selectCount(new LambdaQueryWrapper<ChatMessage>()
                    .eq(ChatMessage::getRunId, run.getRunId())
                    .eq(ChatMessage::getRole, ChatMessage.ROLE_ASSISTANT)
                    .eq(ChatMessage::getStatus, ChatMessage.STATUS_OK));
            if (existing != null && existing > 0) {
                log.info("run {} already has assistant message, skip duplicate persist", run.getRunId());
                return;
            }
            ChatMessage message = new ChatMessage();
            message.setTenantId(run.getTenantId());
            message.setConversationId(run.getConversationId());
            message.setRunId(run.getRunId());
            message.setRole(ChatMessage.ROLE_ASSISTANT);
            message.setContent(content);
            message.setContentType("text");
            message.setCitations(citations == null ? List.of() : citations);
            message.setToolCalls(toolCalls == null ? List.of() : toolCalls);
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
        Usage u = usage == null ? Usage.ZERO : usage;
        AgentRun patch = new AgentRun();
        patch.setId(run.getId());
        patch.setStatus(AgentRun.STATUS_SUCCEEDED);
        patch.setTokensIn(u.prompt());
        patch.setTokensOut(u.completion());
        patch.setEndedAt(endedAt);
        patch.setDurationMs(elapsedMillis(run.getStartedAt()));
        agentRunMapper.updateById(patch);

        // 词元计费：一次 run 只记一笔（run_id 唯一），失败不影响会话结果
        try {
            billingService.recordUsage(run.getRunId(), run.getTenantId(), run.getUserId(),
                    TokenLedger.BIZ_CHAT, conversationTitle(run.getConversationId()),
                    u.prompt(), u.completion());
        } catch (Exception e) {
            log.warn("record token usage failed for run {}: {}", run.getRunId(), e.getMessage());
        }
    }

    /** 账单标题取会话标题（前端建会话时形如「政策咨询专家 · 会话」）。 */
    private String conversationTitle(Long conversationId) {
        ChatConversation conversation = conversationId == null ? null : conversationMapper.selectById(conversationId);
        return conversation == null ? "会话" : displayTitle(conversation);
    }

    private static String displayTitle(ChatConversation conversation) {
        String title = conversation.getTitle();
        if (title == null || title.isBlank()) {
            return "会话";
        }
        return title.replace(" · 会话", "").trim();
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

    /**
     * ask_user 暂停：把 run 置 WAITING_INPUT 挂起。
     * 有意不写 endedAt/durationMs——本轮尚未结束，resume 后仍是同一条 run（同一条 agent_run 记录）。
     * MyBatis-Plus updateById 默认 FieldStrategy.NOT_NULL，null 字段不参与 SET，
     * 故不写 endedAt 不会被清空（不要用 UpdateWrapper.set(null)）。
     */
    private void markWaitingInput(AgentRun run) {
        AgentRun patch = new AgentRun();
        patch.setId(run.getId());
        patch.setStatus(AgentRun.STATUS_WAITING_INPUT);
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

    /** 输出内容被内容安全策略拦截时下发的 error 帧。 */
    private String blockedJson(String tip) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "code", "CONTENT_BLOCKED",
                    "message", tip,
                    "retryable", false));
        } catch (Exception e) {
            return "{\"code\":\"CONTENT_BLOCKED\",\"message\":\"content blocked\",\"retryable\":false}";
        }
    }

    /** FR-D6 审批卡点演示：输出涉及对外发布场景时下发的卡片事件。 */
    private String approvalCardJson(String scenario) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "title", "对外发布审批",
                    "bizType", "doc_publish",
                    "scenario", scenario,
                    "reason", "回答内容涉及对外发布场景，需按合规流程提交审批"));
        } catch (Exception e) {
            return "{\"title\":\"对外发布审批\",\"bizType\":\"doc_publish\"}";
        }
    }

    /** 从 SSE data 中读取数组字段（citations / tool_calls），异常返回空列表。 */
    private List<Object> readListField(String data, String field) {
        if (data == null || data.isBlank()) {
            return List.of();
        }
        try {
            Map<?, ?> map = objectMapper.readValue(data, Map.class);
            Object value = map.get(field);
            if (value instanceof List<?> list) {
                return new java.util.ArrayList<>(list);
            }
            return List.of();
        } catch (Exception e) {
            log.debug("unable to read list field {} from sse data", field);
            return List.of();
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

    /** 词元用量快照：SSE 帧中的 usage{prompt_tokens, completion_tokens}。 */
    private record Usage(int prompt, int completion) {

        static final Usage ZERO = new Usage(0, 0);
    }

    /** 从 SSE data 中读取用量，兼容 {usage:{}} 与 {data:{usage:{}}} 两种形态。 */
    private Usage readUsage(String data) {
        if (data == null || data.isBlank()) {
            return Usage.ZERO;
        }
        try {
            Map<?, ?> map = objectMapper.readValue(data, Map.class);
            Map<?, ?> usage = firstUsage(map);
            if (usage == null) {
                return Usage.ZERO;
            }
            return new Usage(toInt(usage.get("prompt_tokens"), usage.get("input_tokens")),
                    toInt(usage.get("completion_tokens"), usage.get("output_tokens")));
        } catch (Exception e) {
            log.debug("unable to read usage from sse data: {}", data);
            return Usage.ZERO;
        }
    }

    private Map<?, ?> firstUsage(Map<?, ?> map) {
        if (map.get("usage") instanceof Map<?, ?> direct) {
            return direct;
        }
        if (map.get("data") instanceof Map<?, ?> nested && nested.get("usage") instanceof Map<?, ?> inner) {
            return inner;
        }
        return null;
    }

    private static int toInt(Object... candidates) {
        for (Object value : candidates) {
            if (value instanceof Number number) {
                return Math.max(0, number.intValue());
            }
            if (value instanceof String text && !text.isBlank()) {
                try {
                    return Math.max(0, Integer.parseInt(text.trim()));
                } catch (NumberFormatException ignored) {
                    // 继续尝试下一个候选键
                }
            }
        }
        return 0;
    }

    private static String newRunId() {
        String random = String.format("%06d", new Random().nextInt(1_000_000));
        return "run_" + LocalDateTime.now().format(RUN_ID_TS) + "_" + random;
    }
}
