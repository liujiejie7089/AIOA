package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbDocument;

import java.util.List;

/**
 * 知识库存储层 SPI（FR-F / 方案 P2）：把「文档 + 切片 + 检索」的物理实现与业务层解耦。
 *
 * <p>实现：{@link MysqlKnowledgeStore}（MySQL + 内置向量，默认）、
 * {@link ElasticKnowledgeStore}（Elasticsearch dense_vector，预留）。
 * 切换方式：{@code aioa.kb.store=mysql|elasticsearch}（@ConditionalOnProperty），业务层零改动。</p>
 *
 * <p>实现约定：</p>
 * <ul>
 *   <li>可见性：{@code listVisible / search} 必须只返回「本人 + 租户共享 + 公共资源」，
 *       跨租户数据零泄露（FR-B3），该规则与物理实现无关；</li>
 *   <li>切片：{@code replaceChunks} 需先清旧切片再写入，保证幂等（重跑不重复）；</li>
 *   <li>检索：命中返回原文片段（snippet）与相似度分数（score），供引用溯源与阈值过滤（FR-D5）。</li>
 * </ul>
 */
public interface KnowledgeStore {

    /** 存储实现标识：mysql / elasticsearch，与配置 aioa.kb.store 对应。 */
    String type();

    /** 新增文档（未切片）。 */
    KbDocument saveDocument(KbDocument doc);

    /** 更新文档元信息与正文（state / chunkCount / errorMsg 等全量字段）。 */
    KbDocument updateDocument(KbDocument doc);

    /** 按主键取文档，不存在返回 null。 */
    KbDocument findDocById(Long docId);

    /** 删除文档及其全部切片（物理或逻辑删除由实现决定）。 */
    void deleteDocument(Long docId);

    /** 当前用户可见的文档：本人 + 租户共享（TENANT）+ 公共资源（userId=0），按时间倒序。 */
    List<KbDocument> listVisible(Long tenantId, Long userId);

    /** 租户内全部文档（管理端运营视角，调用方自行校验管理员角色）。 */
    List<KbDocument> listTenant(Long tenantId);

    /** 用给定切片整体替换该文档的切片（先清后写，幂等）。 */
    int replaceChunks(KbDocument doc, List<String> chunks);

    /**
     * 向量化并持久化一个切片（在 replaceChunks 之后由调用方逐个调用）。
     *
     * @param chunkId 切片主键
     * @param content 切片正文
     * @param vector  已计算的向量（由 EmbeddingProvider 产出）
     * @param provider provider 标识
     * @param dims     向量维度
     */
    void saveEmbedding(Long chunkId, String content, float[] vector, String provider, int dims);

    /**
     * 混合检索：关键词（BM25 语义）+ 向量（余弦）召回后按 RRF 融合。
     *
     * @param query      用户问句
     * @param queryVec   问句向量（可为 null，表示跳过向量召回、纯关键词）
     * @param topK       返回条数
     * @param threshold  相似度阈值，低于该分的命中被丢弃（仅对向量召回生效）
     * @param mode       vector / bm25 / hybrid
     * @param docIdScope 知识库范围过滤：null/空=ALL，否则只在这些文档内检索
     * @return 带分数的命中，按融合分降序
     */
    List<KbHit> search(Long tenantId, Long userId, String query, float[] queryVec,
                       int topK, double threshold, String mode, List<Long> docIdScope);

    /**
     * 兼容旧签名：纯关键词检索，等效 mode=bm25、topK=limit、无阈值、无范围。
     * 供未迁移的调用方（如工具网关旧版）继续使用。
     */
    List<KbHit> search(Long tenantId, Long userId, String keyword, int limit);

    /** 检索命中：文档 + 原文片段 + 片段序号 + 相似度（引用溯源最小单元）。 */
    record KbHit(Long docId, String docName, String snippet, Integer chunkIndex, Float score) {
        /** 兼容旧构造（无分数）。 */
        public KbHit(Long docId, String docName, String snippet, Integer chunkIndex) {
            this(docId, docName, snippet, chunkIndex, null);
        }
    }
}
