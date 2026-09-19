package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbChunk;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
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
}
