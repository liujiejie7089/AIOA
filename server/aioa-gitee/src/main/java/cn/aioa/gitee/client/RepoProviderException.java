package cn.aioa.gitee.client;

import lombok.Getter;

/**
 * 仓库托管方（Gitee / Gitea / …）调用失败的**中立基类**。
 *
 * <p><b>为什么需要它</b>：{@link GiteeApiException} 承载的语义（状态码、是否可重试、
 * 令牌是否失效）其实与「哪一家托管方」无关，只有类名带 Gitee 味道。把它抽成基类后：</p>
 * <ul>
 *   <li>既有全部 {@code catch (GiteeApiException e)} 与
 *       {@code GiteeExceptionAdvice} <b>一行都不用改</b>（子类仍被匹配）；</li>
 *   <li>新增的托管方（GiteaProviderClient）直接抛本类即可被同一个 advice 翻译，
 *       不会因为「没人处理这个异常」而落到全局兜底变成 HTTP 500。</li>
 * </ul>
 *
 * <p><b>提取说明</b>：本文件与 {@link RepoProviderClient} 目前放在 {@code aioa-gitee}
 * 模块内（零构建改动、可逆）。当第二个托管方实现落地时，把这两个文件整体迁到独立的
 * {@code aioa-repo-api} 模块即可，不需要任何设计变更。</p>
 */
@Getter
public class RepoProviderException extends RuntimeException {

    /** HTTP 状态码；0 表示连接层失败（未拿到响应：DNS / 超时 / TLS）。 */
    private final int status;

    /** 是否值得重试（网络 / 超时 / 5xx / 限流）。 */
    private final boolean retryable;

    /** 托管方授权失效（需用户重新绑定）—— 上层据此把绑定标记为失效并提示。 */
    private final boolean tokenInvalid;

    public RepoProviderException(int status, String message, boolean retryable, boolean tokenInvalid) {
        super(message);
        this.status = status;
        this.retryable = retryable;
        this.tokenInvalid = tokenInvalid;
    }

    /**
     * 托管方展示名，用于错误文案（如「无法连接 {providerName}…」）。
     *
     * <p>默认给中性词；各实现覆写为自己的品牌名，文案才具体可辨。放在异常上而不是
     * 在译文层按类名 switch，是为了让「新增一家托管方」不需要改动译文层。</p>
     */
    public String providerName() {
        return "代码托管平台";
    }

    /**
     * 按 HTTP 状态码与错误文案推断「可重试 / 令牌失效」语义（各托管方通用口径）。
     *
     * <p>把重试语义与错误码绑定的原因见 {@code GiteeApiException} 的类注释：
     * 混为一谈要么把永久错误重试到天花板（浪费配额），要么把限流当永久失败直接放弃
     * （用户看到的失败原因完全对不上）。</p>
     *
     * <ul>
     *   <li>401 → 令牌无效或过期，<b>不可重试</b>，标记令牌失效（提示用户重新授权）；</li>
     *   <li>403 → 若文案提示 scope/权限不足，则同样属「授权问题」；否则为普通拒绝；</li>
     *   <li>429 / 5xx → 可重试；</li>
     *   <li>其余 4xx → 参数或状态问题，不可重试。</li>
     * </ul>
     */
    public static RepoProviderException of(int status, String message) {
        if (status == 401) {
            return new RepoProviderException(status, message, false, true);
        }
        if (status == 403) {
            String m = message == null ? "" : message.toLowerCase();
            // Gitea 对「令牌 scope 不足」返回 403 且文案含 scope —— 这属于授权问题，
            // 提示重新授权才对症；其余 403（如无权访问该仓库）不是重授权能解决的。
            boolean scopeIssue = m.contains("scope");
            return new RepoProviderException(status, message, false, scopeIssue);
        }
        boolean retry = status == 429 || status >= 500;
        return new RepoProviderException(status, message, retry, false);
    }
}
