package cn.aioa.gitee.client;

import lombok.Getter;

/**
 * Gitee API 调用失败。
 *
 * <p><b>为什么区分 retryable</b>：异步任务的重试策略必须能分辨「等一会儿再试就好」与
 * 「再试一万次也不会好」。把这两类混在一起，要么把永久错误重试到天花板（浪费配额），
 * 要么把限流当永久失败直接放弃（用户看到的失败原因完全对不上）。</p>
 *
 * <ul>
 *   <li>{@code retryable=true}：网络异常 / 超时 / 5xx / 403 Rate Limit（Gitee 实测会返回它）；</li>
 *   <li>{@code retryable=false}：400 参数错 / 401 令牌失效 / 403 权限不足 / 404 不存在 / 422 已存在。</li>
 * </ul>
 */
@Getter
public class GiteeApiException extends RuntimeException {

    /** HTTP 状态码；0 表示连接层失败（未拿到响应）。 */
    private final int status;

    /** Gitee 业务错误码（响应体里的 code），无则为 0。 */
    private final int giteeCode;

    /** 是否值得重试。 */
    private final boolean retryable;

    /** 令牌失效（需要用户重新绑定）—— 上层据此把绑定标记为失效并提示。 */
    private final boolean tokenInvalid;

    public GiteeApiException(int status, int giteeCode, String message, boolean retryable, boolean tokenInvalid) {
        super(message);
        this.status = status;
        this.giteeCode = giteeCode;
        this.retryable = retryable;
        this.tokenInvalid = tokenInvalid;
    }

    public GiteeApiException(int status, String message, boolean retryable) {
        this(status, 0, message, retryable, status == 401);
    }

    /** 连接层失败（DNS / 超时 / TLS）—— 一律可重试。 */
    public static GiteeApiException network(String message) {
        return new GiteeApiException(0, 0, message, true, false);
    }

    /** 按 HTTP 状态与错误码推断重试语义。 */
    public static GiteeApiException of(int status, int giteeCode, String message) {
        // 401 = 令牌不存在/失效；Gitee 实测返回 {"message":"401 Unauthorized: Access token does not exist"}
        if (status == 401) {
            return new GiteeApiException(status, giteeCode, message, false, true);
        }
        // 403 有两种：Rate Limit（可重试）与权限不足（不可重试）——按文义区分
        if (status == 403) {
            boolean rate = message != null && message.toLowerCase().contains("rate limit");
            return new GiteeApiException(status, giteeCode, message, rate, false);
        }
        boolean retry = status == 429 || status >= 500;
        return new GiteeApiException(status, giteeCode, message, retry, false);
    }
}
