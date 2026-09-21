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
 *
 * <p>{@code provider=http} 时启动会对端点做一次真实探针（{@link #probe}）：连不通只打 ERROR、
 * **不阻断启动**，避免把后端卡在与自身无关的上游上——但会明确写出「向量将全部缺失」与两条出路。</p>
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
            HttpEmbeddingProvider provider = new HttpEmbeddingProvider(e);
            probe(provider, e);
            return provider;
        }
        log.info("知识库嵌入 provider=local（确定性 n-gram 哈希，256 维；无语义，仅兜底）");
        return EmbeddingProvider.local();
    }

    /**
     * 启动探针：对配置的 http 嵌入端点打一次真实请求，把「配了却连不通」提前喊出来。
     *
     * <p><b>只告警、不阻断启动</b>（与 {@code MilvusConfig} 的 fail-fast 有意不同）：嵌入服务常与后端
     * 并行上线，拉模型可能耗时数分钟，启动期强校验会把后端卡死在一个与它自身无关的上游上。
     * 但也不能不出声——provider=http 却连不通时的后果是「切片照常入库、向量全部缺失、
     * 检索直接报错」，静默下去只能等运维自己撞上。</p>
     */
    private void probe(EmbeddingProvider provider, KbProperties.Embedding e) {
        try {
            float[] v = provider.embed("探针");
            log.info("嵌入端点连通性正常：url={} 返回 {} 维（与配置 dims={} 一致）", e.getUrl(), v.length, e.getDims());
        } catch (Exception ex) {
            log.error("嵌入端点不可达/不可用，知识库向量将全部缺失（切片仍会照常入库）：url={} 原因={}。"
                            + "出路二选一：① 起 Ollama / vLLM 并让该地址可达；"
                            + "② 改 aioa.kb.embedding-provider=local（零依赖、不需要任何嵌入服务），"
                            + "同时把 aioa.kb.milvus.dims 设为 256 并换成新集合名。",
                    e.getUrl(), ex.getMessage());
        }
    }
}
