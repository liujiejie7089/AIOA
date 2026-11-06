package cn.aios.resource.store;

import cn.aios.resource.entity.KbChunk;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 关键词打分单测（docs/32 Ph3 抽公共）。
 *
 * <p>两个档位（mysql（内联实现）与 milvus 档位在「集合无 BM25 稀疏列」时的兜底路径）
 * 共用这一份打分，所以这里既测「行为正确」也测「口径不变」。</p>
 */
class KeywordScorerTest {

    private static KbChunk chunk(long id, String content) {
        KbChunk c = new KbChunk();
        c.setId(id);
        c.setContent(content);
        return c;
    }

    @Test
    @DisplayName("无重叠 → 不产生分数（不会被召回）")
    void noOverlapNoScore() {
        Map<Long, Double> s = KeywordScorer.score(List.of(chunk(1, "完全无关的一句话")), "年度预算");
        assertTrue(s.isEmpty());
    }

    @Test
    @DisplayName("重叠越多分越高")
    void moreOverlapScoresHigher() {
        KbChunk weak = chunk(1, "预算");
        KbChunk strong = chunk(2, "年度预算编制说明");
        Map<Long, Double> s = KeywordScorer.score(List.of(weak, strong), "年度预算");
        assertTrue(s.containsKey(1L) && s.containsKey(2L), "两个切片都含 2-gram 命中: " + s);
        assertTrue(s.get(2L) > s.get(1L), "覆盖更全的切片分更高: " + s);
    }

    @Test
    @DisplayName("空查询 / 空列表 → 空结果，不抛异常")
    void degenerateInputs() {
        assertTrue(KeywordScorer.score(List.of(chunk(1, "abc")), "").isEmpty());
        assertTrue(KeywordScorer.score(List.of(chunk(1, "abc")), null).isEmpty());
        assertTrue(KeywordScorer.score(List.of(), "预算").isEmpty());
        assertTrue(KeywordScorer.score(null, "预算").isEmpty());
        assertTrue(KeywordScorer.score(List.of(chunk(1, "abc")), "  ").isEmpty());
    }

    @Test
    @DisplayName("主键为 null 的切片被跳过（避免 NPE / 脏键）")
    void nullIdSkipped() {
        KbChunk c = chunk(0, "年度预算");
        c.setId(null);
        assertTrue(KeywordScorer.score(List.of(c), "年度预算").isEmpty());
    }

    @Test
    @DisplayName("正文为 null 视为空串，不抛 NPE")
    void nullContentTolerated() {
        assertFalse(KeywordScorer.score(List.of(chunk(1, null)), "预算").containsKey(1L));
    }

    @Test
    @DisplayName("ngram：长度<=2 整体成词，>2 按 2-gram 滑窗")
    void ngramRules() {
        assertEquals(List.of("预算"), KeywordScorer.ngrams("预算"));
        assertEquals(List.of("ab"), KeywordScorer.ngrams(" ab "));
        assertEquals(List.of("年度", "度预", "预算"), KeywordScorer.ngrams("年度预算"));
        assertTrue(KeywordScorer.ngrams("   ").isEmpty());
    }

    // ---------- BM25 改造后的区分度（docs/74 根因 4） ----------

    @Test
    @DisplayName("稀有词压过常见词：含「川剧」的行必须高于只含「项目」的行")
    void rareTermOutranksCommonTerm() {
        List<KbChunk> chunks = new java.util.ArrayList<>();
        for (int i = 1; i <= 50; i++) {
            chunks.add(chunk(i, "| " + i + " | 项目" + i + " | 传统技艺 | 成都市 | 第六批 |"));
        }
        chunks.add(chunk(99, "| 99 | 川剧 | 传统戏剧 | 成都市 | 第一批 |"));
        Map<Long, Double> s = KeywordScorer.score(chunks, "川剧项目");
        assertTrue(s.containsKey(99L), "含稀有词的切片必须被召回: " + s.containsKey(99L));
        double rare = s.get(99L);
        double commonMax = s.entrySet().stream().filter(e -> e.getKey() != 99L)
                .mapToDouble(Map.Entry::getValue).max().orElse(0);
        assertTrue(rare > commonMax,
                "稀有项必须排最前（IDF 生效）：rare=" + rare + " commonMax=" + commonMax);
    }

    @Test
    @DisplayName("TF 饱和：同一 gram 重复多次不会线性加分")
    void termFrequencySaturates() {
        Map<Long, Double> once = KeywordScorer.score(List.of(chunk(1, "川剧")), "川剧");
        Map<Long, Double> many = KeywordScorer.score(List.of(chunk(2, "川剧川剧川剧川剧川剧川剧川剧川剧")), "川剧");
        // 8 次出现但分数不应达到 1 次的 5 倍以上（BM25 的 k1 饱和；老口径会随 hit 继续长）
        assertTrue(many.get(2L) < once.get(1L) * 2.0,
                "once=" + once.get(1L) + " many=" + many.get(2L));
    }

    @Test
    @DisplayName("同构行不再同分：内容相同同分、内容不同必分")
    void distinctRowsGetDistinctScores() {
        KbChunk a = chunk(1, "| 1 | 川剧 | 传统戏剧 | 成都市 | 第一批 |");
        KbChunk b = chunk(2, "| 2 | 项目 | 传统技艺 | 绵阳市 | 第二批 |");
        KbChunk c = chunk(3, "| 1 | 川剧 | 传统戏剧 | 成都市 | 第一批 |");
        Map<Long, Double> s = KeywordScorer.score(List.of(a, b, c), "川剧项目");
        assertTrue(s.containsKey(1L) && s.containsKey(2L), "两行都应命中: " + s);
        assertEquals(s.get(1L), s.get(3L), 1e-9, "内容相同就该同分（确定性的前提）");
        assertNotEquals(s.get(1L), s.get(2L), "同分塌陷已修复：不同内容必须可分");
    }

    @Test
    @DisplayName("occurrences 计数正确（非重叠）")
    void occurrencesCount() {
        assertEquals(0, KeywordScorer.occurrences("abc", "z"));
        assertEquals(1, KeywordScorer.occurrences("川剧", "川剧"));
        assertEquals(3, KeywordScorer.occurrences("川剧川剧川剧", "川剧"));
        assertEquals(0, KeywordScorer.occurrences("川剧", ""));
        // B5：把「非重叠」钉死 —— 滑窗会给出 2，本实现给 1（「aa」在「aaa」里只有一处不重叠匹配）
        assertEquals(1, KeywordScorer.occurrences("aaa", "aa"));
    }
}
