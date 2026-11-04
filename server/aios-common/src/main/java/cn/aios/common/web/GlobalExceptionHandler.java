package cn.aios.common.web;

import cn.aios.common.error.ErrorCode;
import cn.aios.common.error.ErrorText;
import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.common.trace.TraceId;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.TypeMismatchException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.validation.FieldError;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.ArrayList;
import java.util.List;

/**
 * 全局异常出口：**所有异常在这里归一次类、洗一次文案、记一次日志**。
 *
 * <p>三段职责（docs/73）：</p>
 * <ol>
 *   <li><b>归类</b>：异常 → {@link ErrorCode}。归错类的代价很实际 ——
 *       路径写错显示「服务内部错误」会让人去查后端，而不是查自己的 URL。</li>
 *   <li><b>清洗</b>：对外只给「一句人话 + 一句建议 + 错误编号」，
 *       类名、SQL、绝对路径、堆栈、密钥片段一律不外发（{@link ErrorText}）。</li>
 *   <li><b>留痕</b>：原始信息完整进日志 —— 4xx 用 WARN（含原始 message），
 *       5xx 用 ERROR（含堆栈）。日志与响应通过同一个 traceId 关联，
 *       用户报「错误编号」即可定位到这次请求。</li>
 * </ol>
 *
 * <p>401/403 的认证/授权路径由 security 模块的 entryPoint / accessDeniedHandler 处理
 * （同一套 {@link ErrorCode}，见 SecurityConfig），本类不引入 spring-security 依赖。</p>
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /** 仅用于把错误体序列化成 SSE 的一行 data（SSE 不能带换行，故用单行 JSON）。 */
    private static final ObjectMapper MAPPER = new ObjectMapper();

    // ==================================================================
    // 业务异常：抛错方已给出人话，这里只做兜底清洗 + 记录
    // ==================================================================
    @ExceptionHandler(BizException.class)
    public ResponseEntity<?> handleBiz(BizException e, HttpServletRequest request) {
        ErrorCode ec = e.getErrorCode();
        String raw = e.getMessage();
        String message = ErrorText.sanitize(raw, ec.defaultMessage());
        String suggestion = e.getSuggestion();
        List<ApiResponse.FieldErrorItem> details = toItems(e.getDetails());

        // 业务异常默认不是「故障」，但**原始信息必须留痕**：排查时常常只有这一行能看出
        // 是「用户填错」还是「我们算错」。密钥在落盘前脱敏。
        log.warn("[{}] {} {} -> {} {} | 原始: {}", TraceId.get(), request.getMethod(),
                safeUri(request), ec.errorCode(), message, ErrorText.maskSecrets(raw));
        if (e.getCause() != null) {
            log.warn("[{}] {} 的根因如下（仅供排查）", TraceId.get(), ec.errorCode(), e.getCause());
        }

        return respond(request, ec.httpStatus(), ApiResponse.fail(ec, message, suggestion, details));
    }

    // ==================================================================
    // 校验类
    // ==================================================================
    @ExceptionHandler({MethodArgumentNotValidException.class, BindException.class})
    public ResponseEntity<?> handleValidation(BindException e, HttpServletRequest request) {
        List<ApiResponse.FieldErrorItem> details = new ArrayList<>();
        for (FieldError fe : e.getBindingResult().getFieldErrors()) {
            details.add(new ApiResponse.FieldErrorItem(fe.getField(),
                    ErrorText.fieldMessage(fe.getDefaultMessage())));
        }
        String message = details.isEmpty()
                ? ErrorCode.VALIDATION_FAILED.defaultMessage()
                : "提交的内容有误：" + details.get(0).getMessage();
        log.warn("[{}] {} {} -> VALIDATION_FAILED | 字段: {} | 原始: {}", TraceId.get(),
                request.getMethod(), safeUri(request), details, ErrorText.maskSecrets(e.getMessage()));
        return respond(request, ErrorCode.VALIDATION_FAILED.httpStatus(),
                ApiResponse.fail(ErrorCode.VALIDATION_FAILED, message, null, details));
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<?> handleMissingParam(MissingServletRequestParameterException e,
                                                HttpServletRequest request) {
        String field = e.getParameterName();
        String message = "缺少必填参数：" + field;
        List<ApiResponse.FieldErrorItem> details =
                List.of(new ApiResponse.FieldErrorItem(field, "不能为空"));
        log.warn("[{}] {} {} -> PARAM_MISSING | {} | 原始: {}", TraceId.get(), request.getMethod(),
                safeUri(request), field, ErrorText.maskSecrets(e.getMessage()));
        return respond(request, ErrorCode.PARAM_MISSING.httpStatus(),
                ApiResponse.fail(ErrorCode.PARAM_MISSING, message,
                        "补上「" + field + "」后重试", details));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<?> handleUnreadable(HttpMessageNotReadableException e,
                                              HttpServletRequest request) {
        // Jackson 的原文含类名与偏移量（Could not read document / JSON parse error ...）
        // 对用户毫无用处；日志里留全量，界面上只说「格式不对」。
        log.warn("[{}] {} {} -> BODY_UNREADABLE | 原始: {}", TraceId.get(), request.getMethod(),
                safeUri(request), ErrorText.maskSecrets(e.getMessage()));
        return respond(request, ErrorCode.BODY_UNREADABLE.httpStatus(),
                ApiResponse.fail(ErrorCode.BODY_UNREADABLE, null,
                        "检查请求体的引号、逗号与括号是否成对", null));
    }

    /**
     * 路径 / 查询参数类型不匹配 → 400（而不是 500）。
     *
     * <p>典型场景：{@code /api/v1/workflow/tasks/{id}/decide} 的 id 写成非数字。
     * 以前会落到兜底被包成「服务内部错误」，于是「客户端传错参数」看起来像「后端崩了」，
     * 排查方向直接被带偏。</p>
     */
    @ExceptionHandler({MethodArgumentTypeMismatchException.class, TypeMismatchException.class})
    public ResponseEntity<?> handleTypeMismatch(TypeMismatchException e, HttpServletRequest request) {
        String field = e.getPropertyName() == null ? "参数" : e.getPropertyName();
        String expected = humanType(e.getRequiredType());
        // 保留「类型」二字：scripts/e2e_v45_misc_fixes.py 的 D2-1b 按它判断「归错类」，
        // 文案可以更友好，但「这是类型问题而不是服务崩溃」这个信号不能丢。
        String message = "参数类型不正确：「" + field + "」应为" + expected;
        log.warn("[{}] {} {} -> PARAM_INVALID | {} | 原始: {}", TraceId.get(), request.getMethod(),
                safeUri(request), message, ErrorText.maskSecrets(e.getMessage()));
        return respond(request, ErrorCode.PARAM_INVALID.httpStatus(),
                ApiResponse.fail(ErrorCode.PARAM_INVALID, message,
                        "按接口文档改正「" + field + "」的" + expected + "格式", null));
    }

    /** 裸 IllegalArgumentException：既是历史约定（铁律 29 说它会落 500），也确实常是入参问题。 */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<?> handleIllegalArgument(IllegalArgumentException e,
                                                   HttpServletRequest request) {
        String message = ErrorText.sanitize(e.getMessage(), ErrorCode.PARAM_INVALID.defaultMessage());
        log.warn("[{}] {} {} -> PARAM_INVALID | 原始: {}", TraceId.get(), request.getMethod(),
                safeUri(request), ErrorText.maskSecrets(e.getMessage()));
        return respond(request, ErrorCode.PARAM_INVALID.httpStatus(),
                ApiResponse.fail(ErrorCode.PARAM_INVALID, message, null, null));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<?> handleMethod(HttpRequestMethodNotSupportedException e,
                                          HttpServletRequest request) {
        log.warn("[{}] {} {} -> METHOD_NOT_ALLOWED | 支持: {}", TraceId.get(), request.getMethod(),
                safeUri(request), e.getSupportedHttpMethods());
        return respond(request, ErrorCode.METHOD_NOT_ALLOWED.httpStatus(),
                ApiResponse.fail(ErrorCode.METHOD_NOT_ALLOWED, null,
                        "该接口支持的请求方式：" + e.getSupportedHttpMethods(), null));
    }

    /** 路径不存在 → 404，而不是 500（拼错路径不该看起来像后端崩溃）。 */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<?> handleNotFound(NoResourceFoundException e, HttpServletRequest request) {
        String uri = pathOnly(AiosRequestAttributes.originalUri(request));
        log.warn("[{}] {} {} -> API_NOT_FOUND", TraceId.get(), request.getMethod(), uri);
        return respond(request, ErrorCode.API_NOT_FOUND.httpStatus(),
                ApiResponse.fail(ErrorCode.API_NOT_FOUND, "接口不存在：" + uri,
                        "核对接口路径；前端版本与后端是否一致", null));
    }

    /** 响应类型协商失败 → 406（客户端 Accept 写错不该看起来像后端崩溃）。 */
    @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
    public ResponseEntity<?> handleNotAcceptable(HttpMediaTypeNotAcceptableException e,
                                                 HttpServletRequest request) {
        log.warn("[{}] {} {} -> NOT_ACCEPTABLE | 原始: {}", TraceId.get(), request.getMethod(),
                safeUri(request), e.getMessage());
        return respond(request, ErrorCode.NOT_ACCEPTABLE.httpStatus(),
                ApiResponse.fail(ErrorCode.NOT_ACCEPTABLE, null, null, null));
    }

    // ==================================================================
    // 兜底
    // ==================================================================
    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> handleServer(Exception e, HttpServletRequest request) {
        // 客户端主动断开（刷新页面 / 关闭 H5 / 手机切网）不是服务端故障：
        // 原先它会被记成 ERROR 并触发「写 500 JSON 到已关闭的连接」的二次异常
        // （HttpMessageNotWritableException: No converter ... text/html），把日志淹掉。
        if (isClientAbort(e)) {
            log.debug("客户端已断开，忽略本次异常：{} {}", request.getMethod(), safeUri(request));
            return ResponseEntity.status(499).build();
        }
        // 数据完整性冲突（唯一键、外键、锁等待）→ 409，且**绝不把 SQL 带出去**：
        // 这类异常的消息里直接写着表名与列名，属于典型的信息泄漏。
        if (isDataIntegrity(e)) {
            log.warn("[{}] {} {} -> STATE_CONFLICT | 原始: {}", TraceId.get(), request.getMethod(),
                    safeUri(request), ErrorText.maskSecrets(rootMessage(e)));
            return respond(request, ErrorCode.STATE_CONFLICT.httpStatus(),
                    ApiResponse.fail(ErrorCode.STATE_CONFLICT,
                            "数据处理时发生冲突（可能重复提交，或该记录已被修改）",
                            "刷新后重新提交；若反复出现，可能是并发操作了同一条数据", null));
        }

        // 5xx：对用户只说「我们的问题 + 错误编号」，堆栈只进日志。
        log.error("[{}] 未处理异常 {} {}", TraceId.get(), request.getMethod(), safeUri(request), e);
        return respond(request, ErrorCode.INTERNAL_ERROR.httpStatus(),
                ApiResponse.fail(ErrorCode.INTERNAL_ERROR, null,
                        "稍后重试；仍失败请把错误编号 " + TraceId.get() + " 发给管理员", null));
    }

    // ==================================================================
    // 公共出口
    // ==================================================================

    /**
     * 统一出口：普通请求回 JSON，SSE 请求回一条 {@code event: error} 帧。
     *
     * <p>为什么必须分开：{@code /api/v1/runs/{id}/events} 等方法声明了
     * {@code produces = text/event-stream}，浏览器也只会发 {@code Accept: text/event-stream}。
     * 若异常处理器仍返回 {@code ApiResponse}(JSON)，Spring 在消息转换阶段找不到可写表示，
     * 抛 {@code HttpMediaTypeNotAcceptableException}，于是<b>错误处理器本身失败</b>。</p>
     *
     * <p>SSE 分支用 HTTP 200：EventSource 对非 2xx 只会报笼统的连接失败、且会不断重连；
     * 200 + 明确错误帧可以把「为什么失败」原样送到前端。</p>
     */
    private static ResponseEntity<?> respond(HttpServletRequest request, HttpStatus status,
                                             ApiResponse<Void> body) {
        if (wantsEventStream(request)) {
            try {
                String json = MAPPER.writeValueAsString(body);
                return ResponseEntity.ok()
                        .contentType(MediaType.TEXT_EVENT_STREAM)
                        .header("Cache-Control", "no-cache")
                        .body("event: error\ndata: " + json + "\n\n");
            } catch (Exception ser) {
                log.warn("错误体序列化失败，降级为纯文本 SSE 帧：{}", ser.getMessage());
                return ResponseEntity.ok()
                        .contentType(MediaType.TEXT_EVENT_STREAM)
                        .body("event: error\ndata: {\"code\":" + body.getCode()
                                + ",\"errorCode\":\"" + body.getErrorCode() + "\"}\n\n");
            }
        }
        return ResponseEntity.status(status).body(body);
    }

    private static List<ApiResponse.FieldErrorItem> toItems(List<ErrorText.FieldError> in) {
        if (in == null || in.isEmpty()) {
            return null;
        }
        List<ApiResponse.FieldErrorItem> out = new ArrayList<>();
        for (ErrorText.FieldError f : ErrorText.flatten(in)) {
            out.add(new ApiResponse.FieldErrorItem(f.field(), f.message()));
        }
        return out;
    }

    /** 只保留路径，丢掉查询串（里面可能带 token / 手机号）。 */
    private static String pathOnly(String uri) {
        if (uri == null) {
            return "/";
        }
        int q = uri.indexOf('?');
        String p = q >= 0 ? uri.substring(0, q) : uri;
        return p.length() > 200 ? p.substring(0, 200) + "…" : p;
    }

    private static String safeUri(HttpServletRequest request) {
        return pathOnly(AiosRequestAttributes.originalUri(request));
    }

    /** 把 Java 类型名翻成用户能理解的词，避免出现 {@code java.lang.Long}。 */
    private static String humanType(Class<?> type) {
        if (type == null) {
            return "正确的格式";
        }
        String n = type.getSimpleName();
        return switch (n) {
            case "Integer", "Long", "Short", "BigInteger" -> "整数";
            case "Double", "Float", "BigDecimal" -> "数字";
            case "Boolean" -> "true/false";
            case "LocalDate" -> "日期（2026-11-04）";
            case "LocalDateTime" -> "时间（2026-11-04T09:30:00）";
            default -> "正确的格式";
        };
    }

    private static String rootMessage(Throwable e) {
        Throwable t = e;
        int guard = 0;
        while (t.getCause() != null && guard++ < 8) {
            t = t.getCause();
        }
        return t.getMessage();
    }

    /** 请求是否只接受 SSE（浏览器 EventSource / fetch 流式订阅）。 */
    private static boolean wantsEventStream(HttpServletRequest request) {
        String accept = request.getHeader("Accept");
        return accept != null && accept.contains("text/event-stream");
    }

    /**
     * 判断异常链里是否存在「对端已关闭」类异常。
     *
     * <p>按类名匹配而不直接 import Tomcat 类型：common 模块不保证编译期可见
     * tomcat-embed-core（各 web 模块自己带 starter），写死 import 会让 common 单独编译失败。</p>
     */
    private static boolean isClientAbort(Throwable e) {
        return chainHas(e, "ClientAbortException", "AsyncRequestNotUsableException",
                "EofException", "BrokenPipeException")
                || chainMessageHas(e, "Connection reset by peer", "Broken pipe");
    }

    /** 数据完整性/唯一键冲突（同样用类名匹配，避免 common 依赖 spring-jdbc）。 */
    private static boolean isDataIntegrity(Throwable e) {
        return chainHas(e, "DataIntegrityViolationException", "DuplicateKeyException",
                "ConstraintViolationException", "SQLIntegrityConstraintViolationException",
                "CannotAcquireLockException", "PessimisticLockingFailureException",
                "DeadlockLoserDataAccessException");
    }

    private static boolean chainHas(Throwable e, String... simpleNames) {
        Throwable t = e;
        int guard = 0;
        while (t != null && guard++ < 12) {
            String cn = t.getClass().getName();
            for (String s : simpleNames) {
                if (cn.endsWith(s)) {
                    return true;
                }
            }
            t = t.getCause();
        }
        return false;
    }

    private static boolean chainMessageHas(Throwable e, String... needles) {
        Throwable t = e;
        int guard = 0;
        while (t != null && guard++ < 12) {
            String msg = t.getMessage();
            if (msg != null) {
                for (String n : needles) {
                    if (msg.contains(n)) {
                        return true;
                    }
                }
            }
            t = t.getCause();
        }
        return false;
    }
}
