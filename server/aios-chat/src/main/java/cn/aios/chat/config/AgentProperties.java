package cn.aios.chat.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Python agent 服务配置（aios.agent.*）。
 */
@Data
@ConfigurationProperties(prefix = "aios.agent")
public class AgentProperties {

    /** Python agent 基址。 */
    private String baseUrl = "http://localhost:8000";

    /** SSE 心跳间隔（秒）。 */
    private long heartbeatSeconds = 15L;
}
