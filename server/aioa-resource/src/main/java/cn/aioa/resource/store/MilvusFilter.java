package cn.aioa.resource.store;

import java.util.List;
import java.util.StringJoiner;

/**
 * Milvus 过滤表达式构造（docs/32 Ph2，纯函数、可单测、不依赖 Milvus 连接）。
 *
 * <p>把 SPI 契约里最危险的一条——**可见性隔离**——收敛成一个可单测的纯函数，
 * 避免它散落在 {@code search} / {@code deleteDocument} / 回填等多处。</p>
 *
 * <p>可见性口径（与 {@code MysqlKnowledgeStore.listVisible} 必须逐字一致）：</p>
 * <pre>
 *   tenant_id == {租户}                                            // 跨租户零泄露（FR-B3）
 *   and (user_id == {本人} or user_id == 0 or scope == "TENANT")   // 本人 + 公共资源 + 租户共享
 *   [and doc_id in [{...}]]                                        // 可选：知识库范围（kbScope）
 * </pre>
 *
 * <p><b>注意</b>：{@code tenant_id} 同时是集合的 partition key，Milvus 会用它做分区裁剪；
 * 表达式里的该条件既保证正确性，也让检索只落到目标租户的分区上（决策 D5）。</p>
 */
public final class MilvusFilter {

    /** 租户共享可见范围字面量（与 {@code KbService.SCOPE_TENANT} 同值）。 */
    public static final String SCOPE_TENANT = "TENANT";

    /** 公共资源归属用户（可见性口径的一部分）。 */
    public static final long PUBLIC_USER_ID = 0L;

    private MilvusFilter() {
    }

    /**
     * 构造可见性过滤表达式。
     *
     * @param restrictedDocIds 已与「可见文档」求过交集的文档范围：
     *                         {@code null} = 不限范围（全可见）；
     *                         非空列表 = 追加 {@code doc_id in [...]}。
     *                         <b>空列表会被拒绝</b>（{@link IllegalArgumentException}）：
     *                         它同时有两种危险读法——「不限范围」（静默越权）或
     *                         「{@code doc_id in []}」（非法表达式）。调用方必须在求交集后
     *                         先用空判断短路返回空结果，再调本方法。宁可抛，不要猜。
     */
    public static String visibility(long tenantId, long userId, List<Long> restrictedDocIds) {
        if (restrictedDocIds != null && restrictedDocIds.isEmpty()) {
            throw new IllegalArgumentException(
                    "restrictedDocIds 为空列表：调用方应先短路返回空结果（空范围 ≠ 不限范围）");
        }
        StringBuilder sb = new StringBuilder(96);
        sb.append("tenant_id == ").append(tenantId);
        sb.append(" and (user_id == ").append(userId)
                .append(" or user_id == ").append(PUBLIC_USER_ID)
                .append(" or scope == \"").append(SCOPE_TENANT).append("\")");
        if (restrictedDocIds != null) {
            sb.append(" and doc_id in [");
            StringJoiner sj = new StringJoiner(", ");
            for (Long id : restrictedDocIds) {
                sj.add(String.valueOf(id));
            }
            sb.append(sj).append("]");
        }
        return sb.toString();
    }

    /** 删除单个文档的表达式：必须带 tenant_id（既是隔离条件，也是分区裁剪条件）。 */
    public static String docInTenant(long tenantId, long docId) {
        return "tenant_id == " + tenantId + " and doc_id == " + docId;
    }

    /** 集合名合法性（Milvus 规则：字母/数字/下划线，首字符不能是数字，长度 1–255）。 */
    public static boolean validCollectionName(String name) {
        return name != null && name.matches("[A-Za-z_][A-Za-z0-9_]{0,254}");
    }
}
