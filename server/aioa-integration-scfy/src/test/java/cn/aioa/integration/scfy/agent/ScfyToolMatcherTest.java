package cn.aioa.integration.scfy.agent;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 语义匹配器的行为钉死。
 *
 * <p>这些用例是「可替换匹配器」的<b>契约测试</b>：如果将来换成向量或大模型匹配器，
 * 应<b>原样复用这组问句</b> —— 换实现可以改变分数，但不能改变「这句话该用哪个接口」。
 * 否则「可替换」就退化成「换个实现、行为全变」。</p>
 *
 * <p>正例断言到<b>具体工具编码</b>，不停留在「分组对了」：同一分组内
 * 「有哪些工坊」与「工坊卖了多少」是两个不同接口，答错一个就是答非所问。</p>
 */
class ScfyToolMatcherTest {

    private final ToolMatcher matcher = new LexicalToolMatcher();
    private final ScfyAgentCatalog catalog = AgentTestSupport.catalog();

    private record Case(String question, String expectToolCode) {
    }

    /** 真实问句 → 期望接口。每条都对应一个真实的用户意图。 */
    private static final List<Case> CASES = List.of(
            new Case("成都有哪些非遗工坊", "scfy_shop_table"),
            // 「有多少」问的是数量：各等级数量接口是按等级给出数量（国家/省/市/县），
            // 而列表接口虽然也返回 totalCount，但对「各等级分别多少」无能为力
            new Case("甘孜州有多少非遗项目", "scfy_project_count_by_area"),
            new Case("哪个市州非遗项目最多", "scfy_project_area_summary"),
            // 注意这里期望的是「列表」而不是「各市州数量对比」：后者没有任何能收市州名的参数，
            // 它只会返回全省 21 个市州的对比，回答不了「成都这一个市」有多少；
            // 而列表接口返回 totalCount，恰好是该市州的传承人总数（实测口径）
            new Case("成都有多少非遗传承人", "scfy_inheritor_list_by_area"),
            new Case("四川有哪些文化生态保护区", "scfy_eco_area_top_list"),
            new Case("非遗旅游线路有哪些", "scfy_travel_route_top_list"),
            new Case("国家级非遗项目的门类分布是怎样的", "scfy_project_type_data"),
            new Case("非遗传承人的性别比例", "scfy_inheritor_gender_data")
    );

    @Test
    @DisplayName("真实问句命中的是正确的接口")
    void realQuestionsHitTheRightTool() {
        List<String> failures = new ArrayList<>();
        for (Case c : CASES) {
            List<ToolMatcher.Match> ranked = matcher.rank(c.question(), catalog.registered(), 3);
            System.out.println("[matcher] 「" + c.question() + "」 → "
                    + (ranked.isEmpty() ? "（无候选）" : ranked.get(0).line()));
            for (ToolMatcher.Match m : ranked) {
                System.out.println("            " + m.line());
            }
            String actual = ranked.isEmpty() ? null : ranked.get(0).tool().toolCode();
            if (!c.expectToolCode().equals(actual)) {
                failures.add("「" + c.question() + "」期望 " + c.expectToolCode() + "，实际 " + actual);
            }
        }
        assertTrue(failures.isEmpty(), "匹配结果与期望不符：\n  - " + String.join("\n  - ", failures));
    }

    @Test
    @DisplayName("与本系统无关的问题不得匹配到任何接口")
    void unrelatedQuestionsDoNotMatch() {
        List<String> questions = List.of(
                "帮我订一张明天去北京的机票",
                "今天成都的天气怎么样",
                "帮我写一首关于春天的诗"
        );
        for (String q : questions) {
            List<ToolMatcher.Match> ranked = matcher.rank(q, catalog.registered(), 3);
            String top = ranked.isEmpty() ? "（空）" : ranked.get(0).line();
            System.out.println("[matcher-负例] 「" + q + "」 → " + top);
            assertTrue(ranked.isEmpty() || ranked.get(0).score() < matcher.minScore(),
                    "无关问题不应达到匹配阈值，否则会调用错误接口并返回答非所问的数据。实际：" + top);
        }
    }

    @Test
    @DisplayName("匹配结果确定可复现：同一句话多次匹配结果完全一致")
    void rankingIsDeterministic() {
        String q = "成都有哪些非遗工坊";
        List<String> first = matcher.rank(q, catalog.registered(), 5).stream()
                .map(m -> m.tool().toolCode() + "@" + m.score()).toList();
        for (int i = 0; i < 5; i++) {
            List<String> again = matcher.rank(q, catalog.registered(), 5).stream()
                    .map(m -> m.tool().toolCode() + "@" + m.score()).toList();
            assertEquals(first, again, "同一句话的匹配结果必须逐次一致（含分数）");
        }
    }

    @Test
    @DisplayName("空问题与空候选集不抛异常，返回空结果")
    void handlesEmptyInput() {
        assertTrue(matcher.rank(null, catalog.registered(), 3).isEmpty());
        assertTrue(matcher.rank("   ", catalog.registered(), 3).isEmpty());
        assertTrue(matcher.rank("成都有哪些非遗工坊", List.of(), 3).isEmpty());
    }

    @Test
    @DisplayName("返回结构字段名参与匹配：按结果字段提问也能命中")
    void fieldNamesParticipateInMatching() {
        // 「subject_name」是工坊列表的实测字段；用户问「工坊名称」时不应落到别的分组
        List<ToolMatcher.Match> ranked = matcher.rank("成都市非遗工坊的名称和销量", catalog.registered(), 3);
        assertFalse(ranked.isEmpty());
        assertEquals("工坊", ranked.get(0).tool().group(),
                "按工坊字段提问应落在工坊分组，实际：" + ranked.get(0).line());
    }

    @Test
    @DisplayName("匹配器自报实现名与阈值 —— 换实现后结果里能看出是谁做的判定")
    void exposesIdentity() {
        assertEquals("lexical-bigram-idf", matcher.name());
        assertTrue(matcher.minScore() > 0 && matcher.minScore() < 1);
    }
}
