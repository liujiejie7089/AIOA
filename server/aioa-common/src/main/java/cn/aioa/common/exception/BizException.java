package cn.aioa.common.exception;

/**
 * 业务异常：code 为业务错误码（非 0）。
 * 常用语义化工厂方法：badRequest / unauthorized / forbidden / notFound / notImplemented 等。
 */
public class BizException extends RuntimeException {

    private final int code;

    public BizException(int code, String message) {
        super(message);
        this.code = code;
    }

    public BizException(String message) {
        this(400, message);
    }

    public int getCode() {
        return code;
    }

    public static BizException badRequest(String message) {
        return new BizException(400, message);
    }

    public static BizException unauthorized(String message) {
        return new BizException(401, message);
    }

    public static BizException forbidden(String message) {
        return new BizException(403, message);
    }

    public static BizException notFound(String message) {
        return new BizException(404, message);
    }

    public static BizException notImplemented(String message) {
        return new BizException(501, message);
    }
}
