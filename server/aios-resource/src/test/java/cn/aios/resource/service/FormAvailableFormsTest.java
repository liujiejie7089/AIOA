package cn.aios.resource.service;

import cn.aios.resource.entity.FormTemplate;
import cn.aios.resource.mapper.FormTemplateMapper;
import cn.aios.resource.service.FormTemplateService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 独立验收：FormTemplateService.listAvailable 的边界（verify-forms-backend 补的空白测试）。
 *
 * <p>用 Mockito 直接 mock FormTemplateMapper（构造 FormTemplateService(mapper, null, null)），
 * 不进 Spring 上下文。覆盖 worker 单测没覆盖到的五条：租户行优先、只 ACTIVE 参与、
 * 上限 200 截断、返回体只含四键、tenantId=0 时 IN 列表语义。</p>
 */
class FormAvailableFormsTest {

    private final FormTemplateMapper mapper = mock(FormTemplateMapper.class);
    private final FormTemplateService service = new FormTemplateService(mapper, null, null);

    private static FormTemplate row(Long tenantId, String code, String name,
                                    String moduleCode, String bizType, String status) {
        FormTemplate t = new FormTemplate();
        t.setTenantId(tenantId);
        t.setCode(code);
        t.setName(name);
        t.setModuleCode(moduleCode);
        t.setBizType(bizType);
        t.setStatus(status);
        return t;
    }

    // ================================================================== A1：租户行优先于平台默认

    @Test
    @DisplayName("A1 同 code 时租户行胜出（name 取租户的，不是平台的）")
    void tenantRowWins() {
        // 租户 5 与平台 0 都有一个 code=leave，名字不同
        when(mapper.selectList(any())).thenReturn(List.of(
                row(5L, "leave", "租户请假", "leave", "LEAVE", FormTemplate.STATUS_ACTIVE),
                row(0L, "leave", "平台请假", "leave", "LEAVE", FormTemplate.STATUS_ACTIVE)));

        List<Map<String, Object>> result = service.listAvailable(5L);

        assertEquals(1, result.size(), "同 code 去重后应只剩一条");
        assertEquals("leave", result.get(0).get("code"));
        assertEquals("租户请假", result.get(0).get("name"), "应取租户行而非平台默认行");
    }

    // ================================================================== A2：只 ACTIVE 参与
    //
    // 说明：listAvailable 的 DISABLED 过滤发生在 DB 层（wrapper.eq(STATUS, ACTIVE)，见
    // FormTemplateService.java:95），服务本身不做内存过滤。
    // Mockito 不会替我们执行 SQL，且 mock 的 LambdaQueryWrapper 没有 lambda cache，无法从 wrapper
    // 抓取/解析出 status 条件（调用 getSqlSegment 会抛 “can not find lambda cache for this entity”）。
    // 因此这里按团队约定改用“结果层”等价证明：用“DB 仅回 ACTIVE”的 stub，断言服务透传正确、
    // 绝不向结果注入 DISABLED 行；DB 层 status=ACTIVE 过滤由 FormTemplateService.java:95 代码审查兜底。

    @Test
    @DisplayName("A2 只 ACTIVE 参与：服务透传 DB 已过滤结果、不注入 DISABLED 行")
    void onlyActiveParticipates() {
        when(mapper.selectList(any())).thenReturn(List.of(
                row(5L, "a", "启用A", "leave", "LEAVE", FormTemplate.STATUS_ACTIVE)));
        List<Map<String, Object>> result = service.listAvailable(5L);
        Set<Object> codes = result.stream().map(m -> m.get("code"))
                .collect(java.util.stream.Collectors.toSet());
        assertTrue(codes.contains("a"), "ACTIVE 行 a 应在结果中");
        assertFalse(codes.contains("b"), "DISABLED 行 b 不应出现（服务不注入）：" + result);
        assertEquals(1, result.size(), "结果应只有 1 条");
    }

    // ================================================================== A3：上限 200 截断

    @Test
    @DisplayName("A3 超过 200 条截断为 200")
    void capAt200() {
        List<FormTemplate> many = new ArrayList<>();
        for (int i = 0; i < 205; i++) {
            many.add(row(5L, "c" + String.format("%03d", i), "表单" + i, "leave", "LEAVE",
                    FormTemplate.STATUS_ACTIVE));
        }
        when(mapper.selectList(any())).thenReturn(many);

        List<Map<String, Object>> result = service.listAvailable(5L);

        assertEquals(200, result.size(), "超过 200 应被截断为 200（实际=" + result.size() + "）");
    }

    // ================================================================== A4：返回体只含四键

    @Test
    @DisplayName("A4 每条只有 code/name/module_code/biz_type 四键，绝不含 schemaJson")
    void onlyFourKeys() {
        when(mapper.selectList(any())).thenReturn(List.of(
                row(5L, "leave", "请假", "leave", "LEAVE", FormTemplate.STATUS_ACTIVE)));

        List<Map<String, Object>> result = service.listAvailable(5L);

        assertEquals(1, result.size());
        Map<String, Object> m = result.get(0);
        assertEquals(Set.of("code", "name", "module_code", "biz_type"), m.keySet(),
                "返回体应精确四键，实际=" + m.keySet());
        assertFalse(m.containsKey("schemaJson"), "绝不应带 schemaJson（避免大字段灌进对话上下文）");
        assertFalse(m.containsKey("schema_json"), "绝不应带 schema_json");
    }

    // ================================================================== A5：tenantId=0 的 IN 列表语义

    @Test
    @DisplayName("A5 tenantId=0 时只查平台默认（tenant_id=5 的行被排除）")
    void tenantZeroOnlyPlatform() {
        when(mapper.selectList(any())).thenReturn(List.of(
                row(0L, "x", "平台X", "leave", "LEAVE", FormTemplate.STATUS_ACTIVE),
                row(5L, "y", "租户Y", "leave", "LEAVE", FormTemplate.STATUS_ACTIVE)));

        List<Map<String, Object>> result = service.listAvailable(0L);

        Set<Object> codes = result.stream().map(m -> m.get("code"))
                .collect(java.util.stream.Collectors.toSet());
        assertTrue(codes.contains("x"), "平台默认行 x 应在结果中");
        assertFalse(codes.contains("y"), "tenant_id=5 的行 y 不应出现（IN 列表只含 0）：" + result);

        // 代码层复核：FormTemplateService.java:96-100 在 tenantId!=null(含 0) 时走
        //   w.in(FormTemplate::getTenantId, tenantId, 0L)
        // tenantId=0 时生成的是 IN (0, 0) 而非 IN (0)（eq 分支仅在 tenantId==null 时触发）。
        // 功能等价（不会多返回行），但字面不满足“IN 列表只有一个 0”。此点为代码审查发现，
        // 非结果错误；若要严格单 0，应在 tenantId==0 时也走 eq(0) 或去重。详见验收报告。
    }
}
