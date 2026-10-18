package cn.aioa.chat.service;

import cn.aioa.chat.config.AgentProperties;
import cn.aioa.chat.mapper.AgentRunMapper;
import cn.aioa.chat.mapper.ChatConversationMapper;
import cn.aioa.chat.mapper.ChatMessageMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.project.port.PmAiScopePort;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.SysFileMapper;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.resource.service.BillingService;
import cn.aioa.resource.service.ExpertConfigService;
import cn.aioa.resource.service.FormTemplateService;
import cn.aioa.resource.service.KbFileParser;
import cn.aioa.resource.service.WorkerCapabilityService;
import cn.aioa.security.ServiceTokenProvider;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ScheduledExecutorService;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * need_form 帧的 Java 侧契约（docs/52 P2）。
 *
 * <p>为什么单独一枚：`buildNeedFormPayload` 是「Python 只发 form_code，字段标签必须由
 * **表单库**补全」的唯一落点。它一旦回归，前端卡片就会退化成「一个空壳 + 英文键名」，
 * 而这种退化**不会报错**（照样 200、照样渲染），只能靠断言字段来源与按钮文案抓到。</p>
 *
 * <p>钉死四条：</p>
 * <ol>
 *   <li>fields 来自 {@link FormTemplateService#resolveForRender}，**不是** agent 帧里带的；</li>
 *   <li>submit_label 是**中文按钮文案**（"提交"/"提交审批"），不是策略串 LEDGER/APPROVAL+RESUME
 *       —— 2026-10-17 实测确实显示成了 "APPROVAL+RESUME"；</li>
 *   <li>定义查不到 → 带 error 且**不挂起**（needFormHasError=true，completeRun 才会收尾而不是挂死）；</li>
 *   <li>缺 form_code / 坏 JSON → 同样是带 error 的帧，不抛异常、不挂起。</li>
 * </ol>
 */
class RunServiceFormFrameTest {

    private RunService runService;
    private FormTemplateService formTemplateService;
    private WorkerCapabilityService workerCapabilityService;
    private final ObjectMapper mapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        formTemplateService = mock(FormTemplateService.class);
        workerCapabilityService = mock(WorkerCapabilityService.class);
        runService = new RunService(
                mock(ChatConversationMapper.class), mock(ChatMessageMapper.class), mock(AgentRunMapper.class),
                mock(WebClient.class), mock(ServiceTokenProvider.class), mapper,
                mock(ScheduledExecutorService.class), mock(AgentProperties.class),
                mock(BillingService.class), mock(ActivityLogService.class), mock(ContentGuardService.class),
                mock(AgentWorkerMapper.class),
                mock(ExpertConfigService.class), mock(AiExpertMapper.class), formTemplateService,
                workerCapabilityService,
                mock(PmAiScopePort.class), mock(SysFileMapper.class), mock(KbFileParser.class),
                mock(ConversationService.class));
    }

    private String build(String rawFrame, Long tenantId) throws Exception {
        Method m = RunService.class.getDeclaredMethod("buildNeedFormPayload",
                String.class, Long.class, Long.class, String.class);
        m.setAccessible(true);
        return (String) m.invoke(runService, rawFrame, tenantId, 42L, "请假助手");
    }

    private boolean hasError(String payload) throws Exception {
        Method m = RunService.class.getDeclaredMethod("needFormHasError", String.class);
        m.setAccessible(true);
        return (Boolean) m.invoke(runService, payload);
    }

    private FormTemplateService.FormRender render(String code, String name, String policy) {
        List<FormTemplateService.FormField> fields = List.of(
                new FormTemplateService.FormField("leave_type", "假种", "select", true,
                        List.of(Map.of("label", "年休假", "value", "ANNUAL")), null, null, null),
                new FormTemplateService.FormField("days", "请假天数", "number", true,
                        List.of(), null, null, null));
        return new FormTemplateService.FormRender(1L, code, name, 1, "leave", policy, fields);
    }

    @Test
    @DisplayName("T1 字段来自表单库（不是 agent 帧）+ 按钮文案为中文")
    void fieldsComeFromFormLibraryAndLabelIsChinese() throws Exception {
        when(formTemplateService.resolveForRender(anyLong(), eq("leave_request")))
                .thenReturn(render("leave_request", "请假助手", "APPROVAL+RESUME"));

        String payload = build("{\"form_code\":\"leave_request\",\"reason\":\"请补充请假信息\","
                + "\"fields\":[{\"name\":\"HACKED\",\"label\":\"伪造字段\"}]}", 3L);
        Map<?, ?> m = mapper.readValue(payload, Map.class);

        assertEquals("leave_request", m.get("form_code"));
        assertEquals("请假助手", m.get("title"));
        assertEquals(1, m.get("version"));

        List<?> fields = (List<?>) m.get("fields");
        assertNotNull(fields);
        assertEquals(2, fields.size(), "字段必须来自表单库，不能沿用帧里伪造的那 1 个");
        Map<?, ?> first = (Map<?, ?>) fields.get(0);
        assertEquals("leave_type", first.get("name"));
        assertEquals("假种", first.get("label"), "标签必须取自库，不能是英文键名");

        assertEquals("提交审批", m.get("submit_label"),
                "submit_label 是按钮文案；曾把 submitPolicy 塞进来，按钮显示「APPROVAL+RESUME」");

        Map<?, ?> origin = (Map<?, ?>) m.get("origin");
        assertEquals("请假助手", origin.get("worker_name"));
        assertEquals(42, origin.get("worker_id"));
        assertEquals("请补充请假信息", m.get("reason"));
        assertFalse(hasError(payload), "正常帧不能带 error（否则 run 不会被挂起）");
    }

    @Test
    @DisplayName("T2 LEDGER 表单的按钮文案是「提交」")
    void ledgerLabelIsPlainSubmit() throws Exception {
        when(formTemplateService.resolveForRender(anyLong(), eq("worklog_submit")))
                .thenReturn(render("worklog_submit", "工作日志", "LEDGER"));
        Map<?, ?> m = mapper.readValue(build("{\"form_code\":\"worklog_submit\"}", 3L), Map.class);
        assertEquals("提交", m.get("submit_label"));
    }

    @Test
    @DisplayName("T3 表单定义查不到 → 带 error 且不挂起")
    void missingTemplateYieldsErrorFrameAndDoesNotPause() throws Exception {
        when(formTemplateService.resolveForRender(anyLong(), eq("no_such_form")))
                .thenThrow(BizException.notFound("表单不存在或未启用：no_such_form"));

        String payload = build("{\"form_code\":\"no_such_form\",\"reason\":\"补充信息\"}", 3L);
        Map<?, ?> m = mapper.readValue(payload, Map.class);
        assertNotNull(m.get("error"), "查不到定义必须给 error，前端要能提示");
        assertEquals("no_such_form", m.get("form_code"));
        assertEquals("补充信息", m.get("reason"), "原帧 reason 要透传，便于前端说明为什么弹不出来");
        assertTrue(hasError(payload), "带 error 的帧不得被当作暂停帧（否则 run 永久挂起）");
    }

    @Test
    @DisplayName("T4 缺 form_code / 坏 JSON → 都是带 error 的帧，不抛异常")
    void malformedFramesNeverThrow() throws Exception {
        String noCode = build("{\"reason\":\"x\"}", 3L);
        assertTrue(hasError(noCode), "缺 form_code 必须走 error 帧");
        assertNull(mapper.readValue(noCode, Map.class).get("form_code"));

        String broken = build("not-json", 3L);
        assertTrue(hasError(broken), "坏 JSON 必须走 error 帧");
    }

    @Test
    @DisplayName("T5 租户参数原样传给表单库（多租户表单不能串）")
    void tenantIdIsForwarded() throws Exception {
        when(formTemplateService.resolveForRender(eq(77L), any(String.class)))
                .thenReturn(render("leave_request", "请假助手(租户77)", "APPROVAL+RESUME"));
        Map<?, ?> m = mapper.readValue(build("{\"form_code\":\"leave_request\"}", 77L), Map.class);
        assertEquals("请假助手(租户77)", m.get("title"));
        org.mockito.Mockito.verify(formTemplateService).resolveForRender(eq(77L), eq("leave_request"));
    }

    // ==================================================================================
    // 数字人表单越权拦截（2026-10-18）
    //
    // 真实缺陷：`worker_capability` 每个数字人绑 1 张表，但 RunService 下发 available_forms
    // 时只按租户过滤（43 张全给），出口也不校验 ⇒ 实测「用车助手问报销 → 弹 expense_form」
    // 「会议助手问出差 → 弹 travel_form / leave_request」。
    // 修法两道闸：① 下发面按能力收窄（narrowFormsByWorker）② 出口按能力校验（buildNeedFormPayload）。
    // 下面两枚钉死第②道，且必须有负向对照 —— 否则「全拦」也能让 T6 变绿。
    // ==================================================================================

    private String buildWithWorker(String rawFrame, Long tenantId, Long workerId) throws Exception {
        Method m = RunService.class.getDeclaredMethod("buildNeedFormPayload",
                String.class, Long.class, Long.class, String.class);
        m.setAccessible(true);
        return (String) m.invoke(runService, rawFrame, tenantId, workerId, "会议助手");
    }

    private cn.aioa.resource.entity.WorkerCapability cap(String formCode) {
        cn.aioa.resource.entity.WorkerCapability c = new cn.aioa.resource.entity.WorkerCapability();
        c.setWorkerId(7L);
        c.setFormCode(formCode);
        c.setEnabled(1);
        return c;
    }

    @Test
    @DisplayName("T6 出口拦截：数字人只办 meeting_book，模型产出 leave_request 必须被拒（不得渲染别人的表）")
    void foreignFormIsRejectedAtTheExitGate() throws Exception {
        when(workerCapabilityService.listByWorker(7L)).thenReturn(List.of(cap("meeting_book")));
        // 故意让表单库能查到 leave_request —— 证明拦截来自**能力闸**，
        // 而不是「正好查不到这张表」（否则判据可能因为别的原因变绿）
        when(formTemplateService.resolveForRender(anyLong(), eq("leave_request")))
                .thenReturn(render("leave_request", "请假助手", "APPROVAL+RESUME"));

        String payload = buildWithWorker("{\"form_code\":\"leave_request\",\"reason\":\"申请出差\"}", 3L, 7L);
        Map<?, ?> m = mapper.readValue(payload, Map.class);

        assertTrue(hasError(payload), "越权表单必须被拦成 error 帧，不能渲染");
        assertNull(m.get("fields"), "被拦的帧不得带 fields（带了前端就会渲染出一张表）");
        String err = String.valueOf(m.get("error"));
        assertTrue(err.contains("leave_request"), "错误信息要指出被拦的 code，便于定位：" + err);
        assertEquals("申请出差", m.get("reason"), "原帧 reason 要透传");
        // 拦截必须发生在查库**之前**：调用了 resolveForRender 就说明闸门位置错了
        org.mockito.Mockito.verify(formTemplateService, org.mockito.Mockito.never())
                .resolveForRender(anyLong(), eq("leave_request"));
    }

    @Test
    @DisplayName("T6b 负向对照：数字人没有配置能力时不得拦截（历史 GENERAL 数字人不受影响）")
    void noCapabilityMeansNoRestriction() throws Exception {
        when(workerCapabilityService.listByWorker(7L)).thenReturn(List.of());
        when(formTemplateService.resolveForRender(anyLong(), eq("leave_request")))
                .thenReturn(render("leave_request", "请假助手", "APPROVAL+RESUME"));

        String payload = buildWithWorker("{\"form_code\":\"leave_request\"}", 3L, 7L);
        Map<?, ?> m = mapper.readValue(payload, Map.class);
        assertEquals("请假助手", m.get("title"), "未配置能力 ⇒ 不限制，照常渲染");
        assertFalse(hasError(payload), "不得凭空报错");
    }

    @Test
    @DisplayName("T6c 同域放行：能力内的表单必须照常渲染（拦截不能误伤自己那张）")
    void ownFormStillRenders() throws Exception {
        when(workerCapabilityService.listByWorker(7L)).thenReturn(List.of(cap("meeting_book")));
        when(formTemplateService.resolveForRender(anyLong(), eq("meeting_book")))
                .thenReturn(render("meeting_book", "会议助手", "LEDGER"));

        String payload = buildWithWorker("{\"form_code\":\"meeting_book\"}", 3L, 7L);
        Map<?, ?> m = mapper.readValue(payload, Map.class);
        assertEquals("会议助手", m.get("title"));
        assertNotNull(m.get("fields"));
        assertFalse(hasError(payload), "自己那张表必须能渲染");
    }

    // ==================================================================================
    // 第三道闸：单表单数字人的确定性开表判据（shouldOpenSingleForm，纯函数、无模型）
    // 这是把「模型不调工具、只在正文回澄清」改成「Java 收口时补发 need_form」的判定核心，
    // 必须可单测、且含负向对照（点名别的事 → 不开表，这条最关键）。
    // ==================================================================================

    @Test
    @DisplayName("G1 点名任务 ⇒ true（帮我办理工会事项办理 / 工会事项办理 / union_affairs）")
    void pointAtTaskOpensForm() {
        assertTrue(RunService.shouldOpenSingleForm(
                "帮我办理工会事项办理", "工会事项办理", "union_affairs"));
    }

    @Test
    @DisplayName("G2 问候不误触发（userText=你好）")
    void greetingDoesNotOpenForm() {
        assertFalse(RunService.shouldOpenSingleForm(
                "你好", "工会事项办理", "union_affairs"));
    }

    @Test
    @DisplayName("G3 负向对照：点名别的事 ⇒ false（这一条最关键）")
    void pointAtOtherTaskDoesNotOpenForm() {
        assertFalse(RunService.shouldOpenSingleForm(
                "帮我办理公文办理", "工会事项办理", "union_affairs"));
    }

    @Test
    @DisplayName("G4 code 命中且大小写不敏感（taskName 空 / PUB_DOC / pub_doc 怎么走）")
    void codeMatchCaseInsensitive() {
        assertTrue(RunService.shouldOpenSingleForm(
                "pub_doc 怎么走", "", "PUB_DOC"));
    }

    @Test
    @DisplayName("G5 单字任务名不参与匹配（taskName=工 / 人工处理）")
    void singleCharTaskNameIgnored() {
        assertFalse(RunService.shouldOpenSingleForm(
                "人工处理", "工", null));
    }

    @Test
    @DisplayName("G6 userText 为 null ⇒ false")
    void nullUserTextIsFalse() {
        assertFalse(RunService.shouldOpenSingleForm(
                null, "工会事项办理", "union_affairs"));
    }
}
