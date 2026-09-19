package cn.aioa.tool.sdk;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 把一个 Spring Bean 的方法声明为「平台可治理的工具」。
 *
 * <p><b>解决的问题</b>：在它出现之前，新增一个工具要改三处 ——
 * 在 {@code tool_definition} 里插一行、在某处写一个 switch 分支、
 * 再把入参/出参契约手抄一遍。三处里错一处就得到一个「定义存在但调不通」
 * 或「能调用但没登记」的半成品。注解把这三件事压成一件：方法即契约。</p>
 *
 * <p><b>用法</b>：</p>
 * <pre>
 * &#64;Component
 * public class MyTools {
 *     &#64;AioaTool(code = "lookup_order", description = "按单号查订单")
 *     public Map&lt;String, Object&gt; lookup(
 *             &#64;AioaToolParam(name = "orderNo", description = "订单号", required = true) String orderNo,
 *             ToolCallContext caller) {
 *         return Map.of("ok", true, "data", orderNo);
 *     }
 * }
 * </pre>
 *
 * <p>注解只负责「声明」，治理（权限 / 幂等 / 审批 / 审计）仍由工具网关统一执行 ——
 * 标注了 {@link #requiresApproval()} 的方法不会因为「是本地方法」而绕过审批。</p>
 */
@Documented
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface AioaTool {

    /** 全局唯一工具编码（对应 {@code tool_definition.tool_code}），需符合 [a-zA-Z0-9_-]。 */
    String code();

    /** 展示名；缺省时取方法名。 */
    String name() default "";

    /** 描述：模型据此判断何时调用，必须写清适用场景。 */
    String description();

    /** 版本；同一编码多版本共存时，注册表默认取最高版本。 */
    String version() default "1.0.0";

    /** 领域归属（如 org / resource / platform），用于清单分组与运维排查。 */
    String domain() default "";

    /** 风险级别：LOW / MEDIUM / HIGH。 */
    String riskLevel() default "LOW";

    /** 是否必须经审批后才能执行（HITL）。 */
    boolean requiresApproval() default false;

    /** 是否要求调用方携带幂等键。 */
    boolean idempotencyRequired() default false;

    /** 归属人 / 团队（运维追责用）。 */
    String owner() default "sdk";
}
