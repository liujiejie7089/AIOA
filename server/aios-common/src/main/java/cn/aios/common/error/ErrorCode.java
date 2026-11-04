package cn.aios.common.error;

import org.springframework.http.HttpStatus;

/**
 * 统一错误码表：**一处定义「码 → HTTP 状态 → 给用户看的话 → 该怎么办」**。
 *
 * <p>设计约束（2026-11-04 定稿，见 docs/73）：</p>
 * <ol>
 *   <li><b>数字码向后兼容</b>：{@link #code()} 沿用既有 400/401/403/404/405/406/500/501，
 *       新增 409/422/429/502/504；既有调用方与 e2e 断言不受影响。</li>
 *   <li><b>机器码稳定</b>：{@link #errorCode()} 是 UPPER_SNAKE，前端按它判断分支，
 *       不再靠匹配中文文案（文案会改，码不会）。</li>
 *   <li><b>默认文案可直接展示</b>：不含类名、SQL、路径、堆栈；需要具体信息时由抛错方覆盖 message，
 *       但**必须**先过 {@link ErrorText#sanitize(String)}。</li>
 *   <li><b>每条都给「下一步」</b>：{@link #suggestion()} 必须是用户能动手做的事
 *       （去登录 / 改哪个字段 / 找谁 / 等多久），不允许写「请联系我们」这种废话。</li>
 * </ol>
 */
public enum ErrorCode {

    // ---------------- 校验类 ----------------
    VALIDATION_FAILED(400, "VALIDATION_FAILED", ErrorCategory.VALIDATION, HttpStatus.OK,
            "提交的内容有误，请按提示修改后重试",
            "检查标红的字段；数字类字段不要填单位或空格"),
    PARAM_INVALID(400, "PARAM_INVALID", ErrorCategory.VALIDATION, HttpStatus.BAD_REQUEST,
            "请求参数不合法",
            "确认参数名与类型；路径里的编号必须是数字"),
    PARAM_MISSING(400, "PARAM_MISSING", ErrorCategory.VALIDATION, HttpStatus.BAD_REQUEST,
            "缺少必填参数",
            "补齐必填项后重试"),
    BODY_UNREADABLE(400, "BODY_UNREADABLE", ErrorCategory.VALIDATION, HttpStatus.BAD_REQUEST,
            "请求内容不是合法的 JSON",
            "检查请求体格式（引号、逗号、括号）后重试"),
    METHOD_NOT_ALLOWED(405, "METHOD_NOT_ALLOWED", ErrorCategory.VALIDATION, HttpStatus.METHOD_NOT_ALLOWED,
            "该接口不支持这种请求方式",
            "确认用的是 GET / POST / PUT / DELETE 中的哪一种"),
    NOT_ACCEPTABLE(406, "NOT_ACCEPTABLE", ErrorCategory.VALIDATION, HttpStatus.NOT_ACCEPTABLE,
            "该接口不提供你要求的响应格式",
            "流式接口请用 Accept: text/event-stream；普通接口用 application/json"),

    // ---------------- 认证 / 权限 ----------------
    UNAUTHENTICATED(401, "UNAUTHENTICATED", ErrorCategory.AUTHENTICATION, HttpStatus.UNAUTHORIZED,
            "登录状态已失效，请重新登录",
            "重新登录后重试；若反复失效，检查系统时间是否准确"),
    TOKEN_INVALID(401, "TOKEN_INVALID", ErrorCategory.AUTHENTICATION, HttpStatus.UNAUTHORIZED,
            "登录凭证无效",
            "退出后重新登录"),
    PERMISSION_DENIED(403, "PERMISSION_DENIED", ErrorCategory.PERMISSION, HttpStatus.FORBIDDEN,
            "当前账号没有这个操作的权限",
            "换用有权限的账号，或让管理员在「角色权限」里为你开通"),
    TENANT_FORBIDDEN(403, "TENANT_FORBIDDEN", ErrorCategory.PERMISSION, HttpStatus.FORBIDDEN,
            "该数据不属于你所在单位，无法访问",
            "确认登录的单位是否正确（右上角可切换）"),

    // ---------------- 资源 ----------------
    RESOURCE_NOT_FOUND(404, "RESOURCE_NOT_FOUND", ErrorCategory.NOT_FOUND, HttpStatus.NOT_FOUND,
            "要找的内容不存在或已被删除",
            "刷新列表后重试；确认编号是否正确"),
    API_NOT_FOUND(404, "API_NOT_FOUND", ErrorCategory.NOT_FOUND, HttpStatus.NOT_FOUND,
            "接口地址不存在",
            "核对接口路径与版本前缀（如 /api/v1）；前端版本与服务端版本是否一致"),

    // ---------------- 冲突 / 限流 ----------------
    STATE_CONFLICT(409, "STATE_CONFLICT", ErrorCategory.CONFLICT, HttpStatus.CONFLICT,
            "数据状态已变化，本次操作没有生效",
            "刷新页面看到最新状态后再操作一次"),
    RATE_LIMITED(429, "RATE_LIMITED", ErrorCategory.RATE_LIMIT, HttpStatus.TOO_MANY_REQUESTS,
            "操作太频繁，已被限流",
            "等 1 分钟再试；批量操作请分批执行"),

    // ---------------- 外部依赖 ----------------
    MODEL_UPSTREAM_ERROR(502, "MODEL_UPSTREAM_ERROR", ErrorCategory.UPSTREAM, HttpStatus.OK,
            "模型服务本次没有返回结果",
            "稍后重试；连续失败请在「模型配置」里点「连通性校验」确认模型可用"),
    MODEL_NOT_FOUND(502, "MODEL_NOT_FOUND", ErrorCategory.UPSTREAM, HttpStatus.OK,
            "配置的模型已下线或不存在",
            "管理员在「模型配置」里把模型名换成供应商当前提供的名称（可用其 /models 列表确认）"),
    MODEL_AUTH_FAILED(502, "MODEL_AUTH_FAILED", ErrorCategory.UPSTREAM, HttpStatus.OK,
            "模型密钥无效或没有调用权限",
            "到「我的 → 模型账号」检查这个账号的 API Key；或改用平台默认模型"),
    MODEL_RATE_LIMITED(502, "MODEL_RATE_LIMITED", ErrorCategory.UPSTREAM, HttpStatus.OK,
            "模型调用过于频繁",
            "等几十秒再试；长期不足请联系管理员提高额度"),
    MODEL_TIMEOUT(502, "MODEL_TIMEOUT", ErrorCategory.UPSTREAM, HttpStatus.OK,
            "模型响应超时",
            "稍后重试；把问题拆小一点（或减少附件）"),
    CONNECTOR_ERROR(502, "CONNECTOR_ERROR", ErrorCategory.UPSTREAM, HttpStatus.OK,
            "连接的外部应用调用失败",
            "到「连接器」确认状态为「已连接」；重新授权后再试"),

    // ---------------- 服务内部 ----------------
    INTERNAL_ERROR(500, "INTERNAL_ERROR", ErrorCategory.INTERNAL, HttpStatus.INTERNAL_SERVER_ERROR,
            "服务内部出错了，本次操作没有完成",
            "稍后重试；仍失败请把「错误编号」发给管理员，他能凭它定位到这次请求"),
    NOT_IMPLEMENTED(501, "NOT_IMPLEMENTED", ErrorCategory.INTERNAL, HttpStatus.OK,
            "该功能尚未开放",
            "先使用现有功能；需要时联系管理员确认上线计划");

    private final int code;
    private final String errorCode;
    private final ErrorCategory category;
    private final HttpStatus httpStatus;
    private final String defaultMessage;
    private final String suggestion;

    ErrorCode(int code, String errorCode, ErrorCategory category, HttpStatus httpStatus,
              String defaultMessage, String suggestion) {
        this.code = code;
        this.errorCode = errorCode;
        this.category = category;
        this.httpStatus = httpStatus;
        this.defaultMessage = defaultMessage;
        this.suggestion = suggestion;
    }

    public int code() {
        return code;
    }

    public String errorCode() {
        return errorCode;
    }

    public ErrorCategory category() {
        return category;
    }

    public HttpStatus httpStatus() {
        return httpStatus;
    }

    public String defaultMessage() {
        return defaultMessage;
    }

    public String suggestion() {
        return suggestion;
    }

    /**
     * 按数字码找**最贴切**的一类（只用于兼容旧代码里裸传 400/403 的场景）。
     * 同码多义时取「通用且用户可自助」的那一个。
     */
    public static ErrorCode ofCode(int code) {
        return switch (code) {
            case 400 -> VALIDATION_FAILED;
            case 401 -> UNAUTHENTICATED;
            case 403 -> PERMISSION_DENIED;
            case 404 -> RESOURCE_NOT_FOUND;
            case 405 -> METHOD_NOT_ALLOWED;
            case 406 -> NOT_ACCEPTABLE;
            case 409 -> STATE_CONFLICT;
            case 422 -> VALIDATION_FAILED;
            case 429 -> RATE_LIMITED;
            case 501 -> NOT_IMPLEMENTED;
            case 502, 503, 504 -> MODEL_UPSTREAM_ERROR;
            default -> INTERNAL_ERROR;
        };
    }
}
