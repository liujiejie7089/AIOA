package cn.aios.resource.service;

import cn.aios.org.entity.ApprovalFlowDef;
import cn.aios.resource.entity.FormTemplate;
import cn.aios.resource.entity.WorkerCapability;
import cn.aios.resource.mapper.WorkerCapabilityMapper;
import cn.aios.resource.service.WorkerCapabilityService.CapabilityReq;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * WorkerCapabilityService.checkCapabilities 单测（docs/52 P3，纯单测、不起 Spring）。
 *
 * <p>这段是「第 7 项能力自检」的判定内核：form_code 必须存在且 ACTIVE、工具必须已注册、
 * approval_biz_type 非空时必须存在 ACTIVE 审批流。四条用例都能因缺陷变红——
 * 改坏任一分支都会让对应断言失败，而不是静默放过。</p>
 */
class WorkerCapabilityServiceTest {

    private final WorkerCapabilityMapper capabilityMapper = mock(WorkerCapabilityMapper.class);
    private final FormTemplateService templateService = mock(FormTemplateService.class);
    private final ToolGatewayService toolGatewayService = mock(ToolGatewayService.class);
    private final cn.aios.org.mapper.ApprovalFlowDefMapper approvalFlowDefMapper =
            mock(cn.aios.org.mapper.ApprovalFlowDefMapper.class);

    private final WorkerCapabilityService service =
            new WorkerCapabilityService(capabilityMapper, templateService, toolGatewayService, approvalFlowDefMapper);

    private static final long TENANT = 1L;

    private void givenToolRegistered(String name) {
        when(toolGatewayService.listTools()).thenReturn(List.of(
                Map.of("function", Map.of("name", name))));
    }

    private void givenFormExists(String code) {
        when(templateService.getByCode(TENANT, code)).thenReturn(mock(FormTemplate.class));
    }

    private void givenFormMissing(String code) {
        when(templateService.getByCode(TENANT, code)).thenReturn(null);
    }

    private void givenApprovalFlowActive(String biz) {
        when(approvalFlowDefMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);
    }

    @Test
    @DisplayName("未声明能力（空列表）→ 无原因（等价 PASS）")
    void emptyRequest_has_no_reasons() {
        List<String> reasons = service.checkCapabilities(TENANT, List.of());
        assertTrue(reasons.isEmpty(), String.valueOf(reasons));
    }

    @Test
    @DisplayName("合法能力：表单存在 + 工具已注册 + 无审批流 → 无原因")
    void validCapability_has_no_reasons() {
        givenFormExists("leave_request");
        givenToolRegistered("search_kb_documents");
        List<CapabilityReq> reqs = List.of(
                new CapabilityReq("leave_request", List.of("search_kb_documents"), null));
        List<String> reasons = service.checkCapabilities(TENANT, reqs);
        assertTrue(reasons.isEmpty(), String.valueOf(reasons));
    }

    @Test
    @DisplayName("form_code 不存在 → 原因含该表单码")
    void missingFormCode_reports_code() {
        givenFormMissing("ghost_form");
        List<CapabilityReq> reqs = List.of(new CapabilityReq("ghost_form", List.of(), null));
        List<String> reasons = service.checkCapabilities(TENANT, reqs);
        assertFalse(reasons.isEmpty(), "必须报告缺失的表单码");
        assertTrue(reasons.get(0).contains("ghost_form"), String.valueOf(reasons));
    }

    @Test
    @DisplayName("工具未注册 → 原因含该工具名")
    void unregisteredTool_reports_name() {
        givenFormExists("leave_request");
        givenToolRegistered("search_kb_documents"); // 不包含下面的幽灵工具
        List<CapabilityReq> reqs = List.of(
                new CapabilityReq("leave_request", List.of("ghost_tool"), null));
        List<String> reasons = service.checkCapabilities(TENANT, reqs);
        assertFalse(reasons.isEmpty(), "必须报告未注册的工具");
        assertTrue(reasons.get(0).contains("ghost_tool"), String.valueOf(reasons));
    }

    @Test
    @DisplayName("审批流 bizType 非空但无 ACTIVE 定义 → 原因含该 bizType")
    void missingApprovalFlow_reports_biz() {
        givenFormExists("leave_request");
        givenToolRegistered("search_kb_documents");
        when(approvalFlowDefMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        List<CapabilityReq> reqs = List.of(
                new CapabilityReq("leave_request", List.of("search_kb_documents"), "approval:leave"));
        List<String> reasons = service.checkCapabilities(TENANT, reqs);
        assertFalse(reasons.isEmpty(), "必须报告缺失的审批流");
        assertTrue(reasons.get(0).contains("approval:leave"), String.valueOf(reasons));
    }
}
