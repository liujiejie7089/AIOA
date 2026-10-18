package cn.aioa.resource.service;

import cn.aioa.resource.service.FormSchemaValidator.FieldError;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * FormSchemaValidator 单测（docs/52 P1，纯函数）。
 *
 * <p>每条断言都对应一类「删掉被测实现就会变红」的缺陷：未知类型必须报错、必填必须非空、
 * 类型必须匹配、enum 必须命中、min/max/maxLength 必须生效、空 properties 必须被拒。</p>
 */
class FormSchemaValidatorTest {

    private static final String SCHEMA_BASE =
            "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"text\",\"label\":\"姓名\",\"required\":true}"
                    + ",\"age\":{\"type\":\"number\",\"label\":\"年龄\"}},\"required\":[\"name\"]}";

    private static List<FieldError> v(String schema, Map<String, Object> data) {
        return FormSchemaValidator.validate(schema, data);
    }

    @Test
    @DisplayName("合法数据 → 通过（errors 为空）")
    void validPasses() {
        List<FieldError> errors = v(SCHEMA_BASE, Map.of("name", "张三"));
        assertTrue(errors.isEmpty(), "合法数据不应有错误：" + errors);
    }

    @Test
    @DisplayName("必填字段缺失 → 报错")
    void requiredMissing() {
        List<FieldError> errors = v(SCHEMA_BASE, Map.of());
        assertFalse(errors.isEmpty(), "必填姓名缺失应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("name") && e.message().contains("必填")),
                "应指出姓名必填：" + errors);
    }

    @Test
    @DisplayName("number 类型传字符串 → 报错（类型不符）")
    void numberTypeMismatch() {
        String schema = "{\"type\":\"object\",\"properties\":{\"age\":{\"type\":\"number\",\"label\":\"年龄\"}}}";
        List<FieldError> errors = v(schema, Map.of("age", "二十"));
        assertFalse(errors.isEmpty(), "number 传字符串应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("age") && e.message().contains("数字")),
                "应指出 age 必须是数字：" + errors);
    }

    @Test
    @DisplayName("未知字段类型 → 必须报错（不准静默放过）")
    void unknownTypeRejected() {
        String schema = "{\"type\":\"object\",\"properties\":{\"x\":{\"type\":\"blob\"}}}";
        List<FieldError> errors = v(schema, Map.of("x", 1));
        assertFalse(errors.isEmpty(), "未知类型必须报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("x") && e.message().contains("不支持")),
                "应指出类型不支持：" + errors);
    }

    @Test
    @DisplayName("select 的 enum 不命中 → 报错")
    void enumNotHit() {
        String schema = "{\"type\":\"object\",\"properties\":{\"lvl\":{\"type\":\"select\",\"label\":\"级别\""
                + ",\"enum\":[\"A\",\"B\"]}}}";
        List<FieldError> errors = v(schema, Map.of("lvl", "C"));
        assertFalse(errors.isEmpty(), "enum 不命中应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("lvl") && e.message().contains("允许范围")),
                "应指出值不在允许范围内：" + errors);
    }

    @Test
    @DisplayName("number 低于 minimum → 报错")
    void minimumExceeded() {
        String schema = "{\"type\":\"object\",\"properties\":{\"age\":{\"type\":\"number\",\"label\":\"年龄\""
                + ",\"minimum\":18}}}";
        List<FieldError> errors = v(schema, Map.of("age", 10));
        assertFalse(errors.isEmpty(), "低于 minimum 应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("age") && e.message().contains("不能小于")),
                "应指出不能小于 18：" + errors);
    }

    @Test
    @DisplayName("multiselect 传字符串 → 报错（必须是数组）")
    void multiselectString() {
        String schema = "{\"type\":\"object\",\"properties\":{\"tags\":{\"type\":\"multiselect\",\"label\":\"标签\"}}}";
        List<FieldError> errors = v(schema, Map.of("tags", "a"));
        assertFalse(errors.isEmpty(), "multiselect 传字符串应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("tags") && e.message().contains("数组")),
                "应指出必须是数组：" + errors);
    }

    @Test
    @DisplayName("properties 为空 → 报错（不能配置出没有字段的表单）")
    void emptyPropertiesRejected() {
        String schema = "{\"type\":\"object\",\"properties\":{}}";
        List<FieldError> errors = v(schema, Map.of());
        assertFalse(errors.isEmpty(), "空 properties 应报错");
        assertTrue(errors.stream().anyMatch(e -> e.message().contains("不能为空")),
                "应指出 properties 不能为空：" + errors);
    }

    @Test
    @DisplayName("date 传非法日期串 → 报错（不能是任意文本）")
    void invalidDate() {
        String schema = "{\"type\":\"object\",\"properties\":{\"d\":{\"type\":\"date\",\"label\":\"日期\"}}}";
        List<FieldError> errors = v(schema, Map.of("d", "2026/13/40"));
        assertFalse(errors.isEmpty(), "非法日期应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("d") && e.message().contains("合法日期")),
                "应指出不是合法日期：" + errors);
    }

    @Test
    @DisplayName("text 超过 maxLength → 报错")
    void maxLengthExceeded() {
        String schema = "{\"type\":\"object\",\"properties\":{\"note\":{\"type\":\"text\",\"label\":\"备注\""
                + ",\"maxLength\":3}}}";
        List<FieldError> errors = v(schema, Map.of("note", "abcd"));
        assertFalse(errors.isEmpty(), "超过 maxLength 应报错");
        assertTrue(errors.stream().anyMatch(e -> e.field().equals("note") && e.message().contains("长度不能")),
                "应指出长度不能超过：" + errors);
    }

    @Test
    @DisplayName("schema 不是合法 JSON → 报错（不崩溃）")
    void malformedJson() {
        List<FieldError> errors = v("{not json", Map.of());
        assertFalse(errors.isEmpty(), "非法 JSON 应报错");
    }
}
