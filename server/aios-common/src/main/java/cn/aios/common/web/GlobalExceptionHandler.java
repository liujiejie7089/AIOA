package cn.aios.common.web;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 全局异常处理：所有异常统一包装为 ApiResponse。
 * 注：401/403 由 security 模块的 entryPoint / accessDeniedHandler 统一处理，
 * 本类仅处理业务异常、参数异常与兜底异常（不引入 spring-security 依赖，保持 common 轻量）。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /** 仅用于把错误体序列化成 SSE 的一行 data（SSE 不能带换行，故用单行 JSON）。 */
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @ExceptionHandler(BizException.class)
    public ResponseEntity<?> handleBiz(BizException e, HttpServletRequest request) {
        int code = e.getCode();
        HttpStatus status = code == 401 ? HttpStatus.UNAUTHORIZED
                : code == 403 ? HttpStatus.FORBIDDEN
                : code == 404 ? HttpStatus.NOT_FOUND
                : HttpStatus.OK;
        return respond(request, status, ApiResponse.fail(code, e.getMessage()));
    }

    @ExceptionHandler({
            MethodArgumentNotValidException.class,
            BindException.class,
            MissingServletRequestParameterException.class,
            HttpMessageNotReadableException.class
    })
    public ResponseEntity<?> handleBadRequest(Exception e, HttpServletRequest request) {
        return respond(request, HttpStatus.BAD_REQUEST, ApiResponse.fail(400, "请求参数错误：" + e.getMessage()));
    }

    /**
     * 路径 / 查询参数类型不匹配 → 400，而不是 500（已知缺口 D-2）。
     *
     * <p>典型场景：把 {@code /api/v1/workflow/tasks/{id}/decide} 的 id 写成非数字（{@code /tasks/abc/decide}），
     * Spring 在参数绑定阶段抛 {@code MethodArgumentTypeMismatchException}。此前它会落到下面的
     * {@code Exception} 兜底被包成「服务内部错误」，于是「客户端传错参数」看起来像「后端崩了」——
     * 排查方向直接被带偏。</p>
     *
     * <p>本条与 {@code NoResourceFoundException} 是同一类修正：<b>让错误归它的类</b>。</p>
     */
    @ExceptionHandler({
            org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class,
            org.springframework.beans.TypeMismatchException.class
    })
    public ResponseEntity<?> handleTypeMismatch(Exception e, HttpServletRequest request) {
        log.warn("Parameter type mismatch on {} {}: {}", request.getMethod(),
                AiosRequestAttributes.originalUri(request), e.getMessage());
        return respond(request, HttpStatus.BAD_REQUEST, ApiResponse.fail(400, "参数类型不正确：" + e.getMessage()));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<?> handleMethod(HttpRequestMethodNotSupportedException e, HttpServletRequest request) {
        return respond(request, HttpStatus.METHOD_NOT_ALLOWED, ApiResponse.fail(405, "不支持的请求方法"));
    }

    /**
     * 路径不存在 → 404，而不是 500。
     *
     * <p>Spring Boot 3.2 起，未匹配的请求在静态资源处理阶段抛 {@code NoResourceFoundException}；
     * 它会落到下面的 {@code Exception} 兜底，被包装成「服务内部错误」。
     * 后果很实际：拼错路径（如把 {@code /api/v1/leave/types} 写成 {@code /api/v1/workflow/leave/types}）
     * 会看到 500，很容易被误判成后端崩了，而不是「接口没这个路径」。
     * 这里补一条显式处理，让 404 归 404。</p>
     */
    @ExceptionHandler(org.springframework.web.servlet.resource.NoResourceFoundException.class)
    public ResponseEntity<?> handleNotFound(
            org.springframework.web.servlet.resource.NoResourceFoundException e, HttpServletRequest request) {
        // 用「客户端原始 URI」：单端口部署下这里可能已被 /aios 前缀剥离改写，
        // 若直接回显 getRequestURI()，用户会看到一条他没请求过的路径（见 AiosRequestAttributes）。
        String uri = AiosRequestAttributes.originalUri(request);
        log.warn("No handler for {} {}", request.getMethod(), uri);
        return respond(request, HttpStatus.NOT_FOUND, ApiResponse.fail(404, "接口不存在：" + uri));
    }

    /**
     * 响应类型协商失败 → 406，而不是 500。
     *
     * <p>典型场景：对 {@code produces = text/event-stream} 的端点（如
     * {@code /api/v1/runs/{id}/events}）发 {@code Accept: application/json}。
     * 这本来会落到 {@code Exception} 兜底被包成「服务内部错误」，于是
     * <b>客户端写错 Accept 头看起来像后端崩了</b> —— 与
     * {@code MethodArgumentTypeMismatchException} / {@code NoResourceFoundException}
     * 是同一类修正：让错误归它的类。</p>
     */
    @ExceptionHandler(org.springframework.web.HttpMediaTypeNotAcceptableException.class)
    public ResponseEntity<?> handleNotAcceptable(
            org.springframework.web.HttpMediaTypeNotAcceptableException e, HttpServletRequest request) {
        log.warn("Not acceptable on {} {}: {}", request.getMethod(),
                AiosRequestAttributes.originalUri(request), e.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_ACCEPTABLE)
                .body(ApiResponse.fail(406, "不支持的响应类型：该接口只提供 " + e.getSupportedMediaTypes()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> handleServer(Exception e, HttpServletRequest request) {
        // 客户端主动断开（刷新页面 / 关闭 H5 / 手机切网）不是服务端故障：
        // 原先它会被记成 ERROR 并触发「写 500 JSON 到已关闭的连接」的二次异常
        // （HttpMessageNotWritableException: No converter ... text/html），把日志淹掉。
        if (isClientAbort(e)) {
            log.debug("客户端已断开，忽略本次异常：{} {}", request.getMethod(), request.getRequestURI());
            return ResponseEntity.status(499).build();
        }
        log.error("Unhandled exception on {} {}", request.getMethod(), request.getRequestURI(), e);
        return respond(request, HttpStatus.INTERNAL_SERVER_ERROR, ApiResponse.fail(500, "服务内部错误"));
    }

    /**
     * 统一出口：普通请求回 JSON，SSE 请求回一条 {@code event: error} 帧。
     *
     * <p>为什么必须分开：{@code /api/v1/runs/{id}/events} 等方法声明了
     * {@code produces = text/event-stream}，浏览器也只会发 {@code Accept: text/event-stream}。
     * 若异常处理器仍返回 {@code ApiResponse}(JSON)，Spring 在消息转换阶段找不到可写表示，
     * 抛 {@code HttpMediaTypeNotAcceptableException}，于是<b>错误处理器本身失败</b> ——
     * 日志里表现为「Failure in @ExceptionHandler」+ Tomcat 又打一遍完整 ERROR 栈
     * （历史上那条 {@code HttpMessageNotWritableException: No converter for [ApiResponse] with
     * preset Content-Type 'text/html'} 属同一根因），客户端拿到的则是错误页而不是可读原因。</p>
     *
     * <p>SSE 分支用 HTTP 200：EventSource 对非 2xx 只会报笼统的连接失败、且会不断重连；
     * 200 + 明确错误帧可以把「为什么失败」原样送到前端。</p>
     */
    private static ResponseEntity<?> respond(HttpServletRequest request, HttpStatus status, ApiResponse<Void> body) {
        if (wantsEventStream(request)) {
            try {
                String json = MAPPER.writeValueAsString(body);
                return ResponseEntity.ok()
                        .contentType(MediaType.TEXT_EVENT_STREAM)
                        .header("Cache-Control", "no-cache")
                        .body("event: error\ndata: " + json + "\n\n");
            } catch (Exception ser) {
                // 序列化失败也必须退出，不能再抛给容器（否则又回到「处理器二次失败」）
                log.warn("错误体序列化失败，降级为纯文本 SSE 帧：{}", ser.getMessage());
                return ResponseEntity.ok()
                        .contentType(MediaType.TEXT_EVENT_STREAM)
                        .body("event: error\ndata: {\"code\":" + body.getCode() + "}\n\n");
            }
        }
        return ResponseEntity.status(status).body(body);
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
        Throwable t = e;
        int guard = 0;
        while (t != null && guard++ < 12) {
            String cn = t.getClass().getName();
            if (cn.endsWith("ClientAbortException")
                    || cn.endsWith("AsyncRequestNotUsableException")
                    || cn.endsWith("EofException")
                    || cn.endsWith("BrokenPipeException")) {
                return true;
            }
            String msg = t.getMessage();
            if (msg != null && (msg.contains("Connection reset by peer") || msg.contains("Broken pipe"))) {
                return true;
            }
            t = t.getCause();
        }
        return false;
    }
}
