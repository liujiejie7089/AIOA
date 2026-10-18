package cn.aios.resource.service;

import cn.aios.resource.service.FormSchemaValidator.RuleHit;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * FormSchemaValidator 业务规则（rules[]）与 propertyNames 单测（docs/53 缺口二、三）。
 *
 * <p>每条断言对应一类「删掉被测实现就会变红」的缺陷：block 命中/不命中、in+require 缺字段命中、
 * require 已填不命中（负向）、无 when 不拦截（负向）、options 只透传 value/label、x-rules 兼容且
 * rules 优先、propertyNames 取 properties 键、未知 op/action 跳过且不抛。</p>
 */
class FormSchemaValidatorRulesTest {

    /** 含「病假必须附诊断证明」require 规则的 schema。 */
    private static final String SCHEMA_SICK_PROOF =
            "{\"type\":\"object\","
                    + "\"properties\":{\"leave_type\":{\"type\":\"text\"},\"proof\":{\"type\":\"file\"}},"
                    + "\"rules\":[{\"id\":\"sick_need_proof\","
                    + "\"when\":{\"field\":\"leave_type\",\"op\":\"in\",\"value\":[\"sick\"]},"
                    + "\"then\":{\"action\":\"require\",\"require_fields\":[\"proof\"],"
                    + "\"message\":\"病假需上传诊断证明\",\"target_field\":\"leave_type\","
                    + "\"options\":[{\"value\":\"annual\",\"label\":\"改为年假\"}]}}]}";

    private static final String SCHEMA_BLOCK =
            "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                    + "\"rules\":[{\"id\":\"sick_block\","
                    + "\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"sick\"},"
                    + "\"then\":{\"action\":\"block\",\"message\":\"病假被拦截\"}}]}";

    // ================================================================== R1：block 命中 / 不命中

    @Test
    @DisplayName("R1 block 规则：条件成立命中；不成立不命中")
    void r1Block() {
        // leave_type=sick → 命中
        List<RuleHit> hit = FormSchemaValidator.validateRules(SCHEMA_BLOCK, Map.of("leave_type", "sick"));
        assertEquals(1, hit.size(), "条件成立应命中");
        assertEquals("sick_block", hit.get(0).ruleId());

        // leave_type=annual → 不命中
        List<RuleHit> miss = FormSchemaValidator.validateRules(SCHEMA_BLOCK, Map.of("leave_type", "annual"));
        assertTrue(miss.isEmpty(), "条件不成立不应命中：" + miss);
    }

    // ================================================================== R2：in + require 缺字段 → 命中

    @Test
    @DisplayName("R2 in 操作符 + require 缺字段 → 命中")
    void r2InRequireMissing() {
        List<RuleHit> hit = FormSchemaValidator.validateRules(SCHEMA_SICK_PROOF,
                Map.of("leave_type", "sick")); // 没填 proof
        assertEquals(1, hit.size(), "病假且缺证明应命中");
        RuleHit h = hit.get(0);
        assertEquals("sick_need_proof", h.ruleId());
        assertEquals("leave_type", h.field());
        assertEquals("leave_type", h.targetField());
        assertEquals("病假需上传诊断证明", h.message());
    }

    // ================================================================== R3：require 但字段已填 → 不命中（负向）

    @Test
    @DisplayName("R3 require 但字段已填 → 不命中（证明不是恒真）")
    void r3RequireFilled() {
        List<RuleHit> hit = FormSchemaValidator.validateRules(SCHEMA_SICK_PROOF,
                Map.of("leave_type", "sick", "proof", "diag.jpg")); // 已填 proof
        assertTrue(hit.isEmpty(), "字段已填不应命中（若变红说明 require 成了恒真）：" + hit);
    }

    // ================================================================== R4：没有 when 的规则不拦截（负向）

    @Test
    @DisplayName("R4 没有 when 的规则不拦截")
    void r4NoWhen() {
        String schema = "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                + "\"rules\":[{\"id\":\"bad\",\"then\":{\"action\":\"block\",\"message\":\"x\"}}]}";
        List<RuleHit> hit = FormSchemaValidator.validateRules(schema, Map.of("leave_type", "sick"));
        assertTrue(hit.isEmpty(), "无 when 的规则不应拦截：" + hit);
    }

    // ================================================================== R5：options 只透传 value/label，脏键被丢

    @Test
    @DisplayName("R5 options 只透传 value/label，脏键被丢")
    void r5OptionsClean() {
        String schema = "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                + "\"rules\":[{\"id\":\"opt\",\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"sick\"},"
                + "\"then\":{\"action\":\"block\",\"message\":\"x\","
                + "\"options\":[{\"value\":\"annual\",\"label\":\"改为年假\",\"junk\":\"drop\"},"
                + "{\"value\":\"sick\",\"label\":\"病假\"}]}}]}";
        List<RuleHit> hit = FormSchemaValidator.validateRules(schema, Map.of("leave_type", "sick"));
        assertEquals(1, hit.size());
        List<Map<String, Object>> options = hit.get(0).options();
        assertEquals(2, options.size(), "应保留两条合法 option");
        for (Map<String, Object> o : options) {
            assertEquals(Set.of("value", "label"), o.keySet(), "option 只应剩 value/label：" + o);
        }
        assertEquals("改为年假", options.get(0).get("label"));
    }

    // ================================================================== R6：x-rules 兼容 + rules 优先

    @Test
    @DisplayName("R6a rules 优先于 x-rules（两者都有时只用 rules）")
    void r6RulesPriority() {
        String schema = "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                + "\"rules\":[{\"id\":\"r1\",\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"annual\"},"
                + "\"then\":{\"action\":\"block\",\"message\":\"x\"}}],"
                + "\"x-rules\":[{\"id\":\"x1\",\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"sick\"},"
                + "\"then\":{\"action\":\"block\",\"message\":\"x\"}}]}";
        // data=sick 只命中 x-rules，但 rules 优先 → 不命中
        List<RuleHit> hit = FormSchemaValidator.validateRules(schema, Map.of("leave_type", "sick"));
        assertTrue(hit.isEmpty(), "rules 优先，x-rules 的命中应被忽略：" + hit);
    }

    @Test
    @DisplayName("R6b 仅 x-rules（无 rules）也能生效")
    void r6XRulesOnly() {
        String schema = "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                + "\"x-rules\":[{\"id\":\"x1\",\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"sick\"},"
                + "\"then\":{\"action\":\"block\",\"message\":\"x\"}}]}";
        List<RuleHit> hit = FormSchemaValidator.validateRules(schema, Map.of("leave_type", "sick"));
        assertEquals(1, hit.size(), "仅 x-rules 应生效");
        assertEquals("x1", hit.get(0).ruleId());
    }

    // ================================================================== R7：propertyNames 返回 properties 键

    @Test
    @DisplayName("R7 propertyNames 返回 schema 的 properties 键集合")
    void r7PropertyNames() {
        String schema = "{\"type\":\"object\","
                + "\"properties\":{\"leave_type\":{\"type\":\"text\"},\"proof\":{\"type\":\"file\"},"
                + "\"days\":{\"type\":\"number\"}}}";
        Set<String> names = FormSchemaValidator.propertyNames(schema);
        assertEquals(Set.of("leave_type", "proof", "days"), names);

        // 非法 schema → 空集合（不抛）
        assertTrue(FormSchemaValidator.propertyNames("not json").isEmpty());
        assertTrue(FormSchemaValidator.propertyNames(null).isEmpty());
    }

    // ================================================================== R8：未知 op / action 都跳过且不抛

    @Test
    @DisplayName("R8 未知 op / 未知 action 都跳过且不抛异常")
    void r8UnknownOpAction() {
        String schema = "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                + "\"rules\":["
                + "{\"id\":\"u1\",\"when\":{\"field\":\"leave_type\",\"op\":\"unknown_op\",\"value\":\"sick\"},"
                + "\"then\":{\"action\":\"block\",\"message\":\"x\"}},"
                + "{\"id\":\"u2\",\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"sick\"},"
                + "\"then\":{\"action\":\"send_email\",\"message\":\"x\"}}]}";
        // 不应抛异常；两条都不匹配 → 空
        List<RuleHit> hit = FormSchemaValidator.validateRules(schema, Map.of("leave_type", "sick"));
        assertTrue(hit.isEmpty(), "未知 op/action 应跳过：" + hit);
    }

    // ================================================================== 附加：FormRuleException 收集命中、message 取首条

    @Test
    @DisplayName("附加 FormRuleException 收集命中且 message 取首条")
    void formRuleException() {
        List<RuleHit> hits = FormSchemaValidator.validateRules(SCHEMA_SICK_PROOF,
                Map.of("leave_type", "sick"));
        FormRuleException ex = new FormRuleException(hits);
        assertEquals(hits, ex.hits());
        assertEquals("病假需上传诊断证明", ex.getMessage());
        assertThrows(FormRuleException.class, () -> {
            throw ex;
        });
    }
}
