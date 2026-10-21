package cn.aios.resource.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * 开启 Spring 异步执行：通知分发器 {@code @EventListener + @Async} 依赖此注解，
 * 否则分发会在审批主线程同步执行、阻塞流程。
 *
 * <p>项目此前无 {@code @EnableAsync}（已核实），故在此新增。</p>
 *
 * <p>2026-10-20：补上显式 {@code taskExecutor} 线程池。此前只开了 {@code @EnableAsync}
 * 而没有 Executor Bean，Spring 每触发一次 {@code @Async} 就打一条 WARN
 * 「No task executor bean found for async processing」并退化成每次新建线程
 * （SimpleAsyncTaskExecutor，无上限、无复用）。审批高峰时通知分发会把线程数打散。</p>
 */
@Configuration
@EnableAsync
public class AsyncConfig {

    /** 名字必须是 taskExecutor：@Async 默认按此名查找（也可 by-type 找到 Executor）。 */
    @Bean(name = "taskExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor ex = new ThreadPoolTaskExecutor();
        ex.setCorePoolSize(4);
        ex.setMaxPoolSize(16);
        ex.setQueueCapacity(500);
        ex.setKeepAliveSeconds(60);
        ex.setThreadNamePrefix("aios-async-");
        // 队列满时由调用线程执行，保证通知不丢（宁可慢一点，也不要静默丢弃）
        ex.setRejectedExecutionHandler(new java.util.concurrent.ThreadPoolExecutor.CallerRunsPolicy());
        ex.setWaitForTasksToCompleteOnShutdown(true);
        ex.setAwaitTerminationSeconds(10);
        ex.initialize();
        return ex;
    }
}
