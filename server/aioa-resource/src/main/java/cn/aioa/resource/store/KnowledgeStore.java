package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbDocument;

import java.util.List;

/**
 * 知识库存储层 SPI（FR-F）：把「文档 + 切片 + 检索」的物理实现与业务层解耦。
 *
 * <p>现阶段由 {@link MysqlKnowledgeStore} 提供 MySQL（LIKE 检索）实现；
 * 后续切换向量数据库（pgvector / Milvus / ES dense_vector）时新增实现类并修改配置
 * {@code aioa.kb.store=vector} 即可，KbService、工具网关、管理端/用户端与已接入的
 * 业务系统均无需改动（面向接口编程，切换零感知）。</p>
 *
 * <p>实现约定：</p>
 * <ul>
 *   <li>可见性：{@code listVisible / search} 必须只返回「本人 + 租户共享 + 公共资源」，
 *       跨租户数据零泄露（FR-B3），该规则与物理实现无关；</li>
 *   <li>切片：{@code replaceChunks} 需先清旧切片再写入，保证幂等（重跑不重复）；</li>
 *   <li>检索：命中返回原文片段（snippet），供 AI 引用溯源（FR-D5）。</li>
 * </ul>
 */
public interface KnowledgeStore {

    /** 存储实现标识：mysql / vector / ...，与配置 aioa.kb.store 对应。 */
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

    /** 关键词检索：优先切片正文匹配，未命中退回文档名匹配；返回带原文片段的命中。 */
    List<KbHit> search(Long tenantId, Long userId, String keyword, int limit);

    /** 检索命中：文档 + 原文片段 + 片段序号（引用溯源最小单元）。 */
    record KbHit(Long docId, String docName, String snippet, Integer chunkIndex) {
    }
}
