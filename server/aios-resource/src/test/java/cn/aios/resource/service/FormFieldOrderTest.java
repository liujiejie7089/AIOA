package cn.aios.resource.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 表单字段渲染顺序（2026-11-06）。
 *
 * <p>回归的是这条真实缺陷：MySQL 的 {@code JSON} 列会**重排对象键**（实测按 key 长度升序、
 * 再字典序），所以 {@code schema_json} 里 properties 的键顺序落库后与开发者写下的顺序无关。
 * 直接按 properties 顺序渲染的后果：请假表在 H5 上显示成
 * 「请假天数 → 证明材料 → 请假事由 → 结束日期 → 假种 → 开始日期」，用户填不下去。</p>
 *
 * <p>{@code required} 是数组，不受重排影响，而种子脚本里它的顺序就是业务顺序 ⇒ 以它为业务前序。</p>
 */
class FormFieldOrderTest {

    private static Map<String, Object> props(String... names) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (String n : names) {
            Map<String, Object> def = new LinkedHashMap<>();
            def.put("type", "string");
            def.put("title", n);
            m.put(n, def);
        }
        return m;
    }

    private static List<String> names(List<Map.Entry<String, Object>> ordered) {
        List<String> out = new ArrayList<>();
        for (Map.Entry<String, Object> e : ordered) {
            out.add(e.getKey());
        }
        return out;
    }

    @Test
    @DisplayName("required 顺序优先：properties 乱序（MySQL 键重排形状）也能得到业务顺序")
    void requiredOrderWins() {
        // 这就是 MySQL 落库后的实际形状：按 key 长度升序、同长按字典序
        Map<String, Object> p = props("days", "proof", "reason", "end_date", "leave_type", "start_date");
        List<String> req = List.of("leave_type", "start_date", "end_date", "days", "reason");

        assertEquals(
                List.of("leave_type", "start_date", "end_date", "days", "reason", "proof"),
                names(FormTemplateService.orderFieldEntries(p, req)));
    }

    @Test
    @DisplayName("非必填字段排在必填之后，并保持 properties 原顺序")
    void optionalFieldsFollowStableOrder() {
        Map<String, Object> p = props("attach_b", "attach_a", "name");
        List<String> req = List.of("name");

        assertEquals(List.of("name", "attach_b", "attach_a"),
                names(FormTemplateService.orderFieldEntries(p, req)));
    }

    @Test
    @DisplayName("required 里的脏键（properties 不存在）不得被造出来")
    void unknownRequiredKeysAreSkipped() {
        Map<String, Object> p = props("b", "a");
        List<String> req = List.of("ghost", "b");

        List<Map.Entry<String, Object>> out = FormTemplateService.orderFieldEntries(p, req);
        assertEquals(List.of("b", "a"), names(out));
        assertEquals(2, out.size());
    }

    @Test
    @DisplayName("没有 required（纯 LEDGER 表单）时保持 properties 原顺序，不重排")
    void noRequiredKeepsOriginalOrder() {
        Map<String, Object> p = props("remark", "metrics", "push_role", "board_name");
        assertEquals(List.of("remark", "metrics", "push_role", "board_name"),
                names(FormTemplateService.orderFieldEntries(p, List.of())));
    }

    @Test
    @DisplayName("null required 不抛异常（老数据 schema 可能没有该键）")
    void nullRequiredTolerated() {
        Map<String, Object> p = props("x", "y");
        assertTrue(names(FormTemplateService.orderFieldEntries(p, null)).size() == 2);
    }
}
