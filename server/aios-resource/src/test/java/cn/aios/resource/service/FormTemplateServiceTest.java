package cn.aios.resource.service;

import cn.aios.org.entity.LeaveType;
import cn.aios.org.service.LeaveService;
import cn.aios.resource.entity.FormTemplate;
import cn.aios.resource.entity.FormTemplateVersion;
import cn.aios.resource.mapper.FormTemplateMapper;
import cn.aios.resource.mapper.FormTemplateVersionMapper;
import cn.aios.resource.service.FormTemplateService.FormSave;
import cn.aios.security.AuthUser;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * FormTemplateService 单测（docs/52 P1，纯单测、不起 Spring）。
 *
 * <p>锁死两类容易静默走偏的行为：
 * <ol>
 *   <li><b>更新自动升版</b>：改定义后 version+1，且<b>旧版本快照仍可查</b>（写的是新版本行，
 *       绝不覆盖旧版本）—— 用 mock mapper 断言 insert 的 version 与查询行为。</li>
 *   <li><b>平台默认回退</b>：租户没有该表单时回落 tenant_id=0。</li>
 * </ol>
 */
class FormTemplateServiceTest {

    private final FormTemplateMapper templateMapper = mock(FormTemplateMapper.class);
    private final FormTemplateVersionMapper versionMapper = mock(FormTemplateVersionMapper.class);
    private final LeaveService leaveService = mock(LeaveService.class);

    private final FormTemplateService service =
            new FormTemplateService(templateMapper, versionMapper, leaveService);

    private static final String VALID_SCHEMA =
            "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"text\",\"label\":\"姓名\"}}}";

    private static AuthUser user(Long tenantId) {
        return AuthUser.builder().tenantId(tenantId).userId(1L).build();
    }

    private static FormSave save(String code) {
        return new FormSave(code, "请假申请", "leave", "LEAVE",
                VALID_SCHEMA, null, "APPROVAL", null);
    }

    private static FormTemplate existing(Long id, Long tenantId, String code, int version) {
        FormTemplate t = new FormTemplate();
        t.setId(id);
        t.setTenantId(tenantId);
        t.setCode(code);
        t.setName("请假申请");
        t.setModuleCode("leave");
        t.setBizType("LEAVE");
        t.setSchemaJson(VALID_SCHEMA);
        t.setSubmitPolicy("APPROVAL");
        t.setStatus(FormTemplate.STATUS_ACTIVE);
        t.setVersion(version);
        return t;
    }

    @Test
    @DisplayName("更新定义 → version+1，并写入「新版本」快照（旧版本不覆盖、仍可查）")
    void updateBumpsVersionAndSnapshots() {
        FormTemplate old = existing(10L, 5L, "leave", 3);
        when(templateMapper.selectOne(any())).thenReturn(old);

        FormTemplate updated = service.update(user(5L), "leave", save("leave"));

        // 实体版本 +1
        assertEquals(4, updated.getVersion(), "更新后版本应 +1");
        // updateById 写入新版本
        verify(templateMapper, times(1)).updateById(any(FormTemplate.class));
        // 关键：插入的是「新版本=4」快照，而不是改写旧版本=3 —— 旧版本因此仍可查
        verify(versionMapper, times(1)).insert(any(FormTemplateVersion.class));
        FormTemplateVersion inserted = captureInserted();
        assertNotNull(inserted, "应插入版本快照");
        assertEquals(10L, inserted.getTemplateId());
        assertEquals(4, inserted.getVersion(), "快照版本应为新版本 4，不得覆盖旧版本 3");
    }

    @Test
    @DisplayName("本租户无该表单 → 回退平台默认（tenant_id=0）")
    void fallsBackToPlatformDefault() {
        FormTemplate platform = existing(99L, 0L, "leave", 2);
        // 第一次查询（租户 5）返回 null，第二次（租户 0）返回平台默认
        when(templateMapper.selectOne(any())).thenReturn(null).thenReturn(platform);

        FormTemplate got = service.getByCode(5L, "leave");

        assertNotNull(got, "应回退到平台默认");
        assertEquals(0L, got.getTenantId());
        assertEquals(99L, got.getId());
    }

    @Test
    @DisplayName("本租户无、平台也无 → 返回 null（提交时应报未启用）")
    void noTemplateAnywhere() {
        when(templateMapper.selectOne(any())).thenReturn(null);
        assertNull(service.getByCode(5L, "nope"), "无处可回落应返回 null");
    }

    @Test
    @DisplayName("更新不存在的表单 → 抛 notFound（不静默建一份）")
    void updateMissingThrows() {
        when(templateMapper.selectOne(any())).thenReturn(null);
        assertThrows(RuntimeException.class,
                () -> service.update(user(5L), "ghost", save("ghost")));
    }

    @Test
    @DisplayName("resolveForRender 解析 x-options-ref=leave_types → 内联 options")
    void resolveLeaveTypesRef() {
        when(templateMapper.selectOne(any())).thenReturn(existing(10L, 5L, "leave", 1));
        LeaveType lt = new LeaveType();
        lt.setCode("sick");
        lt.setName("病假");
        when(leaveService.listTypes(5L)).thenReturn(List.of(lt));
        String schema = "{\"type\":\"object\",\"properties\":{\"leaveType\":{\"type\":\"select\""
                + ",\"label\":\"假种\",\"x-options-ref\":\"leave_types\"}}}";
        FormTemplate t = existing(10L, 5L, "leave", 1);
        t.setSchemaJson(schema);
        when(templateMapper.selectOne(any())).thenReturn(t);

        FormTemplateService.FormRender render = service.resolveForRender(5L, "leave");

        assertEquals(1, render.fields().size());
        assertEquals("leaveType", render.fields().get(0).name());
        assertEquals(List.of(Map.of("value", "sick", "label", "病假")),
                render.fields().get(0).options(), "leave_types 应被解析内联成 options");
    }

    @Test
    @DisplayName("resolveForRender 遇到未知 x-options-ref → 报错（不返回空 options）")
    void resolveUnknownRefThrows() {
        String schema = "{\"type\":\"object\",\"properties\":{\"x\":{\"type\":\"select\""
                + ",\"x-options-ref\":\"unknown_ref\"}}}";
        FormTemplate t = existing(10L, 5L, "leave", 1);
        t.setSchemaJson(schema);
        when(templateMapper.selectOne(any())).thenReturn(t);
        assertThrows(RuntimeException.class, () -> service.resolveForRender(5L, "leave"));
    }

    @SuppressWarnings("unchecked")
    private FormTemplateVersion captureInserted() {
        var captor = org.mockito.ArgumentCaptor.forClass(FormTemplateVersion.class);
        verify(versionMapper).insert(captor.capture());
        return captor.getValue();
    }
}
