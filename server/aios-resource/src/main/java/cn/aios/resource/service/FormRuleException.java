package cn.aios.resource.service;

import java.util.List;

/**
 * 表单业务规则校验异常：提交数据触发了 schema 里声明的强分支规则（如「病假必须附诊断证明」）。
 *
 * <p>收集 {@link FormSchemaValidator.RuleHit} 全量命中，message 取第一条命中的中文说明，
 * 由 {@code FormRuleExceptionHandler} 转成 HTTP 200 + code=40090 的契约体返回前端（与
 * {@code BizException} 的 400 惯例一致，H5 只看 body.code）。</p>
 */
public class FormRuleException extends RuntimeException {

    private final List<FormSchemaValidator.RuleHit> hits;

    public FormRuleException(List<FormSchemaValidator.RuleHit> hits) {
        super(hits != null && !hits.isEmpty() ? hits.get(0).message() : "该表单有业务规则未通过");
        this.hits = hits == null ? List.of() : hits;
    }

    public List<FormSchemaValidator.RuleHit> hits() {
        return hits;
    }
}
