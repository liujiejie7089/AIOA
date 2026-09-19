package cn.aioa.resource.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 知识库存储与嵌入配置（前缀 {@code aioa.kb}，docs/32 方案 P2）。
 *
 * <p>三个开关决定「向量库重建」的形态，三者正交、可独立回滚：</p>
 * <ul>
 *   <li>{@link #store} —— 存储实现：{@code mysql}（默认，BLOB + 应用层余弦）/ {@code milvus}；
 *       由各 {@code KnowledgeStore} 实现上的 {@code @ConditionalOnProperty} 消费；</li>
 *   <li>{@link #embeddingProvider} —— 嵌入实现：{@code local}（默认，256 维 char n-gram 哈希、零依赖兜底）
 *       / {@code http}（指向 Ollama / vLLM 的 embedding 端点，输出语义向量）；</li>
 *   <li>{@link Milvus#isBackfillOnStart()} —— 启动时是否把 MySQL 切片全量灌入 Milvus（索引重建）。</li>
 * </ul>
 *
 * <p><b>注意</b>：{@code store=milvus} 要求 Milvus 必须在线（决策 D6 fail-fast），
 * 不允许静默降级为空结果——那是 {@code ElasticKnowledgeStore} 踩过的坑。</p>
 */
@Data
@Component
@ConfigurationProperties(prefix = "aioa.kb")
public class KbProperties {

    /** 存储实现标识：mysql / milvus（对应 KB_STORE 的实现类 @ConditionalOnProperty）。 */
    private String store = "mysql";

    /** 嵌入实现标识：local / http。 */
    private String embeddingProvider = "local";

    /**
     * 启动时是否用**当前** provider 全量重算切片向量（docs/32 Ph1 的「重算 job」）。
     *
     * <p>换 provider / 换模型后**必须**执行一次：{@code kb_chunk.embedding} 里存的是旧模型的向量，
     * 维度不同时余弦相似度直接返回 0（不会崩，但永远不命中）。判据是
     * {@code embedding_provider / embedding_dims} 与当前 provider 是否一致。</p>
     */
    private boolean reembedOnStart = false;

    /** HTTP 嵌入 provider 参数（embeddingProvider=http 时生效）。 */
    private Embedding embedding = new Embedding();

    /** Milvus 参数（store=milvus 时生效）。 */
    private Milvus milvus = new Milvus();

    /** HTTP 嵌入 provider 参数。 */
    @Data
    public static class Embedding {

        /** 协议形态：ollama（{@code /api/embeddings}、{@code /api/embed}）/ openai（{@code /v1/embeddings}）。 */
        private String format = "ollama";

        /** 端点地址。ollama 例：http://localhost:11434/api/embeddings；openai 例：http://localhost:8001/v1/embeddings */
        private String url = "";

        /** 模型名，随请求发出，也用于 provider 标识（落库到 kb_chunk.embedding_provider）。 */
        private String model = "bge-small-zh-v1.5";

        /** 期望维度；&gt;0 时与响应实长强校验，不一致直接失败（禁止写入错维向量）。 */
        private int dims = 512;

        /** 单次嵌入请求超时（毫秒）。 */
        private int timeoutMs = 15000;

        /** 可选 Bearer 令牌（vLLM 网关常需）。留空则不带 Authorization 头。 */
        private String apiKey = "";
    }

    /** Milvus 参数。 */
    @Data
    public static class Milvus {

        /** 连接串，如 http://localhost:19530（也可用 https）。 */
        private String uri = "http://localhost:19530";

        /** 认证令牌（Milvus 开启鉴权时的 {@code user:password} 或 token）。留空表示无鉴权。 */
        private String token = "";

        /** 数据库名。留空或 default 表示默认库。 */
        private String database = "default";

        /** 集合名。**带版本后缀**——Milvus 集合维度创建后不可改，换模型只能新建集合（风险 R1）。 */
        private String collection = "kb_chunk_v1";

        /** 稠密向量维度，必须与嵌入 provider 的 dims 一致。 */
        private int dims = 512;

        /** 距离度量：COSINE / IP / L2。 */
        private String metricType = "COSINE";

        /** 稠密向量索引类型：HNSW / AUTOINDEX / FLAT。 */
        private String indexType = "HNSW";

        /** HNSW 的 M 参数。 */
        private int hnswM = 16;

        /** HNSW 的 efConstruction 参数。 */
        private int hnswEfConstruction = 200;

        /**
         * 是否启用 Milvus 原生 BM25（2.5+ 的 Function + SparseFloatVector + hybrid_search）。
         * 服务端低于 2.5 或连不上 analyzer 时置 false：集合退化为「纯稠密」，
         * 此时 bm25 / hybrid 的关键词腿改由 MySQL 切片打分 + 客户端 RRF 兜底（见 MilvusKnowledgeStore）。
         */
        private boolean enableBm25 = true;

        /** 启动时是否从 kb_chunk 全量回填（索引重建 / 首次接入）。 */
        private boolean backfillOnStart = false;

        /** 回填与检索的单次 RPC 超时（毫秒）。 */
        private long timeoutMs = 10000;

        /** 回填时的分批大小。 */
        private int backfillBatchSize = 200;
    }
}
