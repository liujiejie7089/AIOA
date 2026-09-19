package cn.aioa.resource.store;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * RRF 融合单测（docs/32 Ph3）。
 *
 * <p>为什么要单独测：融合口径一旦在两档（mysql / milvus）之间漂移，
 * 「同一批用例双跑」就无法对齐，而排序错误的表现只是「结果不太对」——很难在 E2E 里发现。
 * 这里把 mt 的数学口径钉死：{@code 1 / (60 + rank + 1)}，rank 从 0 起。</p>
 */
class RrfFusionTest {

    @Test
    @DisplayName("融合分 = 各路 1/(k+rank+1) 之和，两路都命中的排最前")
    void fuseSumsReciprocalRanks() {
        Map<Long, Double> keywordLeg = new LinkedHashMap<>();
        keywordLeg.put(100L, 0.9);
        keywordLeg.put(200L, 0.5);
        Map<Long, Double> denseLeg = new LinkedHashMap<>();
        denseLeg.put(200L, 0.8);
        denseLeg.put(300L, 0.4);

        Map<Long, Double> fused = RrfFusion.fuse(List.of(keywordLeg, denseLeg));

        // 200 是两路都命中 → 1/62 + 1/61；100 只在关键词路 rank0 → 1/61；300 只在向量路 rank1 → 1/62
        assertEquals(1.0 / 62 + 1.0 / 61, fused.get(200L), 1e-12);
        assertEquals(1.0 / 61, fused.get(100L), 1e-12);
        assertEquals(1.0 / 62, fused.get(300L), 1e-12);
        assertEquals(List.of(200L, 100L, 300L), RrfFusion.topK(fused, 3));
    }

    @Test
    @DisplayName("只有排名参与计算：分数绝对值大小不影响结果")
    void onlyRankMatters() {
        Map<Long, Double> big = new LinkedHashMap<>();
        big.put(1L, 9999.0);
        big.put(2L, 0.001);
        Map<Long, Double> small = new LinkedHashMap<>();
        small.put(1L, 0.0001);
        small.put(2L, 9999.0);

        assertEquals(List.of(1L, 2L), RrfFusion.topK(RrfFusion.fuse(List.of(big)), 5));
        // 两路排名完全相反 → 分数相等，顺序退化为不确定，但两者分值必须相等
        Map<Long, Double> both = RrfFusion.fuse(List.of(big, small));
        assertEquals(both.get(1L), both.get(2L), 1e-12);
    }

    @Test
    @DisplayName("空腿不参与融合（纯关键词模式下列表仍可用）")
    void emptyLegIsIgnored() {
        Map<Long, Double> leg = new LinkedHashMap<>();
        leg.put(5L, 1.0);
        Map<Long, Double> fused = RrfFusion.fuse(List.of(Map.of(), leg));
        assertEquals(1, fused.size());
        assertEquals(1.0 / 61, fused.get(5L), 1e-12);
    }

    @Test
    @DisplayName("topK 截断不会越界")
    void topKClamps() {
        Map<Long, Double> fused = RrfFusion.fuse(List.of(Map.of(1L, 1.0, 2L, 0.5)));
        assertEquals(2, RrfFusion.topK(fused, 10).size());
        assertEquals(1, RrfFusion.topK(fused, 1).size());
        assertTrue(RrfFusion.topK(Map.of(), 5).isEmpty());
    }

    @Test
    @DisplayName("RRF 常数保持在 60（与 Elasticsearch 生产默认、与重构前的 MysqlKnowledgeStore 一致）")
    void kIsStable() {
        assertEquals(60.0, RrfFusion.RRF_K, 0.0);
    }
}
