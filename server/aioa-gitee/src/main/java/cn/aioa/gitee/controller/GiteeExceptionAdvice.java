package cn.aioa.gitee.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.gitee.client.GiteeApiException;
import cn.aioa.gitee.client.RepoProviderException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 仓库托管方调用失败的异常翻译（Gitee / Gitea / … 共用）。
 *
 * <p><b>为什么必须有这一层</b>：{@link RepoProviderException} 是**外部依赖异常**，
 * 不是程序缺陷。若不翻译，它会落到 {@code GlobalExceptionHandler} 的兜底分支变成
 * HTTP 500「服务内部错误」—— 用户看到的是一句无信息量的报错，排障的人还要去翻日志。
 * 翻译后用户直接看到「哪一家的什么接口、什么原因失败」。</p>
 *
 * <p><b>为什么用 {@code HIGHEST_PRECEDENCE}</b>：全局兜底处理器里有
 * {@code @ExceptionHandler(Exception.class)}，它同样能匹配本异常；advice 的优先级
 * 决定谁先被选中。不显式提前，就可能永远走兜底的 500 分支。</p>
 *
 * <p><b>为什么这里是「两个 handler」而不是一个</b>：{@link GiteeApiException} 多带了
 * Gitee 专有的业务错误码，单独接住可以把它打进日志便于对账；Spring 会为给定异常挑选
 * <b>最具体</b>的 handler，因此 Gitee 走前者、其他实现走后者，互不干扰。</p>
 *
 * <p><b>为什么不映射成 HTTP 401</b>：这里的 401 是「托管方令牌失效」，不是
 * 「平台登录态失效」。若返回 HTTP 401，前端会误判为会话过期并强制登出，
 * 把一次第三方授权过期放大成一次平台掉线。因此统一按**业务错误（HTTP 200 + code≠0）**
 * 返回，由前端提示「请重新绑定」。</p>
 */
@Slf4j
@RestControllerAdvice
@Order(Ordered.HIGHEST_PRECEDENCE)
public class GiteeExceptionAdvice {

    @ExceptionHandler(GiteeApiException.class)
    public ResponseEntity<ApiResponse<Void>> handleGitee(GiteeApiException e) {
        log.warn("Gitee 调用失败：status={} code={} retryable={} msg={}",
                e.getStatus(), e.getGiteeCode(), e.isRetryable(), e.getMessage());
        return ResponseEntity.ok(ApiResponse.fail(codeOf(e), messageOf(e)));
    }

    /**
     * 非 Gitee 实现（如 Gitea）的兜底翻译。
     *
     * <p>没有它，新托管方的异常会落到全局兜底变成 500 —— 而这正是「换托管方后
     * 报错全变成服务内部错误」的成因。</p>
     */
    @ExceptionHandler(RepoProviderException.class)
    public ResponseEntity<ApiResponse<Void>> handleProvider(RepoProviderException e) {
        log.warn("仓库托管方调用失败：provider={} status={} retryable={} msg={}",
                e.providerName(), e.getStatus(), e.isRetryable(), e.getMessage());
        return ResponseEntity.ok(ApiResponse.fail(codeOf(e), messageOf(e)));
    }

    /** 业务错误码：用 4xx 表达「调用方/依赖方可修复」，与平台既有口径一致。 */
    static int codeOf(RepoProviderException e) {
        if (e.getStatus() == 0) {
            return 503;   // 连不上托管方（DNS/超时/TLS）
        }
        if (isRateLimited(e)) {
            return 429;   // 限流，稍后重试
        }
        if (e.isTokenInvalid()) {
            return 424;   // 依赖方授权失效：需重新绑定
        }
        return 400;
    }

    static String messageOf(RepoProviderException e) {
        String p = e.providerName();
        if (e.getStatus() == 0) {
            return "无法连接 " + p + "（网络或代理问题）：" + e.getMessage();
        }
        if (isRateLimited(e)) {
            return p + " 接口触发限流，请稍后重试（平台已自动排队重试）";
        }
        if (e.isTokenInvalid()) {
            return p + " 授权已失效，请到「" + p + " 账号绑定」重新授权";
        }
        return p + " 接口调用失败：" + e.getMessage();
    }

    private static boolean isRateLimited(RepoProviderException e) {
        return e.getStatus() == 403 && e.isRetryable();
    }
}
