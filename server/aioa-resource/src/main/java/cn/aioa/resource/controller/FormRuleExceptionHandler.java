package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.service.FormRuleException;
import cn.aioa.resource.service.FormSchemaValidator;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 表单业务规则异常处理器（docs/53 缺口二）。
 *
 * <p>命中 schema 声明的强分支规则时，转成 <b>HTTP 200 + code=40090</b> 的契约体返回——
 * 与现有 {@code BizException(400)}「H5 只看 body.code 判成败」的惯例一致，避免把「用户填错」
 * 当成「服务崩了」（5xx）。</p>
 *
 * <p>契约体（键名不可改，H5 据此渲染）：</p>
 * <pre>
 * {"code":40090,"message":"<第一条规则中文说明>",
 *  "data":{"rule_violation":{"rule_id":"...","field":"leave_type",
 *          "target_field":"leave_type","message":"...",
 *          "options":[{"value":"annual","label":"改为年假"}]}}}
 * </pre>
 */
@RestControllerAdvice
public class FormRuleExceptionHandler {

    @ExceptionHandler(FormRuleException.class)
    public ResponseEntity<ApiResponse<Map<String, Object>>> handle(FormRuleException e) {
        List<FormSchemaValidator.RuleHit> hits = e.hits();
        FormSchemaValidator.RuleHit first = hits.isEmpty() ? null : hits.get(0);
        String msg = first != null ? first.message() : "该表单有业务规则未通过";

        Map<String, Object> ruleViolation = new LinkedHashMap<>();
        ruleViolation.put("rule_id", first != null ? first.ruleId() : "");
        ruleViolation.put("field", first != null ? first.field() : "");
        ruleViolation.put("target_field", first != null ? first.targetField() : "");
        ruleViolation.put("message", msg);
        ruleViolation.put("options", first != null ? first.options() : List.of());

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("rule_violation", ruleViolation);

        // 与 BizException(400) 惯例一致：HTTP 200，成败只看 body.code
        return ResponseEntity.status(HttpStatus.OK)
                .body(ApiResponse.fail(40090, msg, data));
    }
}
