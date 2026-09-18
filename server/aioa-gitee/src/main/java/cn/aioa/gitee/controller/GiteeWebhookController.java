package cn.aioa.gitee.controller;

import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.service.GiteeWebhookService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * Webhook 接收端点（**公开端点**，由托管方服务端调用）。
 *
 * <p><b>安全边界</b>：这是唯一一个不需要登录态就能写数据的入口，因此三重防线缺一不可：
 * ① 路径上的 projectId 必须存在；② 投递必须通过当前托管方的校验
 * （Gitee 是请求头 {@code X-Gitee-Token} 与项目密钥<b>明文相等</b>；
 * Gitea 是 {@code X-Gitea-Signature} 的 <b>HMAC-SHA256</b>）；
 * ③ {@code event_key} 唯一索引兜底幂等，重复投递不会产生重复记录。</p>
 *
 * <p><b>为什么不在这里按托管方分支</b>：校验机制由 {@link RepoProviderClient} 的实现承担，
 * 本类只负责「把原始字节与请求头原样交下去」。若在此处按类名 if/else，新增一家托管方就会
 * 漏掉一处 —— 而漏掉的后果是「任何人都能伪造提交记录」。</p>
 *
 * <p><b>为什么永远返回 HTTP 200</b>：托管方对非 2xx 会持续重投。对**我们不接受**的请求
 * （校验失败、项目不存在）返回 200 并带上 {@code accepted=false}，避免把无效请求
 * 变成一个持续重投的循环；真正的排障信息通过平台侧日志与 {@code gitee_event} 表查看。</p>
 *
 * <p><b>为什么报文用 {@code byte[]} 而不是 {@code String} 接收</b>：Gitea 的签名是对
 * <b>原始字节</b>算的 HMAC。若先让 Spring 把报文解码成字符串、校验时再编码回字节，
 * 只要字符集或转义有一丝往返差异，签名就永远不匹配，而排查方向会被误导到「密钥配错了」。
 * 用 byte[] 接收则字节原样保留。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/gitee/webhook")
@RequiredArgsConstructor
public class GiteeWebhookController {

    private final GiteeWebhookService webhookService;

    /**
     * 接收一次投递。
     *
     * @param projectId 平台项目 id（Webhook 地址由平台在建仓时生成）
     * @param headers   全部请求头：事件头名与请求 id 头名由当前托管方决定
     *                  （Gitee {@code X-Gitee-Event}/{@code X-Gitee-Request-Id}；
     *                  Gitea {@code X-Gitea-Event}/{@code X-Gitea-Delivery}），
     *                  因此这里不做筛选、整体透传
     * @param rawBody   原始报文字节
     */
    @PostMapping("/{projectId}")
    public Map<String, Object> receive(@PathVariable Long projectId,
                                       @RequestHeader Map<String, String> headers,
                                       @RequestBody(required = false) byte[] rawBody) {
        try {
            Map<String, Object> r = webhookService.handle(projectId, headers, rawBody);
            // 托管方只关心 HTTP 状态；响应体返回给「Webhook 测试」按钮时便于人工核对
            return r;
        } catch (Exception e) {
            // 兜底：任何未预期异常都不抛出，否则会被托管方判定为投递失败而重投
            log.error("Webhook 处理异常 project={} headers={}", projectId, safeHeaderNames(headers), e);
            return Map.of("accepted", false, "reason", "INTERNAL_ERROR");
        }
    }

    /** 日志只记头名，不记头值 —— 其中含签名/密钥，落日志等于泄露凭证。 */
    private static Set<String> safeHeaderNames(Map<String, String> headers) {
        return headers == null ? Set.of() : new TreeSet<>(headers.keySet());
    }
}
