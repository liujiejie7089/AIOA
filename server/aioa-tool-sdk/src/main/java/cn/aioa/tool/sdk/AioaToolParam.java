package cn.aioa.tool.sdk;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 声明工具方法的一个入参。
 *
 * <p>被它标注的参数从调用入参里按 {@link #name()} 取值；
 * 未标注的 {@code Map<String,Object>} 参数收到的是整个入参表（透传场景）；
 * {@link ToolCallContext} 类型的参数由框架注入调用者身份，不占用入参命名空间。</p>
 */
@Documented
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
public @interface AioaToolParam {

    /** 入参名（模型 function-calling 的字段名）。 */
    String name();

    /** 字段说明：会进 JSON Schema，是模型填对参数的唯一依据。 */
    String description() default "";

    /** 是否必填；必填而缺失时调用会以业务错误返回，而不是静默传 null。 */
    boolean required() default false;

    /** JSON Schema 类型：string / number / integer / boolean / object / array。 */
    String type() default "string";
}
