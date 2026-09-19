package cn.aioa.resource.config;

import cn.aioa.resource.service.EmbeddingProvider;
import cn.aioa.resource.service.HttpEmbeddingProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 向量化 provider 装配（方案 P2 / docs/32 D1–D2）。
 *
 * <p>按 {@code aioa.kb.embedding-provider} 二选一：</p>
 * <ul>
 *   <li>{@code local}（默认）—— 256 维 char 2-gram 哈希 + L2 归一化。确定性、零依赖、零下载，
 *       保证「无外网 / 无模型」环境也能跑通解析→切分→向量化→检索全链路。**无语义**，
 *       命中等价于字面 n-gram 重叠；</li>
 *   <li>{@code http} —— 复用 compose 里已有的 ollama / vllm 暴露语义向量（Ph1 交付）。
 *       模型与维度由 {@code aioa.kb.embedding.model / dims} 决定，必须与 Milvus 集合维度一致。</li>
 * </ul>
 *
 * <p><b>换 provider 必须重算历史向量</b>：{@code kb_chunk.embedding_provider / embedding_dims} 是判据，
 * 维度不同时 {@link EmbeddingProvider#cosine(float[], float[])} 直接返回 0（不会崩，但永不命中）。
 * 重算入口见 {@code KbBackfillRunner}。</p>
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
public class EmbeddingConfig {

    private final KbProperties props;

    @Bean
    public EmbeddingProvider embeddingProvider() {
        if ("http".equalsIgnoreCase(props.getEmbeddingProvider())) {
            KbProperties.Embedding e = props.getEmbedding();
            log.info("知识库嵌入 provider=http model={} dims={} format={} url={}",
                    e.getModel(), e.getDims(), e.getFormat(), e.getUrl());
            return new HttpEmbeddingProvider(e);
        }
        log.info("知识库嵌入 provider=local（确定性 n-gram 哈希，256 维；无语义，仅兜底）");
        return EmbeddingProvider.local();
    }
}
