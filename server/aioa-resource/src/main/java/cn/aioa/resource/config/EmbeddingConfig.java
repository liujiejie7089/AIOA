package cn.aioa.resource.config;

import cn.aioa.resource.service.EmbeddingProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 向量化 provider 装配（方案 P2 / D-2）。
 *
 * <p>当前阶段（决策点 2）固定用 {@code local} 确定性 provider，不引入模型下载/推理依赖。
 * 后续在管理端提供「一键下载并自行配置 bge-small-zh」后，改这里按配置
 * {@code aioa.kb.embedding-provider} 选择实现即可（扩展点已预留为接口）。</p>
 */
@Configuration
public class EmbeddingConfig {

    @Bean
    public EmbeddingProvider embeddingProvider() {
        return EmbeddingProvider.local();
    }
}
