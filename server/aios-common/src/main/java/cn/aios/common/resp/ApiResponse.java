package cn.aios.common.resp;

import cn.aios.common.error.ErrorCategory;
import cn.aios.common.error.ErrorCode;
import cn.aios.common.trace.TraceId;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.util.List;

/**
 * 统一响应体：{@code code / message / data / traceId} + 错误附加字段。
 *
 * <p><b>成功</b>：{@code code = 0}，{@code message = "ok"}，只有 {@code data}。</p>
 *
 * <p><b>失败</b>（字段约定见 docs/73）：</p>
 * <pre>
 * {
 *   "code": 403,                       // 数字码，向后兼容既有调用方与 e2e 断言
 *   "errorCode": "PERMISSION_DENIED",  // 机器码，稳定；前端按它分支，不匹配中文
 *   "category": "PERMISSION",          // 分类：VALIDATION/AUTHENTICATION/PERMISSION/...
 *   "message": "当前账号没有这个操作的权限",   // 给人看的一句话，不含技术细节
 *   "suggestion": "换用有权限的账号，或让管理员…", // 可操作建议
 *   "details": [{"field":"apiKey","message":"不能为空"}], // 仅校验类
 *   "traceId": "1ffc126d99b14ac6",     // 错误编号：用户报给运维，日志里能定位
 *   "data": null
 * }
 * </pre>
 *
 * <p>新增字段全部 {@code @JsonInclude(NON_NULL)}：成功响应不多出噪音字段，
 * 旧的解析代码不受影响。</p>
 */
@Data
public class ApiResponse<T> {

    public static final int CODE_OK = 0;

    private int code = CODE_OK;
    private String message = "ok";
    private T data;
    private String traceId = TraceId.get();

    /** 机器可读错误码（UPPER_SNAKE）；成功时为 null。 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String errorCode;

    /** 错误分类；成功时为 null。 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private ErrorCategory category;

    /** 可操作建议；成功时为 null。 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String suggestion;

    /** 字段级错误（仅校验失败时出现）。 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private List<FieldErrorItem> details;

    public ApiResponse() {
    }

    public ApiResponse(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
        this.traceId = TraceId.get();
    }

    /** 字段级错误项（与 common.error.ErrorText.FieldError 同构，独立成类便于序列化）。 */
    @Data
    public static class FieldErrorItem {
        private String field;
        private String message;

        public FieldErrorItem() {
        }

        public FieldErrorItem(String field, String message) {
            this.field = field;
            this.message = message;
        }
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

    /** 用错误码表构造：message/suggestion 取默认值。 */
    public static <T> ApiResponse<T> fail(ErrorCode ec) {
        return fail(ec, null, null, null);
    }

    /**
     * 用错误码表构造，允许覆盖文案与建议。
     *
     * @param ec         错误码（决定 code / errorCode / category / 默认文案与建议）
     * @param message    具体文案；null 或空白则用默认文案（调用方负责先清洗）
     * @param suggestion 具体建议；null 或空白则用默认建议
     * @param details    字段级错误；无则 null
     */
    public static <T> ApiResponse<T> fail(ErrorCode ec, String message, String suggestion,
                                          List<FieldErrorItem> details) {
        ApiResponse<T> r = new ApiResponse<>();
        r.setCode(ec.code());
        r.setErrorCode(ec.errorCode());
        r.setCategory(ec.category());
        r.setMessage(message == null || message.isBlank() ? ec.defaultMessage() : message);
        r.setSuggestion(suggestion == null || suggestion.isBlank() ? ec.suggestion() : suggestion);
        if (details != null && !details.isEmpty()) {
            r.setDetails(details);
        }
        return r;
    }
}
