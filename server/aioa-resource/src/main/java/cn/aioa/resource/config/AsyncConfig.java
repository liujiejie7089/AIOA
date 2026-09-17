package cn.aioa.resource.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;

/**
 * 开启 Spring 异步执行：通知分发器 {@code @EventListener + @Async} 依赖此注解，
 * 否则分发会在审批主线程同步执行、阻塞流程。
 *
 * <p>项目此前无 {@code @EnableAsync}（已核实），故在此新增。</p>
 */
@Configuration
@EnableAsync
public class AsyncConfig {
}
