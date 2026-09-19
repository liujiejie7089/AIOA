package cn.aioa.resource.store;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 可见性过滤表达式单测（docs/32 Ph2）。
 *
 * <p>这是整个 Milvus 改造里**最需要被锁死**的一段逻辑：跨租户泄露是风险 R5（最高级别）。
 * 表达式是纯字符串拼接，没有真 Milvus 也能验。</p>
 */
class MilvusFilterTest {

    @Test
    @DisplayName("可见性表达式必须同时含 租户 + 本人 + 公共 + 租户共享 四个条件")
    void visibilityCoversAllFourConditions() {
        String expr = MilvusFilter.visibility(2L, 7L, null);
        assertEquals("tenant_id == 2 and (user_id == 7 or user_id == 0 or scope == \"TENANT\")", expr);
    }

    @Test
    @DisplayName("跨租户隔离：租户 id 必须作为第一条件出现")
    void tenantIsAlwaysFirstCondition() {
        assertTrue(MilvusFilter.visibility(9L, 7L, null).startsWith("tenant_id == 9"));
        assertTrue(MilvusFilter.visibility(0L, 0L, null).startsWith("tenant_id == 0"));
    }

    @Test
    @DisplayName("知识库范围（kbScope）以 doc_id in [...] 追加，不破坏前面的可见性分组")
    void docScopeAppendsInClause() {
        String expr = MilvusFilter.visibility(2L, 7L, List.of(11L, 22L));
        assertEquals("tenant_id == 2 and (user_id == 7 or user_id == 0 or scope == \"TENANT\")"
                + " and doc_id in [11, 22]", expr);
    }

    @Test
    @DisplayName("null 表示不限范围；空列表必须被拒绝（空范围 ≠ 不限范围，两种读法都是错）")
    void nullScopeMeansAllEmptyScopeRejected() {
        assertFalse(MilvusFilter.visibility(1L, 1L, null).contains("doc_id"));
        assertThrows(IllegalArgumentException.class, () -> MilvusFilter.visibility(1L, 1L, List.of()));
    }

    @Test
    @DisplayName("删除表达式必须带 tenant_id（既是隔离条件也是分区裁剪条件）")
    void deleteExprCarriesTenant() {
        assertEquals("tenant_id == 3 and doc_id == 42", MilvusFilter.docInTenant(3L, 42L));
    }

    @Test
    @DisplayName("集合名合法性：首字符不能是数字，只允许字母数字下划线")
    void collectionNameRules() {
        assertTrue(MilvusFilter.validCollectionName("kb_chunk_v1"));
        assertTrue(MilvusFilter.validCollectionName("_x"));
        assertFalse(MilvusFilter.validCollectionName("1kb_chunk"));
        assertFalse(MilvusFilter.validCollectionName("kb-chunk"));
        assertFalse(MilvusFilter.validCollectionName(""));
        assertFalse(MilvusFilter.validCollectionName(null));
        assertFalse(MilvusFilter.validCollectionName("a".repeat(256)));
    }
}
