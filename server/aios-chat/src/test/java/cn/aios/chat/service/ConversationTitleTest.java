package cn.aios.chat.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「标题写成用户的问题总结」（V108）。
 *
 * <p>用户端的「最近」列表原来直接显示 {@code chat_conversation.title}，于是脚本/集成方
 * create 时传的技术名（{@code grade-sheet-probe}、{@code enum-probe}）与缺省的「新会话」
 * 全都直接暴露给用户。现在首轮对话会用这一轮的问题重写标题，本测试钉住清洗规则。</p>
 */
class ConversationTitleTest {

    @Test
    @DisplayName("换行与连续空白折叠成一行（标题不能是多行）")
    void collapsesWhitespace() {
        // 注意「帮我看看」属口语前缀，会被一并剥掉；词间保留单个空格
        assertEquals("这个季度的 报销汇总",
                RunService.summarizeQuestion("帮我看看\n这个季度的   报销汇总"));
    }

    @Test
    @DisplayName("口语前缀被剥掉，标题直接是问题本身")
    void stripsPolitePrefix() {
        assertEquals("统计一下四川省有多少个省级非遗项目",
                RunService.summarizeQuestion("麻烦你统计一下四川省有多少个省级非遗项目"));
        assertEquals("请假三天需要谁审批", RunService.summarizeQuestion("你好，请假三天需要谁审批"));
        assertEquals("报销流程是什么", RunService.summarizeQuestion("请帮我报销流程是什么"));
    }

    @Test
    @DisplayName("超长按 30 字截断并补省略号")
    void truncatesTo30() {
        String longText = "请帮我总结一下这份文件里关于预算调整的全部要点以及每条要点对应的责任部门";
        String got = RunService.summarizeQuestion(longText);
        assertTrue(got.endsWith("…"), got);
        assertEquals(RunService.TITLE_MAX + 1, got.codePointCount(0, got.length()),
                "截断后应为 30 字 + 省略号：" + got);
    }

    @Test
    @DisplayName("emoji 不会被切成半个代理对")
    void doesNotSplitSurrogatePair() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 40; i++) {
            sb.append("👍");
        }
        String got = RunService.summarizeQuestion(sb.toString());
        assertTrue(got.endsWith("…"));
        // 若切在代理对中间，会留下孤立的高位/低位代理 —— 存库即成乱码
        for (int i = 0; i < got.length(); i++) {
            char c = got.charAt(i);
            if (Character.isHighSurrogate(c)) {
                assertEquals(true, i + 1 < got.length() && Character.isLowSurrogate(got.charAt(i + 1)),
                        "高位代理必须成对出现");
            }
        }
    }

    @Test
    @DisplayName("空/纯空白/纯前缀都返回 null（调用方据此不改标题）")
    void returnsNullWhenNothingUsable() {
        assertNull(RunService.summarizeQuestion(null));
        assertNull(RunService.summarizeQuestion("   \n\t "));
        assertNull(RunService.summarizeQuestion("帮我"));
    }
}
