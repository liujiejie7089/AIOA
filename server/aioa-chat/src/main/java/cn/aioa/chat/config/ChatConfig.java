package cn.aioa.chat.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;

@Configuration
@EnableConfigurationProperties(AgentProperties.class)
public class ChatConfig {

    @Bean
    public WebClient agentWebClient(WebClient.Builder builder, AgentProperties properties) {
        return builder.baseUrl(properties.getBaseUrl()).build();
    }

    @Bean(destroyMethod = "shutdown")
    public ScheduledExecutorService sseHeartbeatExecutor() {
        return Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "aioa-sse-heartbeat");
            thread.setDaemon(true);
            return thread;
        });
    }
}
