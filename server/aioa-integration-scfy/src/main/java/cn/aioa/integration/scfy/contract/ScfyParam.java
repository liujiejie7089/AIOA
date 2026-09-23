package cn.aioa.integration.scfy.contract;

import java.util.List;

/**
 * 一个接口参数的契约。
 *
 * <p><b>为什么参数契约要独立成 record、而不是写在工具的注解上</b>：
 * scfy 的参数有三类「文档与实测不一致」的情况（见 {@link ScfyCatalog}）——
 * 文档写 {@code shopId} 实际要 {@code id}、文档说「必填：无」实际必填 {@code travelId}、
 * 文档枚举漏了「联合国级」。如果契约只存在于 {@code @AioaToolParam} 注解里，
 * 这些<strong>实测校正就无处安放</strong>，下一个人照文档读代码又会写错一遍。
 * 所以：注解负责「模型看到的 Schema」，本 record 负责「校验器判定合法性的唯一依据」，
 * 两者由 {@code ScfyCatalog} 一处推导，不允许各自维护。</p>
 *
 * @param name        入参名（模型 function-calling 的字段名，即实测确认的真实参数名）
 * @param required    实测必填性。<b>以实测为准，不以文档表格为准</b>
 * @param type        JSON Schema 类型：string / integer / boolean
 * @param description 字段说明，会进 JSON Schema，是模型填对参数的唯一依据
 * @param enums       合法取值枚举；为空表示自由文本（如市州中文名）
 * @param example     典型取值，用于「参数不足时向用户追问」的话术示例
 * @param docNote     与文档的差异说明；为空表示文档与实测一致。
 *                    非空时既进工具 description（让模型知道），也进审计日志（让运维能追）
 */
public record ScfyParam(String name,
                        boolean required,
                        String type,
                        String description,
                        List<String> enums,
                        String example,
                        String docNote) {

    public static ScfyParam required(String name, String type, String description) {
        return new ScfyParam(name, true, type, description, null, null, null);
    }

    public static ScfyParam optional(String name, String type, String description) {
        return new ScfyParam(name, false, type, description, null, null, null);
    }

    public static ScfyParam requiredEnum(String name, String description, List<String> enums) {
        return new ScfyParam(name, true, "string", description, enums, null, null);
    }

    public static ScfyParam optionalEnum(String name, String description, List<String> enums) {
        return new ScfyParam(name, false, "string", description, enums, null, null);
    }

    /** 带「文档与实测不符」说明的参数 —— 校正过的一律走这个入口，避免静默漂移。 */
    public ScfyParam withDocNote(String note) {
        return new ScfyParam(name, required, type, description, enums, example, note);
    }

    public ScfyParam withExample(String ex) {
        return new ScfyParam(name, required, type, description, enums, ex, docNote);
    }

    public boolean hasEnums() {
        return enums != null && !enums.isEmpty();
    }

    /** 用于 JSON Schema 的枚举描述；无枚举时返回 null（Jackson 会省略该键）。 */
    public List<String> enumForSchema() {
        return hasEnums() ? enums : null;
    }
}
