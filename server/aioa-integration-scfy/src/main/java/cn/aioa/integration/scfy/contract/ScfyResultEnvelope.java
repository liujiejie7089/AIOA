package cn.aioa.integration.scfy.contract;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * scfy 工具返回值的<b>统一信封</b> —— 字段名与含义的唯一事实源。
 *
 * <p><b>为什么要有这个类</b>：在此之前，信封的键名是散落在
 * {@code ScfyToolSupport} 里的一串字符串字面量，而「返回结构」又要对外声明给模型看。
 * 两边各写一份的结果必然是漂移：改了实现忘了改声明，模型就按一个不存在的字段取值、
 * 拿到 null 却以为「这条数据没有该属性」。把键名收成常量后，
 * {@link #schema()} 声明的结构与 {@code ScfyToolSupport} 实际产出的结构
 * <b>在编译期就是同一份东西</b>，不可能不一致。</p>
 *
 * <p>信封分两半：<b>固定字段</b>（本类声明的 17 个，所有工具都一样）与
 * <b>{@code data} 字段</b>（每个接口各不相同，形状来自真实调用实测，
 * 见 {@code resources/scfy/return-shape.json}）。</p>
 */
public final class ScfyResultEnvelope {

    private ScfyResultEnvelope() {
    }

    // ==================== 字段名（与 ScfyToolSupport 同源）====================

    /** 调用是否成功。false 时必有 {@link #ERRORS}。 */
    public static final String OK = "ok";
    /** 契约接口 id（如 project_list_by_area），用于把结论追回到具体接口。 */
    public static final String ENDPOINT = "endpoint";
    /** 数据来源（系统名 + 接口路径），审计里一眼看出这条数据从哪来。 */
    public static final String SOURCE = "source";
    /** 业务数据。形状随接口而异，见接口自己的返回结构。 */
    public static final String DATA = "data";
    /** 失败原因（人类可读，可能多条）。 */
    public static final String ERRORS = "errors";
    /** 对方返回的 HTTP 状态码（失败时才有）。 */
    public static final String HTTP_STATUS = "httpStatus";
    /** 对方返回的业务码（失败时才有）。 */
    public static final String CODE = "code";
    /** 条目是否被裁剪（超过单次返回上限）。 */
    public static final String TRUNCATED = "truncated";
    /** 被裁剪的字段名（数组藏在某个字段里时才有）。 */
    public static final String TRUNCATED_FIELD = "truncatedField";
    /** 裁剪前的真实总条数 —— 让模型知道「这不是全部」。 */
    public static final String TOTAL_ITEMS = "totalItems";
    /** 实际返回的条数。 */
    public static final String RETURNED_ITEMS = "returnedItems";
    /** 响应体是否被字节上限截断（与条目裁剪是两件事）。 */
    public static final String RESPONSE_TRUNCATED = "responseTruncated";
    /** 调用耗时（毫秒）。 */
    public static final String ELAPSED_MS = "elapsedMs";
    /** 文档与实测不一致的提示 —— 必须让模型看到，否则会照文档传错参数。 */
    public static final String DOC_MISMATCH = "docMismatch";
    /** 参数层面的警示（如「该参数传了等于没传」）。 */
    public static final String WARNINGS = "warnings";
    /** 缺必填参数，需要向用户追问。 */
    public static final String NEED_USER_INPUT = "needUserInput";
    /** 追问话术（可直接转述给用户）。 */
    public static final String ASK_USER = "askUser";

    /** 字段名 → 说明，供生成 JSON Schema 与写文档时复用。 */
    private static final Map<String, String> DESCRIPTIONS = new LinkedHashMap<>();

    static {
        DESCRIPTIONS.put(OK, "调用是否成功；false 时 errors 必有值");
        DESCRIPTIONS.put(ENDPOINT, "契约接口 id，可据此追到具体接口");
        DESCRIPTIONS.put(SOURCE, "数据来源：系统名 + 接口路径");
        DESCRIPTIONS.put(DATA, "业务数据；形状随接口而异，见本接口的返回结构");
        DESCRIPTIONS.put(ERRORS, "失败原因（人类可读，可能多条）");
        DESCRIPTIONS.put(HTTP_STATUS, "对方返回的 HTTP 状态码（仅失败时）");
        DESCRIPTIONS.put(CODE, "对方返回的业务码（仅失败时）");
        DESCRIPTIONS.put(TRUNCATED, "条目是否被裁剪（单次返回有上限）");
        DESCRIPTIONS.put(TRUNCATED_FIELD, "被裁剪的字段名（数组嵌在字段里时）");
        DESCRIPTIONS.put(TOTAL_ITEMS, "裁剪前的真实总条数");
        DESCRIPTIONS.put(RETURNED_ITEMS, "实际返回的条数");
        DESCRIPTIONS.put(RESPONSE_TRUNCATED, "响应体是否被字节上限截断");
        DESCRIPTIONS.put(ELAPSED_MS, "调用耗时（毫秒）");
        DESCRIPTIONS.put(DOC_MISMATCH, "接口文档与生产实测不一致之处");
        DESCRIPTIONS.put(WARNINGS, "参数层面的警示（如某参数传了等于没传）");
        DESCRIPTIONS.put(NEED_USER_INPUT, "缺少必填参数，需要向用户追问");
        DESCRIPTIONS.put(ASK_USER, "追问话术，可直接转述给用户");
    }

    public static Map<String, String> descriptions() {
        return Map.copyOf(DESCRIPTIONS);
    }

    /** 必须出现的字段（其余为按情况出现）。 */
    public static List<String> alwaysPresent() {
        return List.of(OK, ENDPOINT, SOURCE);
    }

    /**
     * 生成信封的 JSON Schema。
     *
     * @param dataShape 该接口 {@code data} 的实测形状（可为 null，表示尚未观测到）
     */
    public static Map<String, Object> schema(Map<String, Object> dataShape) {
        Map<String, Object> props = new LinkedHashMap<>();
        for (Map.Entry<String, String> e : DESCRIPTIONS.entrySet()) {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("type", jsonType(e.getKey()));
            p.put("description", e.getValue());
            props.put(e.getKey(), p);
        }
        Map<String, Object> dataProp = null;
        if (dataShape != null && !dataShape.isEmpty()) {
            dataProp = new LinkedHashMap<>();
            dataProp.put("type", jsonType(DATA));
            dataProp.put("description", DESCRIPTIONS.get(DATA));
            dataProp.put("x-scfy-shape", dataShape);
            props.put(DATA, dataProp);
        }

        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("x-scfy-envelope", "scfy 工具统一信封；data 的形状随接口而异，见 data 的 x-scfy-shape");
        schema.put("properties", props);
        schema.put("required", alwaysPresent());
        return schema;
    }

    private static String jsonType(String key) {
        return switch (key) {
            case OK, TRUNCATED, RESPONSE_TRUNCATED, NEED_USER_INPUT -> "boolean";
            case HTTP_STATUS, CODE, ELAPSED_MS, TOTAL_ITEMS, RETURNED_ITEMS -> "integer";
            case ERRORS, DOC_MISMATCH, WARNINGS -> "array";
            case DATA -> "object";
            default -> "string";
        };
    }
}
