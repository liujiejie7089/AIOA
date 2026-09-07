package cn.aioa.common.resp;

import cn.aioa.common.trace.TraceId;
import lombok.Data;

/**
 * 统一响应体：{code, message, data, traceId}；code = 0 表示成功，业务错误非 0。
 */
@Data
public class ApiResponse<T> {

    public static final int CODE_OK = 0;

    private int code = CODE_OK;
    private String message = "ok";
    private T data;
    private String traceId = TraceId.get();

    public ApiResponse() {
    }

    public ApiResponse(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
        this.traceId = TraceId.get();
    }

    public static <T> ApiResponse<T> ok() {
        return new ApiResponse<>(CODE_OK, "ok", null);
    }

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(CODE_OK, "ok", data);
    }

    public static <T> ApiResponse<T> fail(int code, String message) {
        return new ApiResponse<>(code, message, null);
    }

    public static <T> ApiResponse<T> fail(int code, String message, T data) {
        return new ApiResponse<>(code, message, data);
    }
}
