package cn.aios.common.exception;

import cn.aios.common.error.ErrorCode;
import cn.aios.common.error.ErrorText;

import java.util.List;

/**
 * 业务异常：抛错方**只需选一个错误码 + 一句人话**，返回结构与日志由统一出口负责。
 *
 * <p>兼容性：既有的 {@code new BizException(400, "…")} 与 {@link #getCode()} 保持不变，
 * 数字码会映射到最贴切的 {@link ErrorCode}（见 {@link ErrorCode#ofCode(int)}）。</p>
 *
 * <p>用法约定（docs/73 §4）：</p>
 * <pre>
 * throw BizException.badRequest("模型名不能为空");                       // 校验
 * throw BizException.of(ErrorCode.MODEL_NOT_FOUND, "模型「X」已下线")     // 外部依赖
 *         .withSuggestion("在「模型配置」里改用当前可用的模型名");
 * </pre>
 */
public class BizException extends RuntimeException {

    private final ErrorCode errorCode;
    private final String suggestion;
    private final transient List<ErrorText.FieldError> details;

    public BizException(int code, String message) {
        super(message);
        this.errorCode = ErrorCode.ofCode(code);
        this.suggestion = null;
        this.details = List.of();
    }

    public BizException(ErrorCode errorCode, String message) {
        this(errorCode, message, null, List.of(), null);
    }

    public BizException(ErrorCode errorCode, String message, String suggestion,
                        List<ErrorText.FieldError> details, Throwable cause) {
        super(message, cause);
        this.errorCode = errorCode == null ? ErrorCode.VALIDATION_FAILED : errorCode;
        this.suggestion = suggestion;
        this.details = details == null ? List.of() : details;
    }

    public BizException(String message) {
        this(400, message);
    }

    /** 数字码（= errorCode.code()），既有调用方依赖它。 */
    public int getCode() {
        return errorCode.code();
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }

    public String getSuggestion() {
        return suggestion;
    }

    public List<ErrorText.FieldError> getDetails() {
        return details;
    }

    /** 补一句「该怎么办」；返回自身便于链式抛出。 */
    public BizException withSuggestion(String suggestion) {
        return new BizException(errorCode, getMessage(), suggestion, details, getCause());
    }

    /** 附上字段级错误（前端据此标红具体输入框）。 */
    public BizException withDetails(List<ErrorText.FieldError> details) {
        return new BizException(errorCode, getMessage(), suggestion, details, getCause());
    }

    public static BizException of(ErrorCode errorCode, String message) {
        return new BizException(errorCode, message);
    }

    public static BizException badRequest(String message) {
        return new BizException(ErrorCode.VALIDATION_FAILED, message);
    }

    public static BizException unauthorized(String message) {
        return new BizException(ErrorCode.UNAUTHENTICATED, message);
    }

    public static BizException forbidden(String message) {
        return new BizException(ErrorCode.PERMISSION_DENIED, message);
    }

    public static BizException notFound(String message) {
        return new BizException(ErrorCode.RESOURCE_NOT_FOUND, message);
    }

    public static BizException conflict(String message) {
        return new BizException(ErrorCode.STATE_CONFLICT, message);
    }

    /** 额度用完：留在 403（兼容既有兜底），但分类归 RATE_LIMIT —— 别让用户以为是自己没权限。 */
    public static BizException quotaExceeded(String message) {
        return new BizException(ErrorCode.QUOTA_EXCEEDED, message);
    }

    public static BizException notImplemented(String message) {
        return new BizException(ErrorCode.NOT_IMPLEMENTED, message);
    }

    /** 外部依赖（模型/连接器）失败：文案必须是人话，原始上游信息只进日志。 */
    public static BizException upstream(ErrorCode errorCode, String message) {
        return new BizException(errorCode, message);
    }
}
