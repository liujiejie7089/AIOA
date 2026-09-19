package cn.aioa.resource.config;

import cn.aioa.resource.store.MilvusFilter;
import io.milvus.common.clientenum.FunctionType;
import io.milvus.v2.client.ConnectConfig;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.common.ConsistencyLevel;
import io.milvus.v2.common.DataType;
import io.milvus.v2.common.IndexParam;
import io.milvus.v2.service.collection.request.CreateCollectionReq;
import io.milvus.v2.service.collection.request.DescribeCollectionReq;
import io.milvus.v2.service.collection.request.HasCollectionReq;
import io.milvus.v2.service.collection.request.LoadCollectionReq;
import io.milvus.v2.service.collection.response.DescribeCollectionResp;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Milvus 客户端与集合引导（docs/32 Ph2 / Ph0 环境就绪）。
 *
 * <p>只在 {@code aioa.kb.store=milvus} 时装配。启动即完成三件事，任一失败就让应用起不来：</p>
 * <ol>
 *   <li><b>连通性探测</b>——{@code hasCollection} 能返回就说明 gRPC 通、鉴权过；</li>
 *   <li><b>集合自建</b>——不存在则按 schema 建（含 partition key 与索引）；存在则校验维度；</li>
 *   <li><b>load</b>——确保集合已加载可检索。</li>
 * </ol>
 *
 * <p><b>决策 D6：fail-fast，禁止静默降级。</b>这是刻意与 {@code ElasticKnowledgeStore}
 * 划清界线——那个骨架在读路径上「静默返回空列表」，结果是检索无声失效、没人发现。
 * 这里宁可应用起不来，也不要「能启动但检索永远空」。</p>
 *
 * <p>集合 schema（决策 D4/D5）：</p>
 * <pre>
 *   标量：tenant_id(Int64, partition_key) / user_id / doc_id / chunk_index / scope
 *   文本：content(VarChar, enable_analyzer=true)          —— Milvus 2.5 原生 BM25 的输入
 *   向量：vector(FloatVector[dim], HNSW/COSINE)           —— 稠密语义召回
 *         sparse(SparseFloatVector, BM25 Function 输出)   —— 稀疏关键词召回（enable-bm25=true 时存在）
 * </pre>
 * 集合名带版本后缀（{@code kb_chunk_v1}）：Milvus 集合维度建好后**不可改**，
 * 换嵌入模型只能新建集合名再回填（风险 R1）。
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
@ConditionalOnProperty(name = "aioa.kb.store", havingValue = "milvus")
public class MilvusConfig {

    /** 主键（= kb_chunk.id，由 MySQL 权威分配，不用自增）。 */
    public static final String F_PK = "pk";
    /** 稠密向量。 */
    public static final String F_VECTOR = "vector";
    /** BM25 稀疏向量（Function 输出字段）。 */
    public static final String F_SPARSE = "sparse";
    /** 切片正文（进 Milvus 是为了原生 BM25，同时也省掉回查 MySQL 取正文）。 */
    public static final String F_CONTENT = "content";
    /** 租户（同时是 partition key）。 */
    public static final String F_TENANT = "tenant_id";
    /** 归属用户（本人 / 0=公共资源）。 */
    public static final String F_USER = "user_id";
    /** 所属文档。 */
    public static final String F_DOC = "doc_id";
    /** 切片序号。 */
    public static final String F_CHUNK_INDEX = "chunk_index";
    /** 可见范围（PERSONAL / TENANT）。 */
    public static final String F_SCOPE = "scope";
    /** 可选文档名：仅作 MySQL 查不到时的兜底展示，权威值始终取 kb_document.doc_name。 */
    public static final String F_DOC_NAME = "doc_name";

    /** 正文最大长度（Milvus VarChar 上限 65535，留余量并按 utf-8 字节计）。 */
    private static final int CONTENT_MAX_LENGTH = 8192;

    private final KbProperties props;

    /**
     * 引导结果：store 需要据此决定「是否走服务端 BM25」以及集合维度。
     *
     * @param name 集合名
     * @param dims 稠密向量维度
     * @param bm25 集合中是否具备 BM25 稀疏列（false 时 hybrid/bm25 走 MySQL 关键词兜底 + 客户端 RRF）
     */
    public record CollectionInfo(String name, int dims, boolean bm25) {
    }

    @Bean(destroyMethod = "close")
    public MilvusClientV2 milvusClient() {
        KbProperties.Milvus m = props.getMilvus();
        if (!MilvusFilter.validCollectionName(m.getCollection())) {
            throw new IllegalStateException("aioa.kb.milvus.collection 名字非法：" + m.getCollection()
                    + "（只允许字母/数字/下划线，首字符不能是数字）");
        }
        ConnectConfig.ConnectConfigBuilder cb = ConnectConfig.builder()
                .uri(m.getUri())
                .connectTimeoutMs(m.getTimeoutMs());
        if (notBlank(m.getToken())) {
            cb.token(m.getToken());
        }
        if (notBlank(m.getDatabase()) && !"default".equalsIgnoreCase(m.getDatabase())) {
            cb.dbName(m.getDatabase());
        }
        MilvusClientV2 client = null;
        try {
            // 注意：SDK 构造器本身就会做连接预检（ConnectConfig.enablePrecheck 默认 true），
            // 所以「Milvus 连不上」通常在这里就炸，而不是在后面的 hasCollection。
            // 两处必须包在同一个 try 里——否则运维看到的是裸 gRPC DEADLINE_EXCEEDED，
            // 完全不知道自己该改哪个配置项。
            client = new MilvusClientV2(cb.build());
            client.hasCollection(HasCollectionReq.builder().collectionName(m.getCollection()).build());
        } catch (Exception e) {
            safeClose(client);
            throw new IllegalStateException(
                    "Milvus 不可用，应用拒绝启动（aioa.kb.store=milvus 要求 Milvus 必须在线；"
                            + "不存在「降级为空结果」这条路——那是 ElasticKnowledgeStore 踩过的坑）。"
                            + " uri=" + m.getUri() + "，collection=" + m.getCollection()
                            + "，原因=" + e.getMessage(), e);
        }
        log.info("Milvus 连接成功：uri={} collection={}", m.getUri(), m.getCollection());
        return client;
    }

    @Bean
    public CollectionInfo milvusCollectionInfo(MilvusClientV2 client) {
        KbProperties.Milvus m = props.getMilvus();
        String name = m.getCollection();

        boolean exists = Boolean.TRUE.equals(
                client.hasCollection(HasCollectionReq.builder().collectionName(name).build()));

        boolean bm25 = m.isEnableBm25();
        if (!exists) {
            log.info("Milvus 集合不存在，开始创建：{} dims={} bm25={}", name, m.getDims(), bm25);
            if (bm25) {
                try {
                    createCollection(client, m, true);
                } catch (Exception e) {
                    log.warn("Milvus 原生 BM25 建集合失败（服务端可能低于 2.5 或缺 analyzer），"
                                    + "退回纯稠密模式：hybrid/bm25 的关键词腿改由 MySQL 兜底 + 客户端 RRF。原因={}",
                            e.getMessage());
                    bm25 = false;
                }
            }
            if (!bm25) {
                createCollection(client, m, false);
            }
            log.info("Milvus 集合创建完成：{} bm25={}", name, bm25);
        } else {
            DescribeCollectionResp d = client.describeCollection(
                    DescribeCollectionReq.builder().collectionName(name).build());
            int existingDim = 0;
            CreateCollectionReq.FieldSchema vecField =
                    d.getCollectionSchema() == null ? null : d.getCollectionSchema().getField(F_VECTOR);
            if (vecField != null && vecField.getDimension() != null) {
                existingDim = vecField.getDimension();
            }
            if (existingDim > 0 && m.getDims() > 0 && existingDim != m.getDims()) {
                throw new IllegalStateException("Milvus 集合 " + name + " 的向量维度是 " + existingDim
                        + "，与配置 aioa.kb.milvus.dims=" + m.getDims() + " 不一致。"
                        + "Milvus 集合维度创建后不可改，请新建集合名（如 kb_chunk_v2）并开启回填后重试。");
            }
            List<String> fieldNames = d.getFieldNames() == null ? List.of() : d.getFieldNames();
            boolean hasSparse = fieldNames.contains(F_SPARSE);
            if (hasSparse != bm25) {
                log.warn("Milvus 集合 {} 的稀疏列(bm25)实际为 {}，与配置 aioa.kb.milvus.enable-bm25={} 不一致，"
                        + "以集合实际为准（改 schema 需重建集合）。", name, hasSparse, bm25);
                bm25 = hasSparse;
            }
            log.info("Milvus 集合已存在：{} dims={} bm25={}", name, existingDim, bm25);
        }

        client.loadCollection(LoadCollectionReq.builder().collectionName(name).build());
        return new CollectionInfo(name, m.getDims(), bm25);
    }

    // ---------- 建集合 ----------

    private void createCollection(MilvusClientV2 client, KbProperties.Milvus m, boolean withBm25) {
        CreateCollectionReq.CollectionSchema.CollectionSchemaBuilder sb = CreateCollectionReq.CollectionSchema.builder()
                .enableDynamicField(false)
                .fieldSchemaList(fields(m, withBm25));
        if (withBm25) {
            sb.functionList(List.of(CreateCollectionReq.Function.builder()
                    .name("content_bm25")
                    .description("content -> sparse（Milvus 2.5 原生 BM25）")
                    .functionType(FunctionType.BM25)
                    .inputFieldNames(List.of(F_CONTENT))
                    .outputFieldNames(List.of(F_SPARSE))
                    .build()));
        }

        CreateCollectionReq req = CreateCollectionReq.builder()
                .collectionName(m.getCollection())
                .description("AIOA 知识库切片向量索引（权威数据在 MySQL kb_chunk，本集合可随时重建）")
                .collectionSchema(sb.build())
                .indexParams(indexes(m, withBm25))
                // STRONG：写入立即可检索（风险 R4「刚上传检索不到」）。索引副本场景下这点延迟可接受。
                .consistencyLevel(ConsistencyLevel.STRONG)
                .build();
        client.createCollection(req);
    }

    private List<CreateCollectionReq.FieldSchema> fields(KbProperties.Milvus m, boolean withBm25) {
        List<CreateCollectionReq.FieldSchema> list = new ArrayList<>();
        // 主键：直接用 kb_chunk.id，保证 upsert 幂等（重跑入库不会产生重复行）
        list.add(CreateCollectionReq.FieldSchema.builder()
                .name(F_PK).dataType(DataType.Int64)
                .isPrimaryKey(true).autoID(false)
                .description("kb_chunk.id").build());
        list.add(CreateCollectionReq.FieldSchema.builder()
                .name(F_VECTOR).dataType(DataType.FloatVector)
                .dimension(m.getDims()).build());
        if (withBm25) {
            list.add(CreateCollectionReq.FieldSchema.builder()
                    .name(F_SPARSE).dataType(DataType.SparseFloatVector).build());
        }
        list.add(CreateCollectionReq.FieldSchema.builder()
                .name(F_CONTENT).dataType(DataType.VarChar)
                .maxLength(CONTENT_MAX_LENGTH)
                .enableAnalyzer(true)
                .description("切片正文：原生 BM25 输入，同时免去检索回查 MySQL 取原文").build());
        // tenant_id 是 partition key：物理分区 + 检索时分区裁剪（决策 D5，多租户隔离）
        list.add(CreateCollectionReq.FieldSchema.builder()
                .name(F_TENANT).dataType(DataType.Int64)
                .isPartitionKey(true).build());
        list.add(CreateCollectionReq.FieldSchema.builder().name(F_USER).dataType(DataType.Int64).build());
        list.add(CreateCollectionReq.FieldSchema.builder().name(F_DOC).dataType(DataType.Int64).build());
        list.add(CreateCollectionReq.FieldSchema.builder().name(F_CHUNK_INDEX).dataType(DataType.Int64).build());
        list.add(CreateCollectionReq.FieldSchema.builder()
                .name(F_SCOPE).dataType(DataType.VarChar).maxLength(16).build());
        list.add(CreateCollectionReq.FieldSchema.builder()
                .name(F_DOC_NAME).dataType(DataType.VarChar).maxLength(512).build());
        return list;
    }

    private List<IndexParam> indexes(KbProperties.Milvus m, boolean withBm25) {
        List<IndexParam> list = new ArrayList<>();
        IndexParam.IndexParamBuilder dense = IndexParam.builder()
                .fieldName(F_VECTOR)
                .metricType(metricOf(m.getMetricType()));
        if ("AUTOINDEX".equalsIgnoreCase(m.getIndexType())) {
            dense.indexType(IndexParam.IndexType.AUTOINDEX);
        } else if ("FLAT".equalsIgnoreCase(m.getIndexType())) {
            dense.indexType(IndexParam.IndexType.FLAT);
        } else {
            dense.indexType(IndexParam.IndexType.HNSW)
                    .extraParams(Map.<String, Object>of(
                            "M", m.getHnswM(), "efConstruction", m.getHnswEfConstruction()));
        }
        list.add(dense.build());
        if (withBm25) {
            list.add(IndexParam.builder()
                    .fieldName(F_SPARSE)
                    .indexType(IndexParam.IndexType.SPARSE_INVERTED_INDEX)
                    .metricType(IndexParam.MetricType.BM25)
                    .build());
        }
        return list;
    }

    /** 配置里的度量名 → SDK 枚举（未知值退化为 COSINE，与建集合时的默认一致）。 */
    public static IndexParam.MetricType metricOf(String name) {
        if (name == null) {
            return IndexParam.MetricType.COSINE;
        }
        return switch (name.toUpperCase()) {
            case "IP" -> IndexParam.MetricType.IP;
            case "L2" -> IndexParam.MetricType.L2;
            default -> IndexParam.MetricType.COSINE;
        };
    }

    private static boolean notBlank(String s) {
        return s != null && !s.isBlank();
    }

    private static void safeClose(MilvusClientV2 client) {
        if (client == null) {
            return;
        }
        try {
            client.close();
        } catch (Exception ignored) {
            // 关闭失败无所谓：此时已经在抛启动异常了
        }
    }
}
