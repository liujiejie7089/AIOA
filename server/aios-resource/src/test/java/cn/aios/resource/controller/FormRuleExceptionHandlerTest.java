package cn.aios.resource.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.service.FormRuleException;
import cn.aios.resource.service.FormSchemaValidator;
import cn.aios.resource.service.FormSchemaValidator.RuleHit;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 独立验收：FormRuleExceptionHandler 的契约（verify-forms-backend 补的空白测试）。
 *
 * <p>不经 Spring 上下文：直接 new FormRuleExceptionHandler().handle(...)，再用 Jackson 序列化
 * getBody()，断言 H5 契约：HTTP 200、code=40090、data.rule_violation 五键精确、
 * options 原样透传 {value,label}、target_field 为 null 时的回落语义。</p>
 */
class FormRuleExceptionHandlerTest {

    private final FormRuleExceptionHandler handler = new FormRuleExceptionHandler();
    private final ObjectMapper mapper = new ObjectMapper();

    /** 构造一条「真实路径」命中的 RuleHit：用 validateRules 跑 schema，看 buildHit 的 target_field 回落。 */
    private static final String SCHEMA =
            "{\"type\":\"object\",\"properties\":{\"leave_type\":{\"type\":\"text\"}},"
                    + "\"rules\":[{\"id\":\"r1\","
                    + "\"when\":{\"field\":\"leave_type\",\"op\":\"eq\",\"value\":\"sick\"},"
                    + "\"then\":{\"action\":\"block\",\"message\":\"病假被拦截\","
                    + "\"options\":[{\"value\":\"annual\",\"label\":\"改为年假\"},"
                    + "{\"value\":\"sick\",\"label\":\"病假\"}]}}]}";

    @Test
    @DisplayName("B1 HTTP 状态为 200（H5 只看 body.code 判成败）")
    void httpStatus200() {
        RuleHit hit = new RuleHit("r1", "leave_type", "leave_type", "病假被拦截", List.of());
        ResponseEntity<ApiResponse<Map<String, Object>>> resp =
                handler.handle(new FormRuleException(List.of(hit)));
        assertEquals(200, resp.getStatusCode().value(), "应为 HTTP 200，而非 400/500");
    }

    @Test
    @DisplayName("B2 body.code == 40090")
    void code40090() {
        RuleHit hit = new RuleHit("r1", "leave_type", "leave_type", "病假被拦截", List.of());
        ResponseEntity<ApiResponse<Map<String, Object>>> resp =
                handler.handle(new FormRuleException(List.of(hit)));
        assertEquals(40090, resp.getBody().getCode(), "业务码应为 40090");
    }

    @Test
    @DisplayName("B3 序列化后存在 data.rule_violation，且键集精确为五键")
    void ruleViolationKeys() throws Exception {
        RuleHit hit = new RuleHit("r1", "leave_type", "leave_type", "病假被拦截", List.of());
        ResponseEntity<ApiResponse<Map<String, Object>>> resp =
                handler.handle(new FormRuleException(List.of(hit)));

        String json = mapper.writeValueAsString(resp.getBody());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = mapper.readValue(json, Map.class);
        assertTrue(body.containsKey("data"), "body 应含 data：" + json);
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) body.get("data");
        assertTrue(data.containsKey("rule_violation"), "data 应含 rule_violation：" + json);
        @SuppressWarnings("unchecked")
        Map<String, Object> rv = (Map<String, Object>) data.get("rule_violation");
        assertEquals(Set.of("rule_id", "field", "target_field", "message", "options"),
                rv.keySet(), "rule_violation 键集应精确五键，实际=" + rv.keySet());
    }

    @Test
    @DisplayName("B4 options 原样透传 {value,label}；target_field 为 null 时回落 field（经真实路径）")
    void optionsPassthroughAndTargetFallback() throws Exception {
        // 真实路径：schema 里 then 没写 target_field，buildHit 应回落到 field=leave_type
        List<RuleHit> hits = FormSchemaValidator.validateRules(SCHEMA, Map.of("leave_type", "sick"));
        assertEquals(1, hits.size(), "应命中一条");
        RuleHit realHit = hits.get(0);
        assertEquals("leave_type", realHit.targetField(),
                "target_field 为 null 时应回落到 field（buildHit 逻辑）");

        ResponseEntity<ApiResponse<Map<String, Object>>> resp =
                handler.handle(new FormRuleException(List.of(realHit)));
        String json = mapper.writeValueAsString(resp.getBody());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = mapper.readValue(json, Map.class);
        @SuppressWarnings("unchecked")
        Map<String, Object> rv = (Map<String, Object>) ((Map<String, Object>) body.get("data"))
                .get("rule_violation");

        // target_field 回落后应为 leave_type
        assertEquals("leave_type", rv.get("target_field"),
                "处理器应原样透传回落后的 target_field");

        // options 原样透传，且每条只含 value/label
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> options = (List<Map<String, Object>>) rv.get("options");
        assertNotNull(options);
        assertEquals(2, options.size(), "应透传两条 option");
        for (Map<String, Object> o : options) {
            assertEquals(Set.of("value", "label"), o.keySet(),
                    "option 应精确 value/label，实际=" + o.keySet());
        }
        assertEquals("annual", options.get(0).get("value"));
        assertEquals("改为年假", options.get(0).get("label"));
    }
}
