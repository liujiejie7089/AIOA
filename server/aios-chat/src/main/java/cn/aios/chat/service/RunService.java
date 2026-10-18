package cn.aios.chat.service;

import cn.aios.chat.config.AgentProperties;
import cn.aios.chat.dto.AgentRunRequest;
import cn.aios.chat.dto.AgentUserContext;
import cn.aios.chat.entity.AgentRun;
import cn.aios.chat.entity.ChatConversation;
import cn.aios.chat.entity.ChatMessage;
import cn.aios.chat.mapper.AgentRunMapper;
import cn.aios.chat.mapper.ChatConversationMapper;
import cn.aios.chat.mapper.ChatMessageMapper;
import cn.aios.common.exception.BizException;
import cn.aios.common.trace.TraceId;
import cn.aios.project.port.PmAiScopePort;
import cn.aios.resource.controller.KbController;
import cn.aios.resource.entity.AgentWorker;
import cn.aios.resource.entity.AiExpert;
import cn.aios.resource.entity.SysFile;
import cn.aios.resource.entity.TokenLedger;
import cn.aios.resource.entity.WorkerCapability;
import cn.aios.resource.model.ExpertSettings;
import cn.aios.resource.mapper.AgentWorkerMapper;
import cn.aios.resource.mapper.AiExpertMapper;
import cn.aios.resource.mapper.SysFileMapper;
import cn.aios.resource.service.ActivityLogService;
import cn.aios.resource.service.BillingService;
import cn.aios.resource.service.ExpertConfigService;
import cn.aios.resource.service.FormTemplateService;
import cn.aios.resource.service.KbFileParser;
import cn.aios.resource.service.WorkerCapabilityService;
import cn.aios.resource.support.WorkerProfile;
import cn.aios.resource.support.WorkerRole;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import cn.aios.security.ServiceTokenProvider;
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
import java.util.Locale;
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
    /**
     * Agent 在需要结构化表单输入时补发的帧（SSE 末帧，之后本轮流正常结束）。
     * 复用 need_clarification 的 WAITING_INPUT 暂停语义：流末由 completeRun 据 clarificationRef
     * 置 WAITING_INPUT，不终结、不落库、不计费，等 /resume 回填。
     * 与 need_clarification 的差异：agent 只下发 {form_code, reason, prefill}，
     * 表单字段（fields/title/submit_label/version）由 Java 从 DB 补全后一并下发给前端。
     */
    private static final String EVENT_NEED_FORM = "need_form";
    /**
     * 会话内跨数字人转交通知帧（SSE 前导帧）：在同一会话改绑数字人后、订阅 agent 之前下发，
     * 告知前端「这个会话现在由另一个数字人接待」，前端据此更新界面并把答案渲染出来。
     * 注意这是**通知帧**、不是暂停帧——流不被打断、不置 WAITING_INPUT、不要求用户重述。
     */
    private static final String EVENT_WORKER_HANDOFF = "worker.handoff";
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
    /** 专家配置解析：数字人专属运行参数（expert_settings）由此解析五层配置。 */
    private final ExpertConfigService expertConfigService;
    /** 专家（ai_expert）只读映射：按 worker_type / name 命中数字人对应的专家。 */
    private final AiExpertMapper expertMapper;
    /** 表单模板渲染：need_form 帧据此从 DB 补全表单字段（单一事实源）。 */
    private final FormTemplateService formTemplateService;
    /** 数字人能力：按其 worker_capability 收窄下发给模型的表单清单（见 narrowFormsByWorker）。 */
    private final WorkerCapabilityService workerCapabilityService;
    /** 项目域只读窄接口：项目会话下发该项目的生效上下文（跨模块单向依赖 chat → project）。 */
    private final PmAiScopePort pmAiScopePort;

    /** 通用上传文件元数据（按 id 查存储名）。 */
    private final SysFileMapper fileMapper;

    /** 纯解析、零持久化（与知识库共用，但不进知识库）。 */
    private final KbFileParser kbFileParser;

    /** 会话服务：转交时复用其 bindWorker 校验与改绑逻辑（同包，无循环依赖）。 */
    private final ConversationService conversationService;

    /** 上传落盘根目录：与 FileController 同源（aios.upload.dir，默认 ./uploads），读取字节时复用同一路径规则。 */
    @Value("${aios.upload.dir:./uploads}")
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
                        List<Long> attachments, String modelRef, Boolean kbOn,
                        String expertKey, String expert) {
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

        // V88 会话级专家落库：把用户本轮选的「专家 AI」解析为库里真实存在的 expert_key 写回会话，
        // 使每一轮（subscribe 重新取 conversation）都能按 chat_conversation.expert_key 下发专家人设。
        // 只认库里真实存在的专家（查不到就当没传，绝不把乱码写进库）；写库失败不得打断对话主链。
        try {
            long tid = user.getTenantId() == null ? 0L : user.getTenantId();
            String targetKey = resolveExpertKeyFromRequest(expertKey, expert, tid);
            if (targetKey != null && !targetKey.equals(conversation.getExpertKey())) {
                conversationMapper.update(null,
                        new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<ChatConversation>()
                                .eq(ChatConversation::getId, conversationId)
                                .set(ChatConversation::getExpertKey, targetKey));
                conversation.setExpertKey(targetKey); // 本地对象同步，后续分支可直接读
                log.info("会话 {} 绑定专家 {}", conversationId, targetKey);
            }
        } catch (Exception e) {
            // 专家解析/写库异常绝不能打断对话主链
            log.warn("会话级专家落库失败（不影响本轮对话）：{}", e.getMessage());
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
        // 会话在下面就绪前先取出来：表单清单必须按「本会话绑定的数字人」收窄（见下）。
        ChatConversation conversation = conversationMapper.selectById(run.getConversationId());
        // === 会话内跨数字人自动转交（handoff，唯一判定点 matchHandoff）===
        // 命中则把同一会话改绑到目标数字人，复用已落库的这条 user 消息继续跑
        // （不重复落 user 消息、不让用户重述）；并通过 SSE 前导帧通知前端。
        // 关键：绝不换会话——loadHistory 按 conversation 查、不过滤 worker，换会话会丢历史。
        HandoffDecision handoff = resolveHandoff(text, conversation);
        Map<String, Object> handoffPayload = null;
        if (handoff != null) {
            conversationService.rebindWorker(conversation, handoff.toWorkerId());
            conversation.setWorkerId(handoff.toWorkerId()); // 本地对象同步：后续 buildScope/收窄表单都用新 worker
            String fromWorkerName = null;
            AgentWorker fromWorker = workerMapper.selectById(handoff.fromWorkerId());
            if (fromWorker != null) {
                fromWorkerName = fromWorker.getName();
            }
            handoffPayload = new LinkedHashMap<>();
            handoffPayload.put("from_worker_id", handoff.fromWorkerId());
            handoffPayload.put("from_worker_name", fromWorkerName);
            handoffPayload.put("to_worker_id", handoff.toWorkerId());
            handoffPayload.put("to_worker_name", handoff.toWorkerName());
            handoffPayload.put("task_name", handoff.taskName());
            handoffPayload.put("question", handoff.question());
            log.info("会话内转交：会话 {} 由数字人 {} 转交给 {}（任务「{}」）",
                    conversation.getId(), handoff.fromWorkerId(), handoff.toWorkerId(), handoff.taskName());
        }
        // 下发可用表单清单（agent 据此选 form_code，避免编造）。清单为空则不注入，
        // 保持与改动前逐字节一致，便于负向对照。
        // ★ 2026-10-18 修：原实现只按**租户**过滤（本租户 43 张全给），完全无视
        //   `worker_capability`（每个数字人恰好绑 1 张表）。后果实测：
        //   用车助手数字人问「我要报销打车费」→ 弹出 expense_form（费用报销，别人的表）；
        //   会议助手数字人问「我要申请出差」→ 弹出 travel_form。43/43 个数字人都有这个问题。
        //   现已按能力收窄：数字人绑几张就发几张；未配置能力的（GENERAL 等历史数字人）保持租户全量。
        // V88 专家会话（未绑数字人 + 选了专家）整段跳过：业务表单是数字员工的能力，专家 AI 是顾问，
        // 下发会让模型把咨询当成办理（实测法律专家弹「合同起草」表、正文为空）；
        // 普通会话（未绑数字人且未选专家）保持既有能力不受影响。唯一判定点 isExpertConversation。
        if (!isExpertConversation(conversation)) {
            try {
                List<Map<String, Object>> forms =
                        narrowFormsByWorker(formTemplateService.listAvailable(user.getTenantId()), conversation);
                if (forms != null && !forms.isEmpty()) {
                    request.setAvailableForms(forms);
                }
            } catch (Exception e) {
                // 表单表缺失/查询异常绝不能打断对话主链
                log.warn("下发可用表单清单失败（不影响本轮对话）：{}", e.getMessage());
            }
        }
        // ★ 确定性开表提示：该数字人**只绑一张表** + 用户原话点名了这项任务 ⇒ 下发 form_hint。
        //   为什么不在流末由后端补发 need_form 帧：那样图里没有 interrupt()、没有 checkpoint，
        //   用户提交表单后 `/resume` 无从恢复（实测续跑零帧、模型不再确认，表单数据无处可去）。
        //   故判定留在后端一处（shouldOpenSingleForm），执行交给 agent 走真实 interrupt()。
        // V88 专家会话整段跳过（与上面同一唯一判定点 isExpertConversation）：确定性开表同样是数字员工的能力，
        // 专家会话不应触发；普通会话（未绑数字人且未选专家）保持既有能力不受影响。
        if (!isExpertConversation(conversation)) {
            try {
                WorkerCapability onlyCap = uniqueCapability(conversation == null ? null : conversation.getWorkerId());
                if (onlyCap != null && onlyCap.getFormCode() != null && !onlyCap.getFormCode().isBlank()
                        && shouldOpenSingleForm(text, onlyCap.getTaskName(), onlyCap.getTaskCode())) {
                    Map<String, Object> hint = new LinkedHashMap<>();
                    hint.put("form_code", onlyCap.getFormCode());
                    if (onlyCap.getTaskName() != null && !onlyCap.getTaskName().isBlank()) {
                        hint.put("reason", onlyCap.getTaskName());
                    }
                    request.setFormHint(hint);
                    log.info("数字人 {} 命中确定性开表：{}（用户原话点名任务「{}」）",
                            onlyCap.getWorkerId(), onlyCap.getFormCode(), onlyCap.getTaskName());
                }
            } catch (Exception e) {
                // 能力表读取异常不得打断主链
                log.warn("确定性开表判定失败（不影响本轮对话）：{}", e.getMessage());
            }
        }
        request.setUserToken(stripBearer(authorization));
        request.setHistory(loadHistory(run.getConversationId(), userMessage));
        // 本轮上传文档：把已落库的参考正文结构化下发 Agent（不进 content，结构体现在 attachment_docs）。
        List<Map<String, Object>> attachmentDocs = toMapList(userMessage == null ? null : userMessage.getAttachments());
        if (attachmentDocs != null && !attachmentDocs.isEmpty()) {
            request.setAttachmentDocs(attachmentDocs);
        }
        // 会话级模型路由：Agent 按 model_ref 选择 provider（默认走 MODEL_DEFAULT）
        if (conversation != null && conversation.getModelRef() != null && !conversation.getModelRef().isBlank()) {
            request.setModelRef(conversation.getModelRef());
        }
        // V21 会话绑定数字员工：下发职责范围，Agent 侧据此限定回答边界（越界拒答）
        // V79 项目会话：scope 里并入该项目的生效上下文（项目隔离的「下行」一半；
        //              准入的「上行」硬校验已在 ConversationService.bindWorker 完成）
        if (conversation != null && conversation.getWorkerId() != null) {
            request.setScope(buildScope(conversation.getWorkerId(),
                    conversation.getProjectId(), conversation.getTenantId()));
            // 数字人专属运行参数：从 ai_expert 解析后下发 expert_settings（顶层字段，agent 侧直接读）。
            // 取不到（当前 agent_worker 与 ai_expert 无外键）则「不注入」，保持 agent 默认值。
            Map<String, Object> expertSettings = resolveExpertSettings(conversation.getWorkerId(), user);
            if (expertSettings != null) {
                request.setExpertSettings(expertSettings);
            }
        }
        // V88 专家会话（不绑数字员工）：按 chat_conversation.expert_key 解析专家画像 + 五层配置，
        // 把 systemPrompt 下发到 agent —— 这是「专家真的会干这行」的唯一来源。
        // 与上面 worker 分支是 else-if 语义（worker 优先）：绑定数字员工的会话走职责边界，
        // 不绑数字员工的会话才走专家人设，二者互斥，绝不互相覆盖。
        else if (conversation != null && conversation.getExpertKey() != null
                && !conversation.getExpertKey().isBlank()) {
            Map<String, Object> expert = buildExpertProfile(conversation, user);
            if (expert != null) {
                request.setExpert(expert);
                Map<String, Object> settings = resolveExpertConfig(conversation.getExpertKey(), user);
                if (settings != null) {
                    request.setExpertSettings(settings);
                }
            }
        }
        // 项目维度与「是否绑定数字员工」解耦：未绑数字人的项目会话同样要告诉 agent 当前项目，
        // 否则 agent 会反问「上传到哪个系统或平台」（实测缺陷）。项目名以库为准，不由前端传入。
        if (conversation != null && conversation.getProjectId() != null && conversation.getProjectId() > 0L) {
            Map<String, Object> brief = pmAiScopePort.projectBrief(conversation.getTenantId(), conversation.getProjectId());
            if (brief != null) {
                request.setProject(brief);
            }
        }
        Long originWorkerId = conversation != null ? conversation.getWorkerId() : null;
        String originWorkerName = null;
        if (originWorkerId != null) {
            AgentWorker originWorker = workerMapper.selectById(originWorkerId);
            originWorkerName = originWorker != null ? originWorker.getName() : null;
        }
        if (handoffPayload != null) {
            request.setHandoff(handoffPayload);
        }
        return proxyAgentRun("/internal/v1/runs", request, run, lastEventId, originWorkerId, originWorkerName,
                handoffPayload);
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
    private SseEmitter proxyAgentRun(String uri, Object requestBody, AgentRun run, String lastEventId,
                                     Long originWorkerId, String originWorkerName,
                                     Map<String, Object> handoffPayload) {
        SseEmitter emitter = new SseEmitter(0L);
        // 会话内转交前导帧：在订阅 agent 之前下发，告知前端「同一会话改绑了数字人」（这是通知帧、
        // 不是暂停帧——流不被打断）。resume 调用时 handoffPayload 为 null，不发送。
        if (handoffPayload != null && !handoffPayload.isEmpty()) {
            try {
                safeSend(emitter, EVENT_WORKER_HANDOFF, lastEventId,
                        objectMapper.writeValueAsString(handoffPayload));
            } catch (Exception e) {
                log.warn("send worker handoff prelude failed: {}", e.getMessage());
            }
        }
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
                                    citationsRef, toolCallsRef, failureRef, clarificationRef,
                                    run.getTenantId(), originWorkerId, originWorkerName),
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
        ChatConversation resumeConv = conversationMapper.selectById(run.getConversationId());
        Long originWorkerId = resumeConv != null ? resumeConv.getWorkerId() : null;
        String originWorkerName = null;
        if (originWorkerId != null) {
            AgentWorker originWorker = workerMapper.selectById(originWorkerId);
            originWorkerName = originWorker != null ? originWorker.getName() : null;
        }
        return proxyAgentRun("/internal/v1/runs/" + run.getRunId() + "/resume", resumeBody, run,
                lastEventId, originWorkerId, originWorkerName, null);
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
        // 角色画像走唯一判定点：OA 模块数字人（worker_type=OA_*）不在 WorkerRole 枚举内，
        // 用 WorkerRole.of 会被静默降级成「通用办公助手」，系统提示里的职责边界随之全错。
        WorkerProfile role = WorkerProfile.of(worker.getWorkerType(), worker.getName(), worker.getDescription());
        Map<String, Object> scope = new java.util.LinkedHashMap<>();
        scope.put("worker_id", worker.getId());
        scope.put("name", worker.getName());
        scope.put("role", role.code());
        scope.put("role_name", role.roleName());
        scope.put("duty", worker.getDescription() == null || worker.getDescription().isBlank()
                ? role.duty() : worker.getDescription());
        scope.put("permission", role.permission());
        // V79 项目会话：并入「该项目对该数字人生效的上下文来源」，使其只在所属项目的知识范围内作答。
        // 若查不到来源，effectiveScope 返回空列表（合法的「无项目上下文」），不阻断对话。
        if (projectId != null && projectId > 0L) {
            scope.put("project_id", projectId);
            scope.put("project_scope", pmAiScopePort.effectiveScope(tenantId, projectId, worker.getId()));
        }
        return scope;
    }

    /**
     * 解析数字人专属运行参数（expert_settings）：数字员工(agent_worker)当前库表与 ai_expert 无直接外键，
     * 故按 worker_type / name 命中 ai_expert（约定：worker_type 直等于 expert_key，或 name 同名；
     * 跨租户回落到平台模板 tenant=0）。命中后按当前用户上下文解析五层配置（ExpertConfigService.resolve），
     * 转成下发给 agent 的 Map（键名与 ExpertSettings 模型字段一致）。
     *
     * 「取不到 = 不注入」（返回 null，调用方据此不 set），绝不返回空对象——
     * 空对象会让 agent 侧 es.get(...) 拿到空串把 ExpertSettings 的默认值打掉。
     * 现状：worker_type 取值为 OA_*（如 OA_DOC），与 ai_expert.expert_key 取值（policy/legal/...）
     * 命名不重合，故按当前数据「取不到」，本分支为后续建立关联（如 agent_worker 增加 expert_key 列、
     * 或约定 worker_type == expert_key）预留，命中后自动生效。
     */
    /**
     * 该数字人允许使用的表单码集合。
     *
     * @return {@code null} 表示**不限制**——未绑数字人、数字人没配能力（GENERAL / LEAVE_APPROVER 等
     *         历史数字人）、或读库异常。其余情况返回集合（可能为空，见下）。
     *         集合为空表示「能力指向的表全被停用」，调用方据此拒绝任何表单。
     */
    private java.util.Set<String> allowedFormCodes(Long workerId) {
        if (workerId == null) {
            return null;
        }
        List<WorkerCapability> caps;
        try {
            caps = workerCapabilityService.listByWorker(workerId);
        } catch (Exception e) {
            // 能力表读不到 ≠ 数字人没能力：宁可放开（保持历史行为），也不要让整轮对话失去表单
            log.warn("读取数字人 {} 能力失败，本轮不限制表单：{}", workerId, e.getMessage());
            return null;
        }
        if (caps == null || caps.isEmpty()) {
            return null;
        }
        java.util.Set<String> allowed = new java.util.HashSet<>();
        for (WorkerCapability c : caps) {
            if (c.getEnabled() != null && c.getEnabled() == 0) {
                continue;
            }
            if (c.getFormCode() != null && !c.getFormCode().isBlank()) {
                allowed.add(c.getFormCode());
            }
        }
        return allowed;
    }

    /**
     * 按「本会话绑定的数字人」收窄表单清单。
     *
     * <p><b>为什么必须有这一步</b>：`worker_capability` 的语义就是「这个数字人办什么事、用哪张表」，
     * 每个 OA 数字人恰好绑 1 张。而 {@link FormTemplateService#listAvailable} 只按租户过滤，
     * 于是每个数字人都拿到全租户 43 张表 —— 模型可以合法地弹出**别的数字人的表单**。
     * 2026-10-18 实测（tenant 3，真实链路）：用车助手（vehicle_apply）问「我要报销打车费」
     * 实际弹出 expense_form；会议助手（meeting_book）问「我要申请出差」实际弹出 travel_form。
     * 这不是模型违规，是下发面给宽了。</p>
     *
     * <p><b>兼容性</b>：未绑数字人 / 数字人没配能力 / 读能力异常 三种情况保持租户全量，
     * 不改变历史数字人的能力面。只有「确实配了能力」才收窄，且支持一个数字人配多张。</p>
     *
     * <p><b>能力指向的表不在清单里</b>（被停用/改码）时返回空列表，让调用方「不下发清单」——
     * 宁可让模型说没这功能，也不能让它去调一张已停用的表。</p>
     */
    /**
     * 是否为「专家会话」：未绑数字员工（workerId 为空）且已选专家（expert_key 非空白）。
     *
     * <p><b>唯一判定点</b>（铁律 #1）：V88 专家会话不该暴露任何业务表单——
     * 业务表单是数字员工的能力，专家 AI 是顾问，下发会让模型把咨询当成办理
     * （实测法律专家问「试用期最长多久」被弹「合同起草」表、正文为空）。
     * 「未绑数字人且未选专家」的普通会话**不算**专家会话，保持既有开表能力不受影响
     * （经典形态里用户直接说「我要报销」仍会开表）。</p>
     */
    private boolean isExpertConversation(ChatConversation c) {
        return c != null && c.getWorkerId() == null
                && c.getExpertKey() != null && !c.getExpertKey().isBlank();
    }

    private List<Map<String, Object>> narrowFormsByWorker(List<Map<String, Object>> forms,
                                                          ChatConversation conversation) {
        if (forms == null || forms.isEmpty() || conversation == null) {
            return forms;
        }
        java.util.Set<String> allowed = allowedFormCodes(conversation.getWorkerId());
        if (allowed == null) {
            return forms;
        }
        List<Map<String, Object>> narrowed = new ArrayList<>();
        for (Map<String, Object> f : forms) {
            Object code = f.get("code");
            if (code != null && allowed.contains(String.valueOf(code))) {
                narrowed.add(f);
            }
        }
        if (narrowed.isEmpty()) {
            log.warn("数字人 {} 的能力表单不在可用清单内（可能已停用），本轮不下发表单：{}",
                    conversation.getWorkerId(), allowed);
            return narrowed;
        }
        log.debug("数字人 {} 表单清单已收窄为 {}：{}", conversation.getWorkerId(), narrowed.size(), allowed);
        return narrowed;
    }

    private Map<String, Object> resolveExpertSettings(Long workerId, AuthUser user) {
        AgentWorker worker = workerMapper.selectById(workerId);
        if (worker == null) {
            return null;
        }
        AiExpert expert = findExpertForWorker(worker);
        if (expert == null || expert.getExpertKey() == null || expert.getExpertKey().isBlank()) {
            return null;
        }
        long tid = user.getTenantId() == null ? 0L : user.getTenantId();
        ExpertSettings settings = expertConfigService.resolve(
                tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(), expert.getExpertKey())
                .settings();
        return expertSettingsToMap(settings);
    }

    /** 按 worker_type / name 命中 ai_expert（先本租户，再回落平台模板）。无命中返回 null。 */
    private AiExpert findExpertForWorker(AgentWorker worker) {
        String wt = worker.getWorkerType();
        if (wt != null && !wt.isBlank()) {
            AiExpert e = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                    .eq(AiExpert::getTenantId, worker.getTenantId() == null ? 0L : worker.getTenantId())
                    .eq(AiExpert::getExpertKey, wt.trim())
                    .last("limit 1"));
            if (e != null) {
                return e;
            }
            e = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                    .eq(AiExpert::getTenantId, 0L)
                    .eq(AiExpert::getExpertKey, wt.trim())
                    .last("limit 1"));
            if (e != null) {
                return e;
            }
        }
        String name = worker.getName();
        if (name != null && !name.isBlank()) {
            AiExpert e = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                    .eq(AiExpert::getTenantId, worker.getTenantId() == null ? 0L : worker.getTenantId())
                    .eq(AiExpert::getName, name.trim())
                    .last("limit 1"));
            if (e != null) {
                return e;
            }
        }
        return null;
    }

    /** 把 ExpertSettings 转成下发给 agent 的 Map（仅含非空键，避免注入 null 把默认值打掉）。 */
    private Map<String, Object> expertSettingsToMap(ExpertSettings s) {
        Map<String, Object> m = new LinkedHashMap<>();
        if (s.getEnabled() != null) m.put("enabled", s.getEnabled());
        if (s.getVisibleScope() != null) m.put("visibleScope", s.getVisibleScope());
        if (s.getVisibleTargets() != null) m.put("visibleTargets", s.getVisibleTargets());
        if (s.getDefaultEnabled() != null) m.put("defaultEnabled", s.getDefaultEnabled());
        if (s.getKbScope() != null) m.put("kbScope", s.getKbScope());
        if (s.getModel() != null) m.put("model", s.getModel());
        if (s.getTemperature() != null) m.put("temperature", s.getTemperature());
        if (s.getTopK() != null) m.put("topK", s.getTopK());
        if (s.getThreshold() != null) m.put("threshold", s.getThreshold());
        if (s.getRetrievalMode() != null) m.put("retrievalMode", s.getRetrievalMode());
        if (s.getTools() != null) m.put("tools", s.getTools());
        if (s.getSort() != null) m.put("sort", s.getSort());
        if (s.getChunkSize() != null) m.put("chunkSize", s.getChunkSize());
        if (s.getChunkOverlap() != null) m.put("chunkOverlap", s.getChunkOverlap());
        if (s.getSystemPrompt() != null) m.put("systemPrompt", s.getSystemPrompt());
        if (s.getKnowledgeScope() != null) m.put("knowledgeScope", s.getKnowledgeScope());
        return m;
    }

    // ===== V88 专家会话链路（不绑数字员工）=====
    // 以下方法服务于「会话选了专家 AI」这一支路：把 ai_expert 解析为画像与运行参数下发 agent。
    // 与 worker 支路互斥（subscribe 里 else-if），worker 优先。

    /** 按 expert_key 命中 ai_expert（先本租户，再回落平台模板 tenant=0）。无命中返回 null。 */
    private AiExpert findExpertByKey(String expertKey, long tenantId) {
        if (expertKey == null || expertKey.isBlank()) {
            return null;
        }
        AiExpert e = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, tenantId)
                .eq(AiExpert::getExpertKey, expertKey.trim())
                .last("limit 1"));
        if (e != null) {
            return e;
        }
        return expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .eq(AiExpert::getExpertKey, expertKey.trim())
                .last("limit 1"));
    }

    /** 按 name 命中 ai_expert（先本租户，再回落平台模板 tenant=0）。无命中返回 null。 */
    private AiExpert findExpertByName(String name, long tenantId) {
        if (name == null || name.isBlank()) {
            return null;
        }
        AiExpert e = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, tenantId)
                .eq(AiExpert::getName, name.trim())
                .last("limit 1"));
        if (e != null) {
            return e;
        }
        return expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .eq(AiExpert::getName, name.trim())
                .last("limit 1"));
    }

    /**
     * 把前端传来的「专家」解析成库里真实存在的 expert_key。
     * 优先级：expertKey（直当 key 命中）&gt; expert（先当 key、再当 name 命中）。
     * 只认库里真实存在的专家；命中不到返回 null（调用方据此不写库，绝不把乱码写进库）。
     */
    private String resolveExpertKeyFromRequest(String expertKey, String expert, long tenantId) {
        if (expertKey != null && !expertKey.isBlank()) {
            AiExpert e = findExpertByKey(expertKey.trim(), tenantId);
            if (e != null && e.getExpertKey() != null && !e.getExpertKey().isBlank()) {
                return e.getExpertKey();
            }
            return null; // key 传了但库里没有 → 当没传，不写乱码
        }
        if (expert != null && !expert.isBlank()) {
            AiExpert byKey = findExpertByKey(expert.trim(), tenantId);
            if (byKey != null && byKey.getExpertKey() != null && !byKey.getExpertKey().isBlank()) {
                return byKey.getExpertKey();
            }
            AiExpert byName = findExpertByName(expert.trim(), tenantId);
            if (byName != null && byName.getExpertKey() != null && !byName.getExpertKey().isBlank()) {
                return byName.getExpertKey();
            }
        }
        return null;
    }

    /**
     * 按会话的 expert_key 解析专家画像（下发 agent 的 expert 字段）。
     * 库里查不到返回 null（不注入）；system_prompt 取自 ExpertConfigService.resolve 的 settings。
     */
    private Map<String, Object> buildExpertProfile(ChatConversation conv, AuthUser user) {
        if (conv == null || conv.getExpertKey() == null || conv.getExpertKey().isBlank()) {
            return null;
        }
        long tid = user.getTenantId() == null ? 0L : user.getTenantId();
        AiExpert e = findExpertByKey(conv.getExpertKey(), tid);
        if (e == null) {
            return null;
        }
        ExpertSettings settings = expertConfigService.resolve(
                tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(),
                e.getExpertKey()).settings();
        return expertProfileMap(e, settings);
    }

    /**
     * 按 expert_key 解析五层配置并转成下发 agent 的 expert_settings Map（键名与 ExpertSettings 同构）。
     * 与 resolveExpertSettings(workerId, user) 同构，但直接按 expertKey 解析。
     */
    private Map<String, Object> resolveExpertConfig(String expertKey, AuthUser user) {
        long tid = user.getTenantId() == null ? 0L : user.getTenantId();
        ExpertSettings settings = expertConfigService.resolve(
                tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(),
                expertKey).settings();
        return expertSettingsToMap(settings);
    }

    /**
     * 把 AiExpert + 其运行参数 ExpertSettings 拼成下发 agent 的 expert 画像 Map（纯函数，便于单测）。
     * 只放非空键（空字符串/空集合不放），避免把 agent 侧默认值打掉。
     * 键：key / name / summary / intro / tags / recs / system_prompt / knowledge_scope。
     */
    static Map<String, Object> expertProfileMap(AiExpert e, ExpertSettings s) {
        Map<String, Object> m = new LinkedHashMap<>();
        if (e == null) {
            return m;
        }
        if (e.getExpertKey() != null && !e.getExpertKey().isBlank()) {
            m.put("key", e.getExpertKey());
        }
        if (e.getName() != null && !e.getName().isBlank()) {
            m.put("name", e.getName());
        }
        if (e.getSummary() != null && !e.getSummary().isBlank()) {
            m.put("summary", e.getSummary());
        }
        if (e.getIntro() != null && !e.getIntro().isBlank()) {
            m.put("intro", e.getIntro());
        }
        if (e.getTags() != null && !e.getTags().isEmpty()) {
            m.put("tags", e.getTags());
        }
        if (e.getRecs() != null && !e.getRecs().isEmpty()) {
            m.put("recs", e.getRecs());
        }
        if (s != null && s.getSystemPrompt() != null && !s.getSystemPrompt().isBlank()) {
            m.put("system_prompt", s.getSystemPrompt());
        }
        if (s != null && s.getKnowledgeScope() != null && !s.getKnowledgeScope().isBlank()) {
            m.put("knowledge_scope", s.getKnowledgeScope());
        }
        return m;
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
                         AtomicReference<String> clarificationRef,
                         Long tenantId,
                         Long originWorkerId,
                         String originWorkerName) {
        String name = event.event() == null ? "message" : event.event();
        String data = event.data() == null ? "" : event.data();
        // need_form：在「无条件转发」之前补全表单字段（单一事实源在 DB）。
        // 否则前端会先收到一次原始帧、再收到补全帧，渲染出两条表单卡。
        String outData = data;
        if (EVENT_NEED_FORM.equals(name)) {
            outData = buildNeedFormPayload(data, tenantId, originWorkerId, originWorkerName);
        }
        if (event.id() != null) {
            lastId.set(event.id());
        }
        try {
            emitter.send(SseEmitter.event().id(event.id()).name(name).data(outData));
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
        } else if (EVENT_NEED_FORM.equals(name)) {
            // 表单补全帧：仅当 payload 不含 error 才置暂停标记。
            // 定义查不到的帧带 error，不挂起，让 run 走失败/收尾，避免挂死。
            if (!needFormHasError(outData)) {
                clarificationRef.set(outData);
            }
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
     * 把 need_form 原始帧（{form_code, reason, prefill}）补全成前端契约：
     * {form_code, version, title, submit_label, reason, fields, prefill, origin}。
     * 表单字段（fields/title/submit_label/version）由 Java 从 DB 补全（单一事实源），
     * agent 只下发 form_code，避免前端/agent 各自维护字段定义而漂移。
     * 表单定义查不到时返回带 error 的 payload（且调用方据此「不设暂停标记」），
     * 让 run 走失败/收尾，避免挂死。
     */
    private String buildNeedFormPayload(String rawData, Long tenantId, Long workerId, String workerName) {
        Map<String, Object> frame;
        try {
            frame = objectMapper.readValue(rawData, Map.class);
        } catch (Exception e) {
            log.warn("need_form 解析失败: {}", e.getMessage());
            return errorNeedForm(null, "表单帧格式错误: " + e.getMessage(), rawData);
        }
        Object codeObj = frame.get("form_code");
        String code = codeObj == null ? null : String.valueOf(codeObj);
        if (code == null || code.isBlank()) {
            return errorNeedForm(null, "表单定义不存在: (空 form_code)", rawData);
        }
        // ★ 出口兜底闸：下发面已按数字人能力收窄，但模型仍可能编造 form_code
        //   （提示词正文里就有 leave_request 示例）。2026-10-18 实测：会议助手在
        //   available_forms 只有 meeting_book 的情况下，面对「我要申请出差」仍产出
        //   form_code=leave_request，而 resolveForRender 只按租户查、照样渲染成功
        //   ⇒ 用户看到「会议助手弹出请假表单」。这里做最后一道确定性拦截，
        //   不依赖模型守规矩（与「确认归 UI、写工具不下发」同一条设计原则）。
        java.util.Set<String> allowed = allowedFormCodes(workerId);
        if (allowed != null && !allowed.contains(code)) {
            log.warn("need_form 越权拦截：数字人 {} 请求表单 {} 不在其能力内（允许={}），已拒绝渲染",
                    workerId, code, allowed);
            return errorNeedForm(code, "该数字人不办理这张表单（" + code + "），已拦截", rawData);
        }
        // 实际签名 resolveForRender(Long tenantId, String code)：tenantId 用于解析动态选项（如 leave_types）。
        Object renderRaw;
        try {
            renderRaw = formTemplateService.resolveForRender(tenantId, code);
        } catch (Exception e) {
            log.warn("need_form 解析表单模板失败 code={}: {}", code, e.getMessage());
            return errorNeedForm(code, "表单定义不存在: " + code, rawData);
        }
        Map<String, Object> render;
        try {
            render = objectMapper.convertValue(renderRaw, Map.class);
        } catch (Exception e) {
            log.warn("need_form render 转换失败 code={}: {}", code, e.getMessage());
            return errorNeedForm(code, "表单定义不存在: " + code, rawData);
        }
        // FormRender 实测字段：code / name / version / moduleCode / submitPolicy / fields
        // （无 formCode/title/submitLabel）。取不到 code 视为无效。
        if (render == null || render.get("code") == null) {
            return errorNeedForm(code, "表单定义不存在: " + code, rawData);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("form_code", render.get("code"));
        payload.put("version", render.get("version"));
        payload.put("title", render.get("name"));
        // submit_label 是**按钮文案**（docs/52 §3.3 need_form 契约：`"submit_label": "提交"`），
        // 不是策略串。2026-10-17 实测缺陷：这里原样塞了 submitPolicy ⇒ 提交按钮显示
        // 「LEDGER」/「APPROVAL+RESUME」，用户看到的是内部枚举。按策略给中文文案。
        String submitPolicy = render.get("submitPolicy") == null ? "" : String.valueOf(render.get("submitPolicy"));
        payload.put("submit_label", submitPolicy.contains("APPROVAL") ? "提交审批" : "提交");
        payload.put("reason", frame.get("reason"));
        payload.put("fields", render.get("fields"));
        payload.put("prefill", frame.get("prefill"));
        Map<String, Object> origin = new LinkedHashMap<>();
        origin.put("kind", "worker");
        origin.put("worker_id", workerId);
        origin.put("worker_name", workerName);
        payload.put("origin", origin);
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception e) {
            return errorNeedForm(code, "表单定义不存在: " + code, rawData);
        }
    }

    /** need_form 失败回退 payload：带 error（不挂起），并尽量透传原帧的 reason/prefill 供前端提示。 */
    private String errorNeedForm(String code, String message, String rawData) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("form_code", code);
        payload.put("error", message);
        try {
            Map<String, Object> frame = objectMapper.readValue(rawData, Map.class);
            payload.put("reason", frame.get("reason"));
            payload.put("prefill", frame.get("prefill"));
        } catch (Exception ignored) {
            // 原帧都解析不了就不透传，error 已足够说明
        }
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception e) {
            return "{\"form_code\":" + (code == null ? "null" : "\"" + code + "\"")
                    + ",\"error\":\"" + message + "\"}";
        }
    }

    /** 判断 need_form 的已补全 payload 是否处于「定义查不到」状态（带 error 键）。 */
    private boolean needFormHasError(String payload) {
        if (payload == null || payload.isBlank()) {
            return false;
        }
        try {
            Map<?, ?> m = objectMapper.readValue(payload, Map.class);
            return m.containsKey("error");
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * 取「数字人唯一启用的能力行」（恰好 1 条启用记录时返回它，否则 null），
     * 供确定性开表判据拿到 taskName / taskCode（判定只在后端这一处）。读库异常返回 null。
     */
    private WorkerCapability uniqueCapability(Long workerId) {
        if (workerId == null) {
            return null;
        }
        try {
            List<WorkerCapability> caps = workerCapabilityService.listByWorker(workerId);
            if (caps == null || caps.isEmpty()) {
                return null;
            }
            WorkerCapability found = null;
            for (WorkerCapability c : caps) {
                if (c.getEnabled() != null && c.getEnabled() == 0) {
                    continue;
                }
                if (c.getFormCode() == null || c.getFormCode().isBlank()) {
                    continue;
                }
                if (found != null) {
                    return null;            // 多于一条启用能力 → 不构成「唯一」
                }
                found = c;
            }
            return found;
        } catch (Exception e) {
            log.warn("读取数字人 {} 能力失败（确定性开表跳过）：{}", workerId, e.getMessage());
            return null;
        }
    }


    /**
     * 单表单数字人的确定性开表判据：用户原话点名了该任务 ⇒ 直接开表。
     * 纯函数、无模型参与，可单测。规则：
     *  - userText 为 null/blank → false
     *  - taskName 与 taskCode 都取不到（null/blank）→ false
     *  - 三者统一 trim() + 转小写；taskName 长度 < 2 时忽略它（避免单字任务名误命中）
     *  - 命中：userText 含 taskName，或（taskCode 非空且 userText 含 taskCode）→ true
     *  - 否则 false
     */
    static boolean shouldOpenSingleForm(String userText, String taskName, String taskCode) {
        if (userText == null || userText.isBlank()) {
            return false;
        }
        if ((taskName == null || taskName.isBlank()) && (taskCode == null || taskCode.isBlank())) {
            return false;
        }
        String u = userText.trim().toLowerCase(Locale.ROOT);
        String tn = taskName == null ? "" : taskName.trim().toLowerCase(Locale.ROOT);
        String tc = taskCode == null ? "" : taskCode.trim().toLowerCase(Locale.ROOT);
        if (tn.length() >= 2 && u.contains(tn)) {
            return true;
        }
        return !tc.isEmpty() && u.contains(tc);
    }

    /** 转交候选：一个「数字人 × 任务」绑定（taskName 用于中文命中，taskCode 用于码命中）。 */
    public record HandoffCandidate(Long workerId, String workerName, String taskName, String taskCode) {
    }

    /**
     * 转交决策：从 {@code fromWorkerId} 转交给 {@code toWorkerId}，承接同一句用户原话（question）。
     * {@code fromWorkerName} 留给调用方（持有 worker 表）回填；纯函数 {@link #matchHandoff} 拿不到。
     */
    public record HandoffDecision(Long toWorkerId, String toWorkerName, String taskName,
                                  Long fromWorkerId, String fromWorkerName, String question) {
    }

    /**
     * 会话内跨数字人转交判据（**唯一判定点**，纯函数、无 Spring 依赖、可单测）。
     *
     * <p><b>为什么有两级匹配</b>：库里任务名是**书面语**（如「费用报销申请」），用户说的是
     * **口语**（「我要报销差旅费」）。只做整词子串匹配时，后者永远匹配不上 —— 实测该场景
     * 不触发转交。故加一级「核心词重叠」弱匹配（Tier B），但加了四道闸防误跳：
     * 当前数字人也重叠则不转、必须唯一最高分、重叠片段不得是通用词、并列则放弃。</p>
     *
     * <p>规则：
     * <ol>
     *   <li>userText 为 null/blank 或 candidates 空/null → null（不转交）；</li>
     *   <li><b>Tier A（强匹配）</b>：候选 {@code taskName} 非空且长度>=2 且 userText 含 taskName，
     *       或 {@code taskCode} 非空且 userText 含 taskCode；</li>
     *   <li><b>当前数字人自己命中（A 或 B）→ 返回 null</b>（用户在当前职责内说话，最高优先级）；</li>
     *   <li><b>Tier A</b> 恰好命中一个其他 worker → 转交；命中 >=2 个（歧义）→ null；</li>
     *   <li>Tier A 一个都没命中时，才走 <b>Tier B</b>：把任务名剥掉通用词（申请/办理/助手…）得到核心词，
     *       与用户原话求「最长公共子串」；
     *       <ul>
     *         <li>片段长度 < 2、或片段本身是通用词 → 该候选不算命中；</li>
     *         <li>当前数字人的核心词也重叠 → 返回 null（不抢自己人的活）；</li>
     *         <li>取最高分：**唯一最高**才转交；并列（两个数字人一样像）→ null，宁可让模型按职责拒答；</li>
     *       </ul>
     *   </li>
     *   <li>question 即 userText（供前端展示原话）。</li>
     * </ol>
     */
    public static HandoffDecision matchHandoff(String userText, Long currentWorkerId,
                                               List<HandoffCandidate> candidates) {
        if (userText == null || userText.isBlank() || candidates == null || candidates.isEmpty()) {
            return null;
        }
        // ★ 无「当前数字人」⇒ 不转交。转交的语义是「从 A 换到 B」；会话没绑数字人时
        //   （典型是用户直接选了一位专家 AI，或走默认通用助手），命中任意一个数字人都
        //   不是「转交」而是「无端把专家会话劫持成某个数字人」——实测会让专家的领域
        //   问题突然弹出别人的业务表单。故此处硬闸：expert/无绑定会话一律不参与转交。
        if (currentWorkerId == null) {
            return null;
        }
        String u = userText.trim().toLowerCase(Locale.ROOT);

        // ---- Tier A：整词/码命中 ----
        boolean currentHit = false;
        java.util.Map<Long, HandoffCandidate> byWorker = new java.util.LinkedHashMap<>();
        for (HandoffCandidate c : candidates) {
            if (c.workerId() == null) {
                continue;
            }
            boolean hit = handoffHit(c, u);
            if (Objects.equals(c.workerId(), currentWorkerId)) {
                if (hit) {
                    currentHit = true;
                }
                continue; // 当前数字人永不作为转交目标
            }
            if (hit) {
                byWorker.put(c.workerId(), c);
            }
        }
        if (currentHit) {
            return null;
        }
        if (byWorker.size() == 1) {
            return decisionOf(byWorker.values().iterator().next(), currentWorkerId, userText);
        }
        if (byWorker.size() > 1) {
            return null; // 多个整词命中 ⇒ 歧义，不擅自换人
        }

        // ---- Tier B：核心词重叠（只在 Tier A 完全无命中时启用） ----
        int currentScore = 0;
        long bestScore = 0L;
        HandoffCandidate best = null;
        boolean tie = false;
        for (HandoffCandidate c : candidates) {
            if (c.workerId() == null) {
                continue;
            }
            String overlap = coreOverlap(u, c.taskName());
            int score = overlap.length();
            if (Objects.equals(c.workerId(), currentWorkerId)) {
                currentScore = Math.max(currentScore, score);
                continue;
            }
            if (score < 2) {
                continue;
            }
            if (score > bestScore) {
                bestScore = score;
                best = c;
                tie = false;
            } else if (score == bestScore) {
                tie = true; // 同分 ⇒ 无法判断像谁，放弃
            }
        }
        if (currentScore >= 2) {
            return null; // 当前数字人也能吃下这句话，不转交
        }
        if (best != null && !tie && bestScore >= 2) {
            return decisionOf(best, currentWorkerId, userText);
        }
        return null;
    }

    private static HandoffDecision decisionOf(HandoffCandidate target, Long currentWorkerId, String userText) {
        return new HandoffDecision(target.workerId(), target.workerName(), target.taskName(),
                currentWorkerId, null, userText);
    }

    /** 单候选命中判据（与 shouldOpenSingleForm 同口径：taskName 长度>=2 或 taskCode 命中）。 */
    private static boolean handoffHit(HandoffCandidate c, String u) {
        String tn = c.taskName() == null ? "" : c.taskName().trim().toLowerCase(Locale.ROOT);
        String tc = c.taskCode() == null ? "" : c.taskCode().trim().toLowerCase(Locale.ROOT);
        if (tn.length() >= 2 && u.contains(tn)) {
            return true;
        }
        return !tc.isEmpty() && u.contains(tc);
    }

    /**
     * 任务名里的**通用词**：单独重叠不代表任何业务归属，必须排除，否则「帮我办个申请」会乱跳。
     * 同时用于「剥尾」得到核心词（「费用报销申请」→「费用报销」）。
     */
    private static final java.util.Set<String> GENERIC_TASK_WORDS = java.util.Set.of(
            "申请", "办理", "审批", "流程", "助手", "数字人", "工作", "业务", "管理", "服务",
            "信息", "记录", "统计", "查询", "处理", "系统", "平台", "客服", "支持", "助手数字人",
            // ★ 2026-10-18 补：这些是「动作/载体」类尾缀，本身不含业务信息。缺了它们，
            //   Tier B 会靠两字后缀把任务判成「像」——实测 43 个数字人集体互转：
            //   「公文起草」↔「合同起草」重叠「起草」、「看板配置」→「门户布局配置」重叠「配置」，
            //   表单路由普查从 43 PASS 掉到 27 PASS。凡两字尾缀都不算业务重合。
            "配置", "起草", "设置", "填报", "登记", "录入", "借阅", "发起", "发布", "维护",
            "添加", "新建", "申诉", "报名", "上报", "下发", "提交", "生成", "导入", "导出");

    /** 剥掉结尾的通用词，得到任务核心词；剥完不足 2 字则原样返回（避免空串）。 */
    static String coreTaskName(String taskName) {
        if (taskName == null) {
            return "";
        }
        String t = taskName.trim().toLowerCase(Locale.ROOT);
        boolean changed = true;
        while (changed) {
            changed = false;
            for (String g : GENERIC_TASK_WORDS) {
                if (t.length() > g.length() && t.endsWith(g)) {
                    t = t.substring(0, t.length() - g.length());
                    changed = true;
                }
            }
        }
        return t.length() >= 2 ? t : taskName.trim().toLowerCase(Locale.ROOT);
    }

    /**
     * 用户原话与「任务核心词」的最长公共子串；片段本身是通用词（或长度<2）时返回空串。
     *
     * <p>用途仅限 Tier B 判「像不像」：如「我要报销差旅费」× 核心词「费用报销」⇒「报销」（2 字）。</p>
     */
    static String coreOverlap(String userTextLower, String taskName) {
        String core = coreTaskName(taskName);
        if (core.length() < 2 || userTextLower == null || userTextLower.length() < 2) {
            return "";
        }
        int bestLen = 0;
        int bestEnd = 0;
        int[] prev = new int[core.length() + 1];
        int[] cur = new int[core.length() + 1];
        for (int i = 1; i <= userTextLower.length(); i++) {
            char a = userTextLower.charAt(i - 1);
            for (int j = 1; j <= core.length(); j++) {
                if (a == core.charAt(j - 1)) {
                    cur[j] = prev[j - 1] + 1;
                    if (cur[j] > bestLen) {
                        bestLen = cur[j];
                        bestEnd = i;
                    }
                } else {
                    cur[j] = 0;
                }
            }
            int[] tmp = prev;
            prev = cur;
            cur = tmp;
            java.util.Arrays.fill(cur, 0);
        }
        if (bestLen < 2) {
            return "";
        }
        String fragment = userTextLower.substring(bestEnd - bestLen, bestEnd);
        return GENERIC_TASK_WORDS.contains(fragment) ? "" : fragment;
    }

    /**
     * 解析是否需要转交（同一会话内改绑数字人）。
     *
     * <p><b>当前数字人必须留在候选里</b>（2026-10-18 修）：{@link #matchHandoff} 的闸 #1 是
     * 「当前数字人自己也命中 ⇒ 不转」，这个判据要靠候选里的当前行才成立。此前这里
     * {@code continue} 排除了当前 worker ⇒ 闸 #1 结构上永不生效 ⇒ Tier B 把所有「带同一个
     * 尾缀」的任务都判成「像」，43 个数字人互转（公文起草↔合同起草、看板配置→门户布局配置），
     * 表单路由普查 43 PASS → 27 PASS。{@code matchHandoff} 内部本来就不会把当前 worker 当目标。
     *
     * <p>只取本租户启用中的数字人，按其 {@code worker_capability} 组装候选后
     * 调 {@link #matchHandoff}。整个解析包在 try/catch 内：任何异常都只记 warn 并返回 null，
     * <b>绝不打断对话主链</b>。无当前 worker / 无候选 / 命中 null 均返回 null。</p>
     */
    private HandoffDecision resolveHandoff(String text, ChatConversation conversation) {
        if (conversation == null || conversation.getWorkerId() == null) {
            return null;
        }
        try {
            Long tenantId = conversation.getTenantId();
            List<AgentWorker> workers = workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                    .eq(AgentWorker::getTenantId, tenantId)
                    .ne(AgentWorker::getEnabled, 0));
            List<Long> ids = new ArrayList<>();
            java.util.Map<Long, AgentWorker> workerById = new java.util.LinkedHashMap<>();
            for (AgentWorker w : workers) {
                ids.add(w.getId());
                workerById.put(w.getId(), w);
            }
            if (ids.isEmpty()) {
                return null;
            }
            List<WorkerCapability> caps = workerCapabilityService.listByWorkers(ids);
            List<HandoffCandidate> candidates = new ArrayList<>();
            for (WorkerCapability cap : caps) {
                AgentWorker w = workerById.get(cap.getWorkerId());
                if (w == null) {
                    continue;
                }
                candidates.add(new HandoffCandidate(cap.getWorkerId(), w.getName(),
                        cap.getTaskName(), cap.getTaskCode()));
            }
            return matchHandoff(text, conversation.getWorkerId(), candidates);
        } catch (Exception e) {
            log.warn("resolve handoff failed (no effect on conversation): {}", e.getMessage());
            return null;
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
