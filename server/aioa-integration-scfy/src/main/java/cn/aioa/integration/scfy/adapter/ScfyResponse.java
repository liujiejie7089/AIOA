package cn.aioa.integration.scfy.adapter;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * 归一化后的 scfy 响应。
 *
 * <p>scfy 有三套响应包装并存（文档 5.1）：{@code CommonResult}(code/msg/data)、
 * {@code ApiResult}(code/message/data)、{@code M}(success/msg/data)。
 * 本 record 把它们压成一个形状，让上层工具不必知道自己在跟哪套包装打交道。</p>
 *
 * <p><b>实测发现的一处陷阱</b>：同一个接口<b>成功用 {@code msg}、失败用 {@code message}</b>
 * （如 {@code {"code":500,"message":"..."}}）。只读其中一个键，就会在出错时拿到 null 信息，
 * 把「后端 SQL 异常」显示成「未知错误」—— 所以解析时两个键都读。</p>
 *
 * @param httpStatus  HTTP 状态码
 * @param code        业务码：0 成功 / -1 内部错误 / 1 认证失败 / 2 非法参数 / 3 业务错误 / 500 系统异常
 * @param message     业务信息（已合并 msg 与 message 两个键）
 * @param data        业务数据；成功时非空，失败时可能为 null
 * @param elapsedMs   耗时（毫秒）
 * @param truncated   响应体是否因超过 maxBytes 被截断
 */
public record ScfyResponse(int httpStatus,
                           Integer code,
                           String message,
                           JsonNode data,
                           long elapsedMs,
                           boolean truncated) {

    public boolean ok() {
        return httpStatus == 200 && code != null && code == 0;
    }

    /** 认证失败：HTTP 401，或业务码 1。 */
    public boolean authFailed() {
        return httpStatus == 401 || (code != null && code == 1);
    }

    /** 非法参数：业务码 2，或后端 Spring 的「Required parameter ... is not present」包装成的 500。 */
    public boolean illegalParam() {
        if (code != null && code == 2) {
            return true;
        }
        return message != null && message.contains("is not present");
    }

    /**
     * 给模型看的失败原因。
     * <p>区分「参数问题」与「系统问题」很关键：前者模型可自查重试，后者只能如实上报，
     * 混在一起会让模型反复重试一个它改不好的错误。</p>
     */
    public String reason() {
        if (ok()) {
            return "成功";
        }
        if (illegalParam()) {
            return "参数不合法或缺失：" + (message == null ? "（后端未提供说明）" : message);
        }
        if (authFailed()) {
            return "认证失败（Token 无效或过期）：" + (message == null ? "" : message);
        }
        if (code != null && code == -1) {
            return "scfy 内部错误：" + (message == null ? "" : message);
        }
        if (code != null && code == 3) {
            return "scfy 业务错误：" + (message == null ? "" : message);
        }
        return "scfy 返回异常（HTTP " + httpStatus + " / code " + code + "）："
                + (message == null ? "无说明" : message);
    }
}
