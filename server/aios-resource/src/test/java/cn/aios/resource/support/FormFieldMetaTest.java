package cn.aios.resource.support;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 字段元信息判定的判别力测试（docs/52 P1）。
 *
 * <p>本测试存在的理由：种子数据（V86）与设计器写的是 {@code x-type} + {@code title} + {@code description}，
 * 而标准 JSON Schema 只认 {@code type}/{@code format}。这两套词汇一旦在「校验器」与「渲染解析」之间
 * 各认一套，43 张表会全部渲染成英文键名 + 无控件（2026-10-17 实测就是如此）。所以把判定钉在纯函数上。</p>
 */
class FormFieldMetaTest {

    private static Map<String, Object> def(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) {
            m.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return m;
    }

    @Test
    @DisplayName("x-type 优先于标准 type（种子数据的真实形态）")
    void xTypeWins() {
        assertEquals("select", FormFieldMeta.controlType(
                def("type", "string", "x-type", "select", "enum", List.of("A", "B"))));
        assertEquals("file", FormFieldMeta.controlType(def("type", "string", "x-type", "file")));
        assertEquals("amount", FormFieldMeta.controlType(def("type", "string", "x-type", "amount")));
    }

    @Test
    @DisplayName("无 x-type 时按标准 type 回退：string+enum 视为下拉")
    void fallbackStringWithEnum() {
        assertEquals("select", FormFieldMeta.controlType(def("type", "string", "enum", List.of("A"))));
        assertEquals("text", FormFieldMeta.controlType(def("type", "string")));
    }

    @Test
    @DisplayName("无 x-type 时 format 决定日期控件")
    void fallbackDateFormat() {
        assertEquals("date", FormFieldMeta.controlType(def("type", "string", "format", "date")));
        assertEquals("datetime", FormFieldMeta.controlType(def("type", "string", "format", "date-time")));
    }

    @Test
    @DisplayName("标准基本类型映射：number/boolean/array → 数字/开关/多选")
    void fallbackPrimitives() {
        assertEquals("number", FormFieldMeta.controlType(def("type", "number")));
        assertEquals("number", FormFieldMeta.controlType(def("type", "integer")));
        assertEquals("boolean", FormFieldMeta.controlType(def("type", "boolean")));
        assertEquals("multiselect", FormFieldMeta.controlType(def("type", "array")));
    }

    @Test
    @DisplayName("复合类型与空定义必须判为不可渲染（返回 null，由调用方报错）")
    void unknownIsNull() {
        assertNull(FormFieldMeta.controlType(def("type", "object")));
        assertNull(FormFieldMeta.controlType(def()));
        assertNull(FormFieldMeta.controlType(null));
    }

    @Test
    @DisplayName("标签与占位回退：label/title、placeholder/description、最后退回字段名")
    void labelAndPlaceholder() {
        assertEquals("公文种类", FormFieldMeta.label(def("title", "公文种类"), "doc_kind"));
        assertEquals("别名", FormFieldMeta.label(def("label", "别名", "title", "标题"), "k"));
        assertEquals("doc_kind", FormFieldMeta.label(def(), "doc_kind"));
        assertEquals("请输入公文标题", FormFieldMeta.placeholder(def("description", "请输入公文标题")));
        assertEquals("请填", FormFieldMeta.placeholder(def("placeholder", "请填", "description", "描述")));
        assertNull(FormFieldMeta.placeholder(def()));
    }

    @Test
    @DisplayName("负向证明：若判定退化成直接读 type，上面两条断言会红（此处直接对比原始值）")
    void rawTypeWouldDiffer() {
        Map<String, Object> d = def("type", "string", "x-type", "select");
        assertEquals("string", d.get("type"));
        assertEquals("select", FormFieldMeta.controlType(d));
    }
}
