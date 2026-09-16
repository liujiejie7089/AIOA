package cn.aioa.gitee.controller;

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

/**
 * Gitee Webhook 接收端点（**公开端点**，由 Gitee 服务端调用）。
 *
 * <p><b>安全边界</b>：这是唯一一个不需要登录态就能写数据的入口，因此三重防线缺一不可：
 * ① 路径上的 projectId 必须存在；② 请求头 {@code X-Gitee-Token} 必须与该项目
 * 创建 Webhook 时写入的密钥**明文相等**（Gitee 不做 HMAC 签名，这点与 GitHub 不同）；
 * ③ {@code event_key} 唯一索引兜底幂等，重复投递不会产生重复记录。</p>
 *
 * <p><b>为什么永远返回 HTTP 200</b>：Gitee 对非 2xx 会持续重投。对**我们不接受**的请求
 * （密钥错、项目不存在）返回 200 并带上 {@code accepted=false}，避免把无效请求
 * 变成一个持续重投的循环；真正的排障信息通过平台侧日志与 {@code gitee_event} 表查看。</p>
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
     * @param rawBody   原始报文（用 String 接收，保留原样以便计算幂等键与落库排障）
     */
    @PostMapping("/{projectId}")
    public Map<String, Object> receive(@PathVariable Long projectId,
                                       @RequestHeader(value = "X-Gitee-Event", required = false) String eventHeader,
                                       @RequestHeader(value = "X-Gitee-Token", required = false) String tokenHeader,
                                       @RequestHeader(value = "X-Gitee-Request-Id", required = false) String requestId,
                                       @RequestBody(required = false) String rawBody) {
        try {
            Map<String, Object> r = webhookService.handle(projectId, eventHeader, tokenHeader, requestId, rawBody);
            // Gitee 只关心 HTTP 状态；响应体返回给「Webhook 测试」按钮时便于人工核对
            return r;
        } catch (Exception e) {
            // 兜底：任何未预期异常都不抛出，否则会被 Gitee 判定为投递失败而重投
            log.error("Gitee Webhook 处理异常 project={} event={}", projectId, eventHeader, e);
            return Map.of("accepted", false, "reason", "INTERNAL_ERROR");
        }
    }
}
