package cn.aioa.chat.service;

import cn.aioa.resource.service.FormTemplateService;
import cn.aioa.resource.service.WorkerCapabilityService;
import cn.aioa.security.AuthUser;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「第 7 项能力自检」与「formCode → formFields 同源填充」的定点验收。
 *
 * <p>不启动 Spring 上下文：{@link WorkerIntakeService} 用构造器注入，本类直接 new 并传入 Mockito 替身，
 * 只验证这两段逻辑本身（不触发其余 ①~⑥ 检查的依赖）。</p>
 */
class WorkerIntakeDeclaredCapabilityTest {

    private static final long TENANT = 1L;

    private WorkerIntakeService newService(WorkerCapabilityService caps, FormTemplateService forms) {
        // 构造参数顺序：objectMapper, toolGatewayService, approvalFlowService, billingService,
        // kbService, leaveService, permissionGrantService, departmentMapper, memberMapper,
        // formTemplateService, workerCapabilityService, serviceTokenProvider
        // 末位令牌传 null：本类只调 checkDeclaredCapabilities()，不触达 HTTP（intent 才用令牌）。
        return new WorkerIntakeService(
                new ObjectMapper(), null, null, null, null, null, null, null, null, forms, caps, null);
    }

    private static AuthUser user() {
        AuthUser u = Mockito.mock(AuthUser.class);
        Mockito.when(u.getTenantId()).thenReturn(TENANT);
        return u;
    }

    private static Map<String, Object> bodyWith(List<?> capabilities) {
        return Map.of("text", "创建一个请假数字人", "capabilities", capabilities);
    }

    // ----------------------------------------------------------------- 第 7 项：声明的能力自检

    @Test
    @DisplayName("未声明能力（空列表）→ PASS，且提示可稍后配置")
    void noDeclaredCapability_passes() {
        WorkerCapabilityService caps = Mockito.mock(WorkerCapabilityService.class);
        WorkerIntakeService svc = newService(caps, null);
        Map<String, Object> r = svc.checkDeclaredCapabilities(user(), bodyWith(List.of()));
        assertEquals("PASS", r.get("status"), String.valueOf(r));
        assertTrue(r.get("message").toString().contains("未声明能力"), String.valueOf(r));
    }

    @Test
    @DisplayName("未声明能力（缺 capabilities 字段）→ PASS")
    void missingCapabilitiesField_passes() {
        WorkerCapabilityService caps = Mockito.mock(WorkerCapabilityService.class);
        WorkerIntakeService svc = newService(caps, null);
        Map<String, Object> r = svc.checkDeclaredCapabilities(user(), Map.of("text", "x"));
        assertEquals("PASS", r.get("status"), String.valueOf(r));
    }

    @Test
    @DisplayName("合法能力（依赖全就绪）→ PASS")
    void validCapability_passes() {
        WorkerCapabilityService caps = Mockito.mock(WorkerCapabilityService.class);
        Mockito.when(caps.checkCapabilities(Mockito.eq(TENANT), Mockito.anyList())).thenReturn(List.of());
        WorkerIntakeService svc = newService(caps, null);
        Map<String, Object> r = svc.checkDeclaredCapabilities(user(), bodyWith(List.of(
                Map.of("formCode", "leave_request", "toolNames", List.of(), "approvalBizType", ""))));
        assertEquals("PASS", r.get("status"), String.valueOf(r));
    }

    @Test
    @DisplayName("form_code 不存在 → BLOCKED，且 message 含该表单码")
    void missingFormCode_blocks_and_contains_code() {
        WorkerCapabilityService caps = Mockito.mock(WorkerCapabilityService.class);
        Mockito.when(caps.checkCapabilities(Mockito.eq(TENANT), Mockito.anyList()))
                .thenReturn(List.of("表单码「ghost_form」不存在或未启用"));
        WorkerIntakeService svc = newService(caps, null);
        Map<String, Object> r = svc.checkDeclaredCapabilities(user(), bodyWith(List.of(
                Map.of("formCode", "ghost_form", "toolNames", List.of()))));
        assertEquals("BLOCKED", r.get("status"), String.valueOf(r));
        assertTrue(r.get("message").toString().contains("ghost_form"), String.valueOf(r));
    }

    @Test
    @DisplayName("工具未注册 → BLOCKED，且 message 含该工具名")
    void unregisteredTool_blocks_and_contains_name() {
        WorkerCapabilityService caps = Mockito.mock(WorkerCapabilityService.class);
        Mockito.when(caps.checkCapabilities(Mockito.eq(TENANT), Mockito.anyList()))
                .thenReturn(List.of("工具「nonexistent_tool」未注册（form_code=leave_request）"));
        WorkerIntakeService svc = newService(caps, null);
        Map<String, Object> r = svc.checkDeclaredCapabilities(user(), bodyWith(List.of(
                Map.of("formCode", "leave_request", "toolNames", List.of("nonexistent_tool")))));
        assertEquals("BLOCKED", r.get("status"), String.valueOf(r));
        assertTrue(r.get("message").toString().contains("nonexistent_tool"), String.valueOf(r));
    }

    // ----------------------------------------------------------------- 表单字段同源填充（话术与事实同源）

    @Test
    @DisplayName("formCode 命中 → 按表单库标签填充 formFields（顺序与 schema 一致）")
    void resolveFormFields_returns_labels_when_template_present() {
        FormTemplateService forms = Mockito.mock(FormTemplateService.class);
        FormTemplateService.FormRender render = Mockito.mock(FormTemplateService.FormRender.class);
        FormTemplateService.FormField f1 = Mockito.mock(FormTemplateService.FormField.class);
        FormTemplateService.FormField f2 = Mockito.mock(FormTemplateService.FormField.class);
        Mockito.when(f1.label()).thenReturn("假种");
        Mockito.when(f1.name()).thenReturn("leave_type");
        Mockito.when(f2.label()).thenReturn("起止时间");
        Mockito.when(f2.name()).thenReturn("range");
        Mockito.when(render.fields()).thenReturn(List.of(f1, f2));
        Mockito.when(forms.resolveForRender(TENANT, "leave_request")).thenReturn(render);

        WorkerIntakeService svc = newService(null, forms);
        List<String> fields = svc.resolveFormFields(user(), "leave_request");
        assertEquals(List.of("假种", "起止时间"), fields, String.valueOf(fields));
    }

    @Test
    @DisplayName("表单定义缺失 → 降级为空数组、不抛异常（调试/降级路径安全）")
    void resolveFormFields_degrades_to_empty_on_missing_template() {
        FormTemplateService forms = Mockito.mock(FormTemplateService.class);
        Mockito.when(forms.resolveForRender(TENANT, "ghost_form"))
                .thenThrow(new RuntimeException("表单不存在或未启用：ghost_form"));

        WorkerIntakeService svc = newService(null, forms);
        List<String> fields = svc.resolveFormFields(user(), "ghost_form");
        assertEquals(List.of(), fields, "取不到定义必须降级为空数组，绝不让意图接口失败");
    }
}
