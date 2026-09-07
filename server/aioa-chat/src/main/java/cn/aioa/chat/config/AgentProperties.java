package cn.aioa.chat.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Python agent 服务配置（aioa.agent.*）。
 */
@Data
@ConfigurationProperties(prefix = "aioa.agent")
public class AgentProperties {

    /** Python agent 基址。 */
    private String baseUrl = "http://localhost:8000";

    /** SSE 心跳间隔（秒）。 */
    private long heartbeatSeconds = 15L;
}
