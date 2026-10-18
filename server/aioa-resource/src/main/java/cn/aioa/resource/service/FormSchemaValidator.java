package cn.aioa.resource.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;

/**
 * 表单 Schema 校验器（docs/52 P1，纯函数、可单测、无 Spring 依赖）。
 *
 * <p>校验一份 JSON Schema（Draft 2020-12 简化版）与用户填写数据是否一致。
 * 设计铁律：</p>
 * <ul>
 *   <li>只认白名单字段类型，<b>未知类型必须报错</b>（不准静默放过）；</li>
 *   <li>校验一份、三处同源——本类是后端提交校验的<b>唯一权威</b>；</li>
 *   <li>禁止反射/脚本求值，禁止接受任意 HTML（只认白名单类型，渲染器据此也只渲染白名单）；</li>
 *   <li>错误信息中文，指出字段名。</li>
 * </ul>
 */
public final class FormSchemaValidator {

    /** 字段类型白名单（与既有前端控件对齐，禁止新造词）。 */
    private static final Set<String> WHITELIST = Set.of(
            "text", "textarea", "number", "amount", "date", "datetime",
            "select", "multiselect", "file", "boolean");

    /** 单条字段错误：指出字段名与中文原因。 */
    public record FieldError(String field, String message) {
    }

    /**
     * 业务规则命中（强分支校验）：指出规则 id、触发字段、面向字段、中文说明与可选修正项。
     *
     * <p>{@code options} 由运行期只透传 {@code {value,label}} 两个键，供前端渲染「一键改值」按钮。</p>
     */
    public record RuleHit(String ruleId, String field, String targetField, String message,
                          List<Map<String, Object>> options) {
    }

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private FormSchemaValidator() {
    }

    /**
     * 校验用户填写数据是否符合 schema。
     *
     * @param schemaJson 表单定义中的 schema_json（JSON 字符串）
     * @param data       用户填写的数据（字段名 → 值）
     * @return 错误列表；空列表表示通过。每条错误都带字段名与中文原因。
     */
    public static List<FieldError> validate(String schemaJson, Map<String, Object> data) {
        List<FieldError> errors = new ArrayList<>();
        if (schemaJson == null || schemaJson.isBlank()) {
            errors.add(new FieldError("", "表单结构不能为空"));
            return errors;
        }
        Map<String, Object> schema;
        try {
            schema = MAPPER.readValue(schemaJson, new TypeReference<LinkedHashMap<String, Object>>() {
            });
        } catch (Exception e) {
            errors.add(new FieldError("", "表单结构不是合法的 JSON"));
            return errors;
        }
        if (!(schema instanceof Map)) {
            errors.add(new FieldError("", "表单结构必须是对象"));
            return errors;
        }
        // 根必须是 object
        Object rootType = schema.get("type");
        if (rootType != null && !"object".equals(rootType.toString())) {
            errors.add(new FieldError("", "表单根结构必须是 object"));
            return errors;
        }
        Object propsObj = schema.get("properties");
        if (!(propsObj instanceof Map)) {
            errors.add(new FieldError("", "表单字段定义(properties)不能为空"));
            return errors;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) propsObj;
        if (props.isEmpty()) {
            errors.add(new FieldError("", "表单字段定义(properties)不能为空"));
            return errors;
        }
        // 必填字段集合：根 required 数组 + 字段级 required 布尔
        Set<String> required = new HashSet<>();
        Object reqObj = schema.get("required");
        if (reqObj instanceof List<?>) {
            for (Object o : (List<?>) reqObj) {
                if (o != null) {
                    required.add(o.toString());
                }
            }
        }
        for (Map.Entry<String, Object> e : props.entrySet()) {
            String field = e.getKey();
            Object defObj = e.getValue();
            if (!(defObj instanceof Map)) {
                errors.add(new FieldError(field, "字段「" + field + "」的定义格式错误"));
                continue;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> def = (Map<String, Object>) defObj;
            boolean fieldRequired = required.contains(field)
                    || Boolean.TRUE.equals(def.get("required"));
            validateField(field, def, fieldRequired, data, errors);
        }
        return errors;
    }

    private static void validateField(String field, Map<String, Object> def, boolean required,
                                      Map<String, Object> data, List<FieldError> errors) {
        // 控件类型判定统一走 FormFieldMeta（唯一判定点）：优先 x-type，其次标准 type + format。
        String type = cn.aioa.resource.support.FormFieldMeta.controlType(def);
        if (type == null || !WHITELIST.contains(type)) {
            // 未知类型必须报错，不准静默放过
            Object raw = def.get("x-type") != null ? def.get("x-type") : def.get("type");
            errors.add(new FieldError(field, "字段「" + labelOf(field, def) + "」的类型不支持：" + raw));
            return;
        }
        String label = labelOf(field, def);
        Object value = data == null ? null : data.get(field);

        // 必填：存在且非空
        if (required) {
            if (isBlank(type, value)) {
                errors.add(new FieldError(field, "必填字段「" + label + "」不能为空"));
                return; // 空值不再做类型校验，避免重复报错
            }
        } else {
            if (isAbsent(value)) {
                return; // 选填且缺失：跳过
            }
        }

        // 类型匹配
        switch (type) {
            case "number", "amount" -> {
                if (!(value instanceof Number)) {
                    errors.add(new FieldError(field, "字段「" + label + "」必须是数字"));
                    break;
                }
                Number n = (Number) value;
                checkMinMax(field, label, def, n, errors);
            }
            case "boolean" -> {
                if (!(value instanceof Boolean)) {
                    errors.add(new FieldError(field, "字段「" + label + "」必须是布尔值（true/false）"));
                }
            }
            case "date", "datetime" -> {
                if (!parseableDate(value)) {
                    errors.add(new FieldError(field, "字段「" + label + "」不是合法日期"));
                }
            }
            case "multiselect" -> {
                if (!(value instanceof List)) {
                    errors.add(new FieldError(field, "字段「" + label + "」必须是数组"));
                }
            }
            case "file" -> {
                if (!(value instanceof List) && !(value instanceof String)) {
                    errors.add(new FieldError(field, "字段「" + label + "」格式不正确（应为数组或字符串）"));
                }
            }
            case "text", "textarea", "select" -> {
                if (!(value instanceof String)) {
                    errors.add(new FieldError(field, "字段「" + label + "」必须是文本"));
                } else {
                    String s = (String) value;
                    checkMaxLength(field, label, def, s, errors);
                    checkPattern(field, label, def, s, errors);
                }
            }
            default -> {
            }
        }

        // enum 成员必须命中（适用所有带 enum 的字段，如 select）
        checkEnum(field, label, def, value, errors);
    }

    private static void checkMinMax(String field, String label, Map<String, Object> def,
                                   Number n, List<FieldError> errors) {
        double dv = n.doubleValue();
        Object min = def.get("minimum");
        Object max = def.get("maximum");
        if (min instanceof Number && dv < ((Number) min).doubleValue()) {
            errors.add(new FieldError(field, "字段「" + label + "」不能小于 " + min));
        }
        if (max instanceof Number && dv > ((Number) max).doubleValue()) {
            errors.add(new FieldError(field, "字段「" + label + "」不能大于 " + max));
        }
    }

    private static void checkMaxLength(String field, String label, Map<String, Object> def,
                                      String s, List<FieldError> errors) {
        Object ml = def.get("maxLength");
        if (ml instanceof Number && s.length() > ((Number) ml).intValue()) {
            errors.add(new FieldError(field, "字段「" + label + "」长度不能超过 " + ml + " 个字符"));
        }
    }

    private static void checkPattern(String field, String label, Map<String, Object> def,
                                     String s, List<FieldError> errors) {
        Object p = def.get("pattern");
        if (!(p instanceof String ps) || ps.isBlank()) {
            return;
        }
        // 用 try/catch 保护非法正则：配置错误的 pattern 不应让整个校验崩溃
        try {
            if (!Pattern.compile(ps).matcher(s).find()) {
                errors.add(new FieldError(field, "字段「" + label + "」格式不正确"));
            }
        } catch (PatternSyntaxException ex) {
            // 非法正则：跳过该 Pattern 校验（保护不崩溃），不静默放过其他校验
        }
    }

    private static void checkEnum(String field, String label, Map<String, Object> def,
                                 Object value, List<FieldError> errors) {
        Object en = def.get("enum");
        if (!(en instanceof List<?> list) || list.isEmpty()) {
            return;
        }
        for (Object o : list) {
            if (o == null ? value == null : o.equals(value)) {
                return;
            }
        }
        errors.add(new FieldError(field, "字段「" + label + "」的值不在允许范围内"));
    }

    /** 必填语境下值是否为「空」（null / 空串 / 空数组都算空）。 */
    private static boolean isBlank(String type, Object value) {
        if (value == null) {
            return true;
        }
        if (value instanceof String s) {
            return s.isBlank();
        }
        if (value instanceof List<?> l) {
            return l.isEmpty();
        }
        // 数字 / 布尔 视为有值
        return false;
    }

    /** 选填语境下值是否「缺失」（null 或空串视为缺失；布尔/数字/空数组视为有值）。 */
    private static boolean isAbsent(Object value) {
        if (value == null) {
            return true;
        }
        return value instanceof String s && s.isBlank();
    }

    /** 日期/时间是否可被 LocalDate 或 LocalDateTime 解析（含常见 ISO 串）。 */
    private static boolean parseableDate(Object value) {
        if (value instanceof LocalDate || value instanceof LocalDateTime) {
            return true;
        }
        if (value instanceof String s) {
            s = s.trim();
            if (s.isEmpty()) {
                return false;
            }
            try {
                LocalDate.parse(s);
                return true;
            } catch (DateTimeParseException ignored) {
                // 继续尝试
            }
            try {
                LocalDateTime.parse(s);
                return true;
            } catch (DateTimeParseException ignored) {
                return false;
            }
        }
        return false;
    }

    /**
     * 字段展示名：**必须走 {@link FormFieldMeta#label}**（label → title → name）。
     *
     * <p>2026-10-17 实测缺陷：这里原来自带一份 `def.get("label")`，而 V86 种子的 schema 用
     * JSON Schema 标准的 `title` ⇒ 校验报错话术退回英文键名
     * 「必填字段「today_work」不能为空」，用户看不懂该改哪一格。
     * 展示名口径只允许有一个判定点，否则改一处漂移一处。</p>
     */
    private static String labelOf(String field, Map<String, Object> def) {
        return cn.aioa.resource.support.FormFieldMeta.label(def, field);
    }

    // ================================================================== 业务规则强分支校验（docs/53 缺口二）

    /** `when.op` 白名单。 */
    private static final Set<String> RULE_OPS = Set.of(
            "eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "empty", "not_empty");

    /** `then.action` 白名单（运行期只认这两个，其它跳过）。 */
    private static final Set<String> RULE_ACTIONS = Set.of("block", "require");

    /**
     * 业务规则强分支校验：条件成立即产出一条 {@link RuleHit}（可被 {@code FormRuleException} 收集）。
     *
     * <p>规则容器：根键优先 {@code rules}，兼容 {@code x-rules}；{@code rules} 存在就用它
     * （两者都有时仍用 {@code rules}），值必须是 {@code List<Map>}，否则整块跳过（不抛）。
     * 单条规则配置错误（缺 when / 未知 op / 未知 action 等）<b>运行期不抛</b>——坏配置由
     * {@code FormTemplateService.validateSave} 在保存期兜住，不会写进库、也不会让提交静默崩溃。</p>
     *
     * @return 命中的规则列表；空列表表示全部通过。
     */
    public static List<RuleHit> validateRules(String schemaJson, Map<String, Object> data) {
        List<RuleHit> hits = new ArrayList<>();
        if (schemaJson == null || schemaJson.isBlank()) {
            return hits;
        }
        Map<String, Object> schema;
        try {
            schema = MAPPER.readValue(schemaJson, new TypeReference<LinkedHashMap<String, Object>>() {
            });
        } catch (Exception e) {
            return hits; // 解析失败：运行期不抛，交给字段校验器报错
        }
        if (!(schema instanceof Map)) {
            return hits;
        }
        Object rulesObj = schema.get("rules");
        if (!(rulesObj instanceof List)) {
            rulesObj = schema.get("x-rules"); // 兼容 x-rules
        }
        if (!(rulesObj instanceof List<?> rules)) {
            return hits; // 值必须是 List<Map>，否则整块跳过
        }
        for (Object ro : rules) {
            if (!(ro instanceof Map)) {
                continue; // 运行期不抛
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> rule = (Map<String, Object>) ro;
            RuleHit hit = evalRule(rule, data);
            if (hit != null) {
                hits.add(hit);
            }
        }
        return hits;
    }

    /** 评估单条规则；不命中或配置不合法返回 null（不抛）。 */
    private static RuleHit evalRule(Map<String, Object> rule, Map<String, Object> data) {
        Object whenObj = rule.get("when");
        if (!(whenObj instanceof Map)) {
            return null; // 没有 when 的规则不拦截（负向对照）
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> when = (Map<String, Object>) whenObj;
        Object fieldObj = when.get("field");
        if (!(fieldObj instanceof String field) || field.isBlank()) {
            return null;
        }
        Object opObj = when.get("op");
        if (!(opObj instanceof String op) || op.isBlank()) {
            return null;
        }
        Object valObj = when.get("value");

        boolean whenMatched;
        switch (op) {
            case "eq" -> {
                Object actual = data == null ? null : data.get(field);
                whenMatched = actual != null && Objects.equals(String.valueOf(actual), String.valueOf(valObj));
            }
            case "ne" -> {
                // ne 在字段缺失时视为「不相等」= 命中
                Object actual = data == null ? null : data.get(field);
                whenMatched = !Objects.equals(actual == null ? null : String.valueOf(actual),
                        valObj == null ? null : String.valueOf(valObj));
            }
            case "in" -> {
                if (!(valObj instanceof List<?> vals)) {
                    return null; // value 必须是 List，否则跳过该规则
                }
                Object actual = data == null ? null : data.get(field);
                whenMatched = false;
                for (Object v : vals) {
                    if (Objects.equals(String.valueOf(actual), String.valueOf(v))) {
                        whenMatched = true;
                        break;
                    }
                }
            }
            case "not_in" -> {
                if (!(valObj instanceof List<?> vals)) {
                    return null;
                }
                Object actual = data == null ? null : data.get(field);
                whenMatched = true;
                for (Object v : vals) {
                    if (Objects.equals(String.valueOf(actual), String.valueOf(v))) {
                        whenMatched = false;
                        break;
                    }
                }
            }
            case "gt", "gte", "lt", "lte" -> {
                // 两边都能解析成 double 才比，否则不命中（不抛）
                Object actual = data == null ? null : data.get(field);
                double a, b;
                try {
                    a = Double.parseDouble(String.valueOf(actual));
                    b = Double.parseDouble(String.valueOf(valObj));
                } catch (Exception e) {
                    return null;
                }
                whenMatched = switch (op) {
                    case "gt" -> a > b;
                    case "gte" -> a >= b;
                    case "lt" -> a < b;
                    case "lte" -> a <= b;
                    default -> false;
                };
            }
            case "empty" -> {
                Object actual = data == null ? null : data.get(field);
                whenMatched = isBlank("", actual);
            }
            case "not_empty" -> {
                Object actual = data == null ? null : data.get(field);
                whenMatched = !isBlank("", actual);
            }
            default -> {
                return null; // 未知 op 跳过
            }
        }
        if (!whenMatched) {
            return null;
        }

        Object thenObj = rule.get("then");
        if (!(thenObj instanceof Map)) {
            return null;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> then = (Map<String, Object>) thenObj;
        Object actionObj = then.get("action");
        String action = actionObj instanceof String s ? s : "";
        if (!RULE_ACTIONS.contains(action)) {
            return null; // 其它 action 跳过（配置错误由保存校验兜住）
        }

        if ("require".equals(action)) {
            Object rfObj = then.get("require_fields");
            if (!(rfObj instanceof List<?> rfs)) {
                return null; // require 但没配 require_fields → 跳过
            }
            boolean anyEmpty = false;
            for (Object rf : rfs) {
                if (rf == null) {
                    continue;
                }
                Object v = data == null ? null : data.get(rf.toString());
                if (isBlank("", v)) {
                    anyEmpty = true;
                    break;
                }
            }
            if (!anyEmpty) {
                return null; // 字段都填了 → 不命中（负向对照，证明不是恒真）
            }
        }
        // block 直接命中；require 且任一字段为空 → 命中
        return buildHit(rule, field, then);
    }

    /** 组装一条命中：id / target_field / message 给可读兜底，options 只透传 {value,label}。 */
    private static RuleHit buildHit(Map<String, Object> rule, String field, Map<String, Object> then) {
        String ruleId = rule.get("id") instanceof String s ? s : "";
        String targetField = then.get("target_field") instanceof String tf && !tf.isBlank()
                ? tf : field;
        String message = then.get("message") instanceof String m && !m.isBlank()
                ? m : "该表单有业务规则未通过";
        List<Map<String, Object>> options = cleanRuleOptions(then.get("options"));
        return new RuleHit(ruleId, field, targetField, message, options);
    }

    /**
     * options 只透传 {value,label} 两个键（其余键丢掉）；非法（非 List 或单条缺 value）给空 List。
     */
    private static List<Map<String, Object>> cleanRuleOptions(Object optsObj) {
        if (!(optsObj instanceof List<?> opts) || opts.isEmpty()) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object o : opts) {
            if (!(o instanceof Map<?, ?> om)) {
                continue;
            }
            Object v = om.get("value");
            if (v == null) {
                continue; // 缺 value 视为非法条目，丢弃
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("value", v);
            m.put("label", om.get("label") == null ? "" : om.get("label"));
            out.add(m);
        }
        return out;
    }

    /**
     * 返回 schema 的 properties 键集合（任务 C 落库白名单用）。
     *
     * <p>解析失败或没有 properties 返回空集合（调用方据此决定是否裁剪）。</p>
     */
    public static Set<String> propertyNames(String schemaJson) {
        Set<String> names = new java.util.HashSet<>();
        if (schemaJson == null || schemaJson.isBlank()) {
            return names;
        }
        Map<String, Object> schema;
        try {
            schema = MAPPER.readValue(schemaJson, new TypeReference<LinkedHashMap<String, Object>>() {
            });
        } catch (Exception e) {
            return names;
        }
        if (!(schema instanceof Map)) {
            return names;
        }
        Object propsObj = schema.get("properties");
        if (!(propsObj instanceof Map<?, ?> props)) {
            return names;
        }
        for (Object k : props.keySet()) {
            names.add(String.valueOf(k));
        }
        return names;
    }
}
