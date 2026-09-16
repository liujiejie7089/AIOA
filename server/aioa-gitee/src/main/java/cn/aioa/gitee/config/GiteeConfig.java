package cn.aioa.gitee.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * Gitee 集成模块装配。
 *
 * <p>只做一件事：把 {@link GiteeProperties} 注册成 Bean。组件扫描与 Mapper 扫描
 * 由启动类统一负责（{@code @SpringBootApplication(scanBasePackages="cn.aioa")} +
 * {@code @MapperScan("cn.aioa.**.mapper")}），此处重复声明只会造成扫描重复。</p>
 */
@Configuration
@EnableConfigurationProperties(GiteeProperties.class)
public class GiteeConfig {
}
