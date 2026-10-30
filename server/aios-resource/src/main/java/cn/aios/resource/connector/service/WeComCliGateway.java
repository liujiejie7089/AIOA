package cn.aios.resource.connector.service;

import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.mcp.config.McpProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 企业微信「扫码授权」连接器（{@code wecom_cli}）网关：Java 控制面 → mcp-hub 数据面
 * （{@code /api/v1/wecom_cli/**}）。见 docs/64。
 *
 * <p><b>为什么不复用 {@link ConnectorCredentialGateway}</b>：</p>
 * <ol>
 *   <li><b>前缀不同</b>：那个类把 {@code /api/v1/connectors} 写死在前缀常量里，路径无法外置。</li>
 *   <li><b>成功判定契约不同</b>：hub 的 {@code /api/v1/connectors/*} 回 {@code {"ok":true,...}}，
 *       而 {@code /api/v1/wecom_cli/*} 回 {@code {"code":0,"message":"ok","data":{...}}}（阿里风格）。
 *       直接套用会把每一次成功都判成失败并抛 400 —— 这是接错网关最典型的症状。</li>
 * </ol>
 *
 * <p><b>身份</b>：原样转发调用者的 {@code Authorization}。hub 拿它回调 {@code /api/v1/auth/me}
 * 判定 tenant/user，再据此决定「读写哪个配置目录」—— 一人一账号的隔离在 hub 侧由目录保证，
 * 本类不接受也不传递任何 tenant/user 入参（传了也不会被使用）。</p>
 *
 * <p><b>失败处理</b>：hub 明确拒绝 → 抛 {@link BizException}，把 hub 的中文原因原样透给前端
 * （如「企业微信尚未完成扫码授权」）；hub 不可达 → 抛 {@link BizException}，说明运行时未启用。
 * 绝不把失败伪装成成功：扫码绑定的成败直接决定数字人能否读到该用户的企微数据。</p>
 */
@Slf4j
@Component
public class WeComCliGateway {

    private static final String PREFIX = "/api/v1/wecom_cli";

    private final McpProperties props;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 同 {@code McpProbeClient}：JDK 默认会对明文地址发 h2c 升级，uvicorn 会吞掉 body。 */
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public WeComCliGateway(McpProperties props) {
        this.props = props;
    }

    public boolean available() {
        return props.isHubEnabled();
    }

    /** 我的绑定状态：{@code {authorized, accountLabel, sharedProfile}}。含开发态共享兜底，仅供排障。 */
    public Map<String, Object> status(String authorization) {
        return call("GET", "/status", authorization, 10);
    }

    /**
     * **本次扫码**是否完成：{@code {authorized, accountLabel, reason}}。
     *
     * <p>与 {@link #status} 的区别是本方法的判据只有「本人目录 + 凭据写入时间晚于本次会话
     * 起点」，不含 {@code AIOS_WECOM_CLI_SHARED_PROFILE} 的共享兜底。轮询必须用它：
     * 用 {@code /status} 时，共享目录里早已存在别人的凭据 ⇒ 二维码刚显示就被判定扫完了
     * （2026-10-30 线上现象：用户一个像素都没扫，弹层却自己跳成「已连接」）。</p>
     */
    public Map<String, Object> qrStatus(String authorization) {
        return call("GET", "/qr-status", authorization, 15);
    }

    /**
     * 发起扫码：{@code {qr: "data:image/png;base64,...", reused, expiresIn, hint}}。
     *
     * <p>超时给到 35s —— hub 侧要起 {@code wecom-cli auth init} 子进程并等二维码 PNG 落盘
     * （自身上限 20s），沿用凭据网关的 8s 会把「二维码正在生成」误判成故障。</p>
     */
    public Map<String, Object> qr(String authorization) {
        return call("POST", "/qr", authorization, 35);
    }

    /** 确认绑定：{@code {bound, accountLabel, botName, sharedProfile, stateSynced}}。 */
    public Map<String, Object> bind(String authorization) {
        return call("POST", "/bind", authorization, 30);
    }

    /** 解绑：{@code {bound:false, wiped, stateSynced}}。 */
    public Map<String, Object> disconnect(String authorization) {
        return call("POST", "/disconnect", authorization, 15);
    }

    // ---------- 内部 ----------

    private Map<String, Object> call(String method, String path, String authorization, int timeoutSeconds) {
        if (!props.isHubEnabled()) {
            throw BizException.badRequest(
                    "企业微信连接器运行时未启用（aios.mcp.hub-enabled=false），扫码绑定暂不可用");
        }
        if (authorization == null || authorization.isBlank()) {
            // 没有调用者凭据就无法让 hub 判定租户/用户：绝不能伪造身份去读写别人的授权目录。
            throw BizException.unauthorized("缺少登录凭据，无法识别当前用户");
        }
        HttpResponse<String> resp;
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(props.getHubUrl() + PREFIX + path))
                    .timeout(Duration.ofSeconds(timeoutSeconds))
                    .header("Content-Type", "application/json")
                    .header("Authorization", authorization);
            // POST 一律带空 JSON body：hub 侧要 drain 请求体，部分 uvicorn 配置下 noBody 也能过，
            // 但显式给一个 {} 更稳（也是 hub 各 admin_api 的既有期望）。
            builder.method(method, "POST".equals(method)
                    ? HttpRequest.BodyPublishers.ofString("{}")
                    : HttpRequest.BodyPublishers.noBody());
            resp = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw BizException.badRequest("企业微信连接器请求被中断，请重试");
        } catch (Exception e) {
            // 只记异常类型：Authorization 绝不进日志
            log.warn("企业微信连接器网关不可达（{} {}）：{}", method, path, e.getClass().getSimpleName());
            throw BizException.badRequest(
                    "企业微信连接器运行时不可达（" + props.getHubUrl() + "），请确认 mcp-hub 已启动");
        }

        Map<String, Object> parsed = parse(resp.body());
        int status = resp.statusCode();
        Object codeObj = parsed.get("code");
        boolean bizOk = (codeObj instanceof Number n && n.intValue() == 0)
                || "0".equals(String.valueOf(codeObj));
        if (status >= 200 && status < 300 && bizOk) {
            Object data = parsed.get("data");
            if (data instanceof Map<?, ?> m) {
                @SuppressWarnings("unchecked")
                Map<String, Object> cast = (Map<String, Object>) m;
                return cast;
            }
            return new LinkedHashMap<>();
        }
        String reason = renderReason(status, parsed);
        log.debug("企业微信连接器网关拒绝 {} {}：{}", method, path, reason);
        if (status == 401 || status == 403) {
            throw BizException.forbidden(reason);
        }
        throw BizException.badRequest(reason);
    }

    /** hub 回的是 {@code {code,message,data}}；拿不到 message 时给可排查的兜底文案。 */
    private String renderReason(int status, Map<String, Object> parsed) {
        Object msg = parsed.get("message");
        if (msg != null && !String.valueOf(msg).isBlank() && !"ok".equals(msg)) {
            return String.valueOf(msg);
        }
        return "企业微信连接器返回异常（HTTP " + status + "）";
    }

    private Map<String, Object> parse(String raw) {
        if (raw == null || raw.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(raw, new TypeReference<Map<String, Object>>() { });
        } catch (Exception e) {
            return Map.of();
        }
    }
}
