package cn.aios.resource.connector.mcp.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * MCP 网关配置（{@code aios.mcp.*}，docs/59 §10.3）。默认值已在此处给出，无需改动 application.yml。
 *
 * <ul>
 *   <li>{@code hubUrl}：MCP 网关基址（Java 只把「清单 + 执行入口」暴露给 agent，工具经 hub 走 MCP 协议）。</li>
 *   <li>{@code hubEnabled}：网关开关；关闭时探测直接返回不可用，不会把异常穿透成 HTTP 500。</li>
 *   <li>{@code probeTimeoutMs} / {@code callTimeoutMs}：存活探测 / 调用超时。</li>
 * </ul>
 */
@Data
@Component
@ConfigurationProperties(prefix = "aios.mcp")
public class McpProperties {

    private String hubUrl = "http://127.0.0.1:8099";
    private boolean hubEnabled = true;
    private int probeTimeoutMs = 8000;
    private int callTimeoutMs = 15000;
}
