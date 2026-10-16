package cn.aioa.chat.service;

import cn.aioa.chat.entity.AgentRun;
import cn.aioa.chat.entity.ChatMessage;
import cn.aioa.chat.mapper.AgentRunMapper;
import cn.aioa.chat.mapper.ChatConversationMapper;
import cn.aioa.chat.mapper.ChatMessageMapper;
import cn.aioa.chat.config.AgentProperties;
import cn.aioa.chat.service.ContentGuardService;
import cn.aioa.common.exception.BizException;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.resource.service.BillingService;
import cn.aioa.resource.service.KbFileParser;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.SysFileMapper;
import cn.aioa.project.port.PmAiScopePort;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.ServiceTokenProvider;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.atLeast;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import org.mockito.stubbing.Answer;

/**
 * HITL 澄清链（ask_user）运行时行为定点验收。
 *
 * <p><b>纯 JUnit5 + Mockito，不启动 Spring 上下文、不连 DB / 不连真实 agent。</b>
 * 通过反射调用 {@code RunService} 的 private 末帧收口方法
 * {@code forward(...)} / {@code completeRun(...)}，把「运行期行为」钉死，而非复述代码。</p>
 *
 * <p>覆盖：
 * <ul>
 *   <li>T1 暂停不被当完成：need_clarification 后 completeRun 落 WAITING_INPUT，绝不 SUCCEEDED、绝不落 assistant、绝不计费。</li>
 *   <li>T2 挂起态重复订阅绝不重跑：subscribe(WAITING_INPUT) 不发一条 agent 请求，且下发 error 帧（code=WAITING_INPUT）。</li>
 *   <li>T3 resume 前置校验：非 WAITING_INPUT 抛 BizException 且不打 agent；WAITING_INPUT 通过校验（WebClient 链路未打桩，收窄到“无业务校验异常”）。</li>
 *   <li>T4 多轮澄清：第二轮 need_clarification 仍落到 WAITING_INPUT，不是 SUCCEEDED。</li>
 * </ul>
 * </p>
 *
 * <p>mutation test：注释掉 completeRun 顶部那段
 * {@code if (clarificationRef != null && clarificationRef.get() != null) { markWaitingInput(run); return; }}
 * 后，T1/T4 必须变红；还原后全绿。详见交付报告。</p>
 */
@DisplayName("RunService HITL 澄清链运行时行为")
class RunServiceHitlTest {

    private ChatConversationMapper conversationMapper;
    private ChatMessageMapper messageMapper;
    private AgentRunMapper agentRunMapper;
    private WebClient agentWebClient;
    private ServiceTokenProvider serviceTokenProvider;
    private ObjectMapper objectMapper;
    private ScheduledExecutorService sseHeartbeatExecutor;
    private AgentProperties agentProperties;
    private BillingService billingService;
    private ActivityLogService activityLogService;
    private ContentGuardService contentGuard;
    private AgentWorkerMapper workerMapper;
    private PmAiScopePort pmAiScopePort;
    private SysFileMapper fileMapper;
    private KbFileParser kbFileParser;

    private RunService runService;

    private AuthUser user;

    /** 记录 objectMapper.writeValueAsString 的入参，供 T2 校验 WAITING_INPUT 提示帧的 data 内容。 */
    private final List<Object> serializedArgs = new ArrayList<>();

    @BeforeEach
    void setUp() throws Exception {
        conversationMapper = mock(ChatConversationMapper.class);
        messageMapper = mock(ChatMessageMapper.class);
        agentRunMapper = mock(AgentRunMapper.class);
        agentWebClient = mock(WebClient.class);
        serviceTokenProvider = mock(ServiceTokenProvider.class);
        objectMapper = mock(ObjectMapper.class);
        sseHeartbeatExecutor = mock(ScheduledExecutorService.class);
        agentProperties = mock(AgentProperties.class);
        billingService = mock(BillingService.class);
        activityLogService = mock(ActivityLogService.class);
        contentGuard = mock(ContentGuardService.class);
        workerMapper = mock(AgentWorkerMapper.class);
        pmAiScopePort = mock(PmAiScopePort.class);
        fileMapper = mock(SysFileMapper.class);
        kbFileParser = mock(KbFileParser.class);

        // 心跳打桩：返回 mock ScheduledFuture，避免真线程干扰断言（T3 WAITING_INPUT 分支会走到 proxyAgentRun）。
        ScheduledFuture dummyFuture = mock(ScheduledFuture.class);
        when(sseHeartbeatExecutor.scheduleAtFixedRate(any(Runnable.class), anyLong(), anyLong(), any(TimeUnit.class)))
                .thenReturn(dummyFuture);
        when(agentProperties.getHeartbeatSeconds()).thenReturn(30L);

        // 真实 ObjectMapper 行为（completeRun/finish 不用，但 waitingInputNotice 用 writeValueAsString）。
        // 同时把被序列化的对象记下来，供 T2 校验「挂起态重复订阅下发的 WAITING_INPUT 提示帧」的 data。
        // 说明：subscribe(WAITING_INPUT) 走 waitingInputNotice，它先 objectMapper.writeValueAsString(Map)
        // 再 safeSend(error 帧)。standalone SseEmitter 的帧缓冲会在 emitter.complete() 时被刷掉，故这里
        // 从序列化入参侧捕获 data（等价于 emitter 发出的帧内容），比读已清空的缓冲更可靠。
        serializedArgs.clear();
        when(objectMapper.writeValueAsString(any())).thenAnswer((Answer<String>) inv -> {
            Object arg = inv.getArgument(0);
            serializedArgs.add(arg);
            return serialize(arg);
        });

        runService = new RunService(
                conversationMapper, messageMapper, agentRunMapper, agentWebClient, serviceTokenProvider,
                objectMapper, sseHeartbeatExecutor, agentProperties, billingService, activityLogService,
                contentGuard, workerMapper, pmAiScopePort, fileMapper, kbFileParser);

        // AuthUserContext 是 ThreadLocal；@BeforeEach 注入，@AfterEach 清掉，避免污染别的测试。
        user = AuthUser.builder().userId(7L).tenantId(100L).username("tester").build();
        AuthUserContext.set(user);
    }

    @AfterEach
    void tearDown() {
        AuthUserContext.clear();
    }

    // ---------------------------------------------------------------- 反射调用 private 方法

    private static Method forwardMethod() throws NoSuchMethodException {
        return RunService.class.getDeclaredMethod("forward",
                SseEmitter.class, ServerSentEvent.class, StringBuilder.class,
                AtomicReference.class, AtomicReference.class, AtomicReference.class,
                AtomicReference.class, AtomicReference.class, AtomicReference.class);
    }

    private static Method completeRunMethod() throws NoSuchMethodException {
        return RunService.class.getDeclaredMethod("completeRun",
                AgentRun.class, SseEmitter.class, AtomicReference.class, StringBuilder.class,
                AtomicReference.class, AtomicReference.class, AtomicReference.class,
                AtomicReference.class, AtomicReference.class);
    }

    @SuppressWarnings("unchecked")
    private void callForward(SseEmitter emitter, ServerSentEvent<String> event,
                             StringBuilder assistant, AtomicReference<String> lastId,
                             AtomicReference<?> usageRef, AtomicReference<List<Object>> citationsRef,
                             AtomicReference<List<Object>> toolCallsRef, AtomicReference<String> failureRef,
                             AtomicReference<String> clarificationRef) throws Exception {
        Method m = forwardMethod();
        m.setAccessible(true);
        m.invoke(runService, emitter, event, assistant, lastId, usageRef, citationsRef,
                toolCallsRef, failureRef, clarificationRef);
    }

    @SuppressWarnings("unchecked")
    private void callCompleteRun(AgentRun run, SseEmitter emitter, AtomicReference<String> lastId,
                                 StringBuilder assistant, AtomicReference<?> usageRef,
                                 AtomicReference<List<Object>> citationsRef,
                                 AtomicReference<List<Object>> toolCallsRef, AtomicReference<String> failureRef,
                                 AtomicReference<String> clarificationRef) throws Exception {
        Method m = completeRunMethod();
        m.setAccessible(true);
        m.invoke(runService, run, emitter, lastId, assistant, usageRef, citationsRef,
                toolCallsRef, failureRef, clarificationRef);
    }

    // ---------------------------------------------------------------- 构造辅助

    private static String serialize(Object o) {
        try {
            return new ObjectMapper().writeValueAsString(o);
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }

    private AgentRun runningRun() {
        AgentRun run = new AgentRun();
        run.setId(1L);
        run.setTenantId(100L);
        run.setRunId("run-1");
        run.setConversationId(10L);
        run.setUserId(7L);
        run.setStatus(AgentRun.STATUS_RUNNING);
        run.setStartedAt(LocalDateTime.now().minusSeconds(5));
        return run;
    }

    private ServerSentEvent<String> sse(String event, String data) {
        return ServerSentEvent.<String>builder().event(event).data(data).build();
    }

    @SuppressWarnings("unchecked")
    private List<AgentRun> capturedUpdatePatches() {
        var cap = org.mockito.ArgumentCaptor.forClass(AgentRun.class);
        verify(agentRunMapper, atLeast(1)).updateById(cap.capture());
        return cap.getAllValues();
    }

    // T1、T4 共用：跑一轮「need_clarification 帧 + 一条 message.delta → completeRun」
    @SuppressWarnings("unchecked")
    private void runClarificationRound(AgentRun run, SseEmitter emitter,
                                       AtomicReference<String> clarificationRef) throws Exception {
        StringBuilder assistant = new StringBuilder();
        AtomicReference<String> lastId = new AtomicReference<>();
        AtomicReference<Object> usageRef = new AtomicReference<>();
        AtomicReference<List<Object>> citationsRef = new AtomicReference<>(List.of());
        AtomicReference<List<Object>> toolCallsRef = new AtomicReference<>(List.of());
        AtomicReference<String> failureRef = new AtomicReference<>();

        callForward(emitter,
                sse("need_clarification",
                        "{\"question\":\"选哪个\",\"suggested_options\":[{\"value\":\"a\",\"label\":\"A\"}]}"),
                assistant, lastId, usageRef, citationsRef, toolCallsRef, failureRef, clarificationRef);
        // 续跑也会带普通增量帧，但澄清帧已记下，不影响收口口径。
        callForward(emitter, sse("message.delta", "{\"text\":\"（思考中）\"}"),
                assistant, lastId, usageRef, citationsRef, toolCallsRef, failureRef, clarificationRef);
        callCompleteRun(run, emitter, lastId, assistant, usageRef, citationsRef, toolCallsRef, failureRef, clarificationRef);
    }

    // ================================================================ T1

    @Test
    @DisplayName("T1 暂停不被当完成：need_clarification 后 completeRun 落 WAITING_INPUT，绝不 SUCCEEDED / 不落库 / 不计费")
    void t1_pauseNotCompleted() throws Exception {
        AgentRun run = runningRun();
        SseEmitter emitter = mock(SseEmitter.class); // mock：forward 里的 emitter.send 不抛、不依赖 servlet
        AtomicReference<String> clarificationRef = new AtomicReference<>();

        runClarificationRound(run, emitter, clarificationRef);

        // clarificationRef 确实被 forward 记下（帧已原样转发，且写了 ref）
        assertNotNull(clarificationRef.get(), "forward 未把 need_clarification 载荷写进 clarificationRef");

        List<AgentRun> patches = capturedUpdatePatches();
        // 1) updateById 收到的 patch 的 status == WAITING_INPUT
        assertTrue(patches.stream().anyMatch(p -> AgentRun.STATUS_WAITING_INPUT.equals(p.getStatus())),
                "没有任何 updateById patch 把 status 置为 WAITING_INPUT：" + patches);
        // 2) 没有 patch 把 status 置成 SUCCEEDED
        assertFalse(patches.stream().anyMatch(p -> AgentRun.STATUS_SUCCEEDED.equals(p.getStatus())),
                "竟然有 updateById 把 status 置成 SUCCEEDED（暂停被当完成）：" + patches);
        // 3) 不落 assistant 消息
        verify(messageMapper, never()).insert(any(ChatMessage.class));
        // 4) 不计费（记录口径：recordUsage(String,Long,Long,String,String,int,int)）
        verify(billingService, never()).recordUsage(anyString(), any(), any(), anyString(), anyString(), anyInt(), anyInt());
    }

    // ================================================================ T2

    @Test
    @DisplayName("T2 挂起态重复订阅绝不重跑：subscribe(WAITING_INPUT) 不发一条 agent 请求，且下发 error 帧（含 WAITING_INPUT）")
    void t2_waitingInputResubscribeNoRerun() throws Exception {
        AgentRun run = runningRun();
        run.setStatus(AgentRun.STATUS_WAITING_INPUT);
        when(agentRunMapper.selectOne(any())).thenReturn(run);

        runService.subscribe("run-1", null, null);

        // 关键判据：一次 agent 请求都没发（不覆盖 agent 侧断点 → 已完成工具不重跑，Q3）
        verifyNoInteractions(agentWebClient);

        // 下发帧经由 waitingInputNotice：先 objectMapper.writeValueAsString(Map{code=WAITING_INPUT,...})
        // 再 safeSend(event=error, data=该 json)。standalone SseEmitter 缓冲在 complete() 时被清空，
        // 故改从序列化入参侧校验 data（等价于帧内容）。event 名固定为常量 EVENT_ERROR（"error"）。
        boolean hasWaitingInputFrame = serializedArgs.stream().anyMatch(a -> {
            if (!(a instanceof Map<?, ?> m)) {
                return false;
            }
            Object code = m.get("code");
            Object message = m.get("message");
            return "WAITING_INPUT".equals(code)
                    && message != null && message.toString().contains("澄清");
        });
        assertTrue(hasWaitingInputFrame,
                "重复订阅挂起 run 时，未产出 WAITING_INPUT 提示帧（code=WAITING_INPUT 且 message 涉及澄清）。"
                        + " 实际序列化内容：" + serializedArgs);

        // 直接证明 event 名即 error：反射取 RunService.EVENT_ERROR 常量，确认 waitingInputNotice 用的是 error 事件。
        String eventName = readPrivateConstant("EVENT_ERROR");
        assertEquals("error", eventName, "WAITING_INPUT 提示帧应使用 error 事件名（与前端约定一致）");
    }

    // ================================================================ T3

    @Test
    @DisplayName("T3 resume 前置校验：非 WAITING_INPUT 抛 BizException 且不打 agent；WAITING_INPUT 通过校验")
    void t3_resumePrecondition() {
        // ---- 3a: RUNNING 状态下 resume 必须抛 BizException，且不触碰 agentWebClient ----
        AgentRun running = runningRun();
        running.setStatus(AgentRun.STATUS_RUNNING);
        when(agentRunMapper.selectOne(any())).thenReturn(running);

        BizException ex = assertThrows(BizException.class,
                () -> runService.resume("run-1", Map.of("answer", "a"), null, "auth"),
                "RUNNING 状态 resume 未抛 BizException（前置校验失效）");
        assertTrue(ex.getMessage().contains("等待澄清"), "异常信息应说明非等待澄清态：" + ex.getMessage());
        verifyNoInteractions(agentWebClient);

        // ---- 3b: WAITING_INPUT 状态 resume 不应在业务校验阶段抛 BizException ----
        // WebClient 链路未打桩（agentWebClient.post() 返回 null → 后续 NPE），属预期；
        // 故把断言收窄为「业务校验阶段没有抛出 BizException」，并显式记录收窄原因。
        AgentRun waiting = runningRun();
        waiting.setStatus(AgentRun.STATUS_WAITING_INPUT);
        when(agentRunMapper.selectOne(any())).thenReturn(waiting);

        BizException bizException = null;
        try {
            runService.resume("run-1", Map.of("answer", "a"), null, "auth");
        } catch (BizException e) {
            bizException = e;
        } catch (Exception e) {
            // 预期：WAITING_INPUT 已通过业务校验，进入 proxyAgentRun 后，
            // 因 WebClient 链路未打桩（agentWebClient.post() 返回 null → NPE）而失败。
            // 这不是业务校验异常，故忽略；只要不是 BizException 即通过。
        }
        assertNull(bizException,
                "WAITING_INPUT 状态 resume 在业务校验阶段抛出了 BizException（前置校验不应拦住合法续跑）："
                        + (bizException == null ? "" : bizException.getMessage()));
    }

    // ================================================================ T4

    @Test
    @DisplayName("T4 多轮澄清：第二轮 need_clarification 仍落 WAITING_INPUT，不是 SUCCEEDED")
    void t4_multiRoundClarification() throws Exception {
        AgentRun run = runningRun();
        SseEmitter emitter = mock(SseEmitter.class);
        AtomicReference<String> clarificationRef = new AtomicReference<>();

        // 第一轮澄清
        runClarificationRound(run, emitter, clarificationRef);
        // 第二轮澄清（多轮澄清：又来一条 need_clarification）
        runClarificationRound(run, emitter, clarificationRef);

        List<AgentRun> patches = capturedUpdatePatches();
        // 两轮都应落 WAITING_INPUT
        long waitingCount = patches.stream()
                .filter(p -> AgentRun.STATUS_WAITING_INPUT.equals(p.getStatus())).count();
        assertEquals(2, waitingCount, "两轮澄清都应置 WAITING_INPUT，实际：" + patches);
        // 没有任何一轮误置 SUCCEEDED
        assertFalse(patches.stream().anyMatch(p -> AgentRun.STATUS_SUCCEEDED.equals(p.getStatus())),
                "多轮澄清中出现了 SUCCEEDED（把暂停当完成）：" + patches);
    }

    // ---------------------------------------------------------------- 反射读 private 常量

    /** 读 RunService 的 private static final 字段（如 EVENT_ERROR），用于断言事件名与实现约定一致。 */
    private static String readPrivateConstant(String name) {
        try {
            Field f = RunService.class.getDeclaredField(name);
            f.setAccessible(true);
            return String.valueOf(f.get(null));
        } catch (Exception e) {
            throw new IllegalStateException("无法读取 RunService 常量 " + name, e);
        }
    }
}
