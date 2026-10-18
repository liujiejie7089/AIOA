package cn.aioa.resource.support;

import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 表单字段元信息的<b>唯一判定点</b>（docs/52 P1）。
 *
 * <p>为什么需要它：schema_json 是<b>标准 JSON Schema</b>（Draft 2020-12），其中
 * {@code type} 只能是 string/number/boolean/array 等基本类型，<b>不能</b>写 text/select 这类控件词。
 * 本仓约定用扩展键 {@code x-type} 承载控件类型（设计器与种子数据都这么写），
 * 同时兼容未写 x-type 的纯标准 schema（按 type + format 回退映射）。</p>
 *
 * <p>铁律 1：这条判定只允许存在这一份。校验器（提交校验）与渲染解析（{@code resolveForRender}）
 * 都必须调这里，否则会出现「校验认 text、渲染认 string」这类口径漂移。</p>
 */
public final class FormFieldMeta {

    /** 控件类型白名单（与前端渲染器一致，禁止新造词）。 */
    public static final Set<String> CONTROL_TYPES = Set.of(
            "text", "textarea", "number", "amount", "date", "datetime",
            "select", "multiselect", "file", "boolean");

    private FormFieldMeta() {
    }

    /**
     * 解析控件类型：优先 {@code x-type}，否则按标准 {@code type}（含 {@code format}）回退。
     *
     * @return 白名单内的控件类型；无法判定时返回 {@code null}（调用方必须按「不支持」报错，不得静默放过）
     */
    public static String controlType(Map<String, Object> def) {
        if (def == null) {
            return null;
        }
        Object xType = def.get("x-type");
        if (xType != null && !String.valueOf(xType).isBlank()) {
            return String.valueOf(xType).trim();
        }
        Object t = def.get("type");
        if (t == null) {
            return null;
        }
        String jsonType = String.valueOf(t).trim();
        // 兼容第三种写法：把控件词直接写在 type 上（早期手写 schema / 单测如此）。
        // 这些词不是合法的 JSON Schema 基本类型，出现即代表「想表达控件」，按控件处理。
        if (CONTROL_TYPES.contains(jsonType)) {
            return jsonType;
        }
        return switch (jsonType) {
            case "string" -> {
                Object fmt = def.get("format");
                if ("date".equals(fmt)) {
                    yield "date";
                }
                if ("date-time".equals(fmt)) {
                    yield "datetime";
                }
                // 带 enum 的字符串按单选渲染（标准 schema 里这是最常见的下拉写法）
                yield def.get("enum") instanceof List<?> ? "select" : "text";
            }
            case "integer", "number" -> "number";
            case "boolean" -> "boolean";
            case "array" -> "multiselect";
            // object 等复合类型不提供控件：必须报不支持，避免渲染出无意义空块
            default -> null;
        };
    }

    /** 字段标签：{@code label} → {@code title} → 字段名（中文界面不允许裸露英文键名在没有标签的情况下）。 */
    public static String label(Map<String, Object> def, String name) {
        String v = firstText(def, "label", "title");
        return v == null ? name : v;
    }

    /** 输入提示：{@code placeholder} → {@code description}。 */
    public static String placeholder(Map<String, Object> def) {
        return firstText(def, "placeholder", "description");
    }

    private static String firstText(Map<String, Object> def, String... keys) {
        if (def == null) {
            return null;
        }
        for (String k : keys) {
            Object v = def.get(k);
            if (v != null && !String.valueOf(v).isBlank()) {
                return String.valueOf(v).trim();
            }
        }
        return null;
    }
}
