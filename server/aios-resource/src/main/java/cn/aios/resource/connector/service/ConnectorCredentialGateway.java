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
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 连接器凭据网关：Java 控制面 → mcp-hub 数据面（{@code /api/v1/connectors/{code}/credentials}）。
 *
 * <p><b>为什么需要它</b>：连接器的工具是「在 hub 里跑的」，凭据必须落在用它的那个进程里才生效。
 * 早先管理端只把凭据写进 MySQL 的 {@code connector_tenant_config}，hub 读的是自己的加密库，
 * 两边不相通 —— 现象就是「管理端显示已保存，用户端仍报未配置」。本类把写操作转给 hub，
 * MySQL 退化为「影子记录」（供 configReady 判定与无 hub 时展示用）。</p>
 *
 * <p><b>鉴权</b>：原样转发调用者的 {@code Authorization}。hub 侧仍把该 token 送到
 * {@code /api/v1/auth/me} 判定身份与角色 —— Java 依旧是唯一身份权威，不新增任何服务间密钥，
 * 也不在 hub 里存 token。</p>
 *
 * <p><b>失败处理</b>：hub 不可达返回 {@code null}（由调用方决定如何降级/报错）；
 * hub 明确拒绝（400/403/404）抛 {@link BizException}，把 hub 的中文原因透给管理端，
 * <b>绝不</b>把失败伪装成成功。</p>
 */
@Slf4j
@Component
public class ConnectorCredentialGateway {

    private static final String PREFIX = "/api/v1/connectors";

    private final McpProperties props;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 与 {@code McpProbeClient} 同理：JDK 默认 HTTP/2 对明文地址会发 h2c 升级，uvicorn 会丢 body。 */
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public ConnectorCredentialGateway(McpProperties props) {
        this.props = props;
    }

    /** hub 是否可能可用（总开关）。关掉时管理端应明确提示「连接器运行时未启用」。 */
    public boolean available() {
        return props.isHubEnabled();
    }

    /** 掩码视图。hub 不可达返回 null。 */
    public Map<String, Object> fetch(String code, String authorization) {
        return call("GET", code + "/credentials", null, authorization);
    }

    /** 保存凭据（空串/掩码值 = 保留旧值，语义在 hub 侧统一实现）。 */
    public Map<String, Object> put(String code, Map<String, String> values, Boolean enabled, String authorization) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("values", values == null ? Map.of() : values);
        body.put("enabled", enabled == null || enabled);
        return call("PUT", code + "/credentials", body, authorization);
    }

    /** 清除凭据（回到「待配置」）。 */
    public Map<String, Object> delete(String code, String authorization) {
        return call("DELETE", code + "/credentials", null, authorization);
    }

    // ---------- 内部 ----------

    private Map<String, Object> call(String method, String path, Map<String, Object> body, String authorization) {
        if (!props.isHubEnabled()) {
            return null;
        }
        // 没有调用者凭据就无法让 hub 判定租户/角色：直接视为「本次不可用」，
        // 由调用方回退到影子记录只读视图（绝不伪造身份去读别人的租户配置）。
        if (authorization == null || authorization.isBlank()) {
            return null;
        }
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(props.getHubUrl() + PREFIX + "/" + path))
                    .timeout(Duration.ofSeconds(8))
                    .header("Content-Type", "application/json");
            if (authorization != null && !authorization.isBlank()) {
                builder.header("Authorization", authorization);
            }
            String json = body == null ? null : objectMapper.writeValueAsString(body);
            builder.method(method, json == null
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8));

            HttpResponse<String> resp = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            Map<String, Object> parsed = parse(resp.body());
            int status = resp.statusCode();
            if (status >= 200 && status < 300 && Boolean.TRUE.equals(parsed.get("ok"))) {
                return parsed;
            }
            // hub 明确拒绝：把中文原因透给管理端，不吞成 500
            Object err = parsed.get("error");
            String reason = err == null ? ("HTTP " + status) : String.valueOf(err);
            log.debug("连接器凭据网关拒绝 {} {}：{}", method, path, reason);
            if (status == 403) {
                throw BizException.forbidden(reason);
            }
            if (status >= 400 && status < 500) {
                throw BizException.badRequest(reason);
            }
            throw new IllegalStateException("连接器运行时异常：" + reason);
        } catch (BizException e) {
            throw e;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.debug("连接器凭据网关被中断：{}", e.getClass().getSimpleName());
            return null;
        } catch (Exception e) {
            // 仅记录异常类型，绝不打印 values / token
            log.debug("连接器凭据网关不可达：{}", e.getClass().getSimpleName());
            return null;
        }
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
