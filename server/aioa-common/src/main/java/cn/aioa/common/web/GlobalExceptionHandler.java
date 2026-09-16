package cn.aioa.common.web;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
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

    @ExceptionHandler(BizException.class)
    public ResponseEntity<ApiResponse<Void>> handleBiz(BizException e) {
        int code = e.getCode();
        HttpStatus status = code == 401 ? HttpStatus.UNAUTHORIZED
                : code == 403 ? HttpStatus.FORBIDDEN
                : code == 404 ? HttpStatus.NOT_FOUND
                : HttpStatus.OK;
        return ResponseEntity.status(status)
                .body(ApiResponse.fail(code, e.getMessage()));
    }

    @ExceptionHandler({
            MethodArgumentNotValidException.class,
            BindException.class,
            MissingServletRequestParameterException.class,
            HttpMessageNotReadableException.class
    })
    public ResponseEntity<ApiResponse<Void>> handleBadRequest(Exception e) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ApiResponse.fail(400, "请求参数错误：" + e.getMessage()));
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
    public ResponseEntity<ApiResponse<Void>> handleTypeMismatch(Exception e, HttpServletRequest request) {
        log.warn("Parameter type mismatch on {} {}: {}", request.getMethod(), request.getRequestURI(),
                e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ApiResponse.fail(400, "参数类型不正确：" + e.getMessage()));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethod(HttpRequestMethodNotSupportedException e) {
        return ResponseEntity.status(HttpStatus.METHOD_NOT_ALLOWED)
                .body(ApiResponse.fail(405, "不支持的请求方法"));
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
    public ResponseEntity<ApiResponse<Void>> handleNotFound(
            org.springframework.web.servlet.resource.NoResourceFoundException e, HttpServletRequest request) {
        log.warn("No handler for {} {}", request.getMethod(), request.getRequestURI());
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.fail(404, "接口不存在：" + request.getRequestURI()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleServer(Exception e, HttpServletRequest request) {
        log.error("Unhandled exception on {} {}", request.getMethod(), request.getRequestURI(), e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.fail(500, "服务内部错误"));
    }
}
