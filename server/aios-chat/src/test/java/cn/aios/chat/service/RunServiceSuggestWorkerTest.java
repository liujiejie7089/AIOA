package cn.aios.chat.service;

import cn.aios.chat.service.RunService.HandoffCandidate;
import cn.aios.chat.service.RunService.WorkerSuggestion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 越界建议 {@link RunService#suggestWorker} 的纯函数单测（不需要 Spring）。
 *
 * <p>回归的真实场景（2026-11-06 截图）：用户对**请假助手**问「策划书里面说了什么」，
 * 它读了《策划书.docx》正文后回：「这属于策划书内容解读，超出我的请假办理职责范围；
 * 请改问文档解读数字员工或项目负责人。」——用户看到的只有一句话，**没有任何可点入口**。</p>
 *
 * <p>为什么不能用 {@code matchHandoff} 兜住这个场景：那是拿**用户原话**比数字人任务名，
 * 而「策划书里面说了什么」里没有任何任务名（Tier A/B 都匹配不上）。越界是模型读完上下文
 * 才承认的，所以只能从**回答正文**里取。</p>
 */
class RunServiceSuggestWorkerTest {

    /** 当前数字人 = 请假助手(1249)；候选里还有文档解读(1301)、会议(1302)。 */
    private static final Long CURRENT = 1249L;

    private static List<HandoffCandidate> candidates() {
        return List.of(
                new HandoffCandidate(1249L, "请假助手", "请假申请", "LEAVE"),
                new HandoffCandidate(1301L, "文档解读数字员工", "文档解读", "DOC_READ"),
                new HandoffCandidate(1302L, "会议助手", "会议预定", "MEETING"));
    }

    /** 截图里的原文，一字不改。 */
    private static final String REAL_ANSWER =
            "我先查一下假种配置和这份「策划书」的位置。知识库里找到了《策划书.docx》，我继续取它的正文。"
                    + "知识库里确实有《策划书.docx》（自贡彩灯数字文旅方向）。我再多取几段正文，确保覆盖完整结构。"
                    + "再补几段核心产品与风险相关内容。这属于策划书内容解读，超出我的请假办理职责范围；"
                    + "请改问文档解读数字员工或项目负责人。";

    @Test
    @DisplayName("截图原文 ⇒ 建议转给「文档解读数字员工」")
    void realScreenshotCase() {
        WorkerSuggestion s = RunService.suggestWorker(REAL_ANSWER, CURRENT, candidates());
        assertEquals(1301L, s.workerId());
        assertEquals("文档解读数字员工", s.workerName());
        assertEquals("文档解读", s.taskName());
    }

    @Test
    @DisplayName("正常回答里提到别的数字人 ⇒ 不建议（没有越界话术）")
    void noSuggestionWithoutOutOfScopePhrase() {
        String normal = "你的年假还剩 5 天。如果你想预订会议室，可以随时告诉我。";
        assertNull(RunService.suggestWorker(normal, CURRENT, candidates()),
                "没说自己干不了，就不能给跳转按钮");
    }

    @Test
    @DisplayName("越界但没点名任何人 ⇒ 不建议（宁可没按钮，也不要送错人）")
    void noSuggestionWhenNoWorkerNamed() {
        String vague = "这个超出我的职责范围，建议改问相关部门。";
        assertNull(RunService.suggestWorker(vague, CURRENT, candidates()));
    }

    @Test
    @DisplayName("永不把当前数字人自己当目标")
    void neverSuggestsSelf() {
        // 正文只提了「请假」（当前人是请假助手），即便有越界话术也不该建议转给自己
        String text = "这超出我的职责范围，请改问请假助手。";
        assertNull(RunService.suggestWorker(text, CURRENT, candidates()));
    }

    @Test
    @DisplayName("点名多个时取名字更长的那个（越具体越可能是它）")
    void prefersLongerName() {
        List<HandoffCandidate> cs = List.of(
                new HandoffCandidate(CURRENT, "请假助手", "请假申请", "LEAVE"),
                new HandoffCandidate(1301L, "文档", "文档解读", "DOC_READ"),
                new HandoffCandidate(1303L, "文档解读数字员工", "文档解读", "DOC_READ2"));
        WorkerSuggestion s = RunService.suggestWorker(
                "超出我的职责范围，请改问文档或文档解读数字员工。", CURRENT, cs);
        assertEquals(1303L, s.workerId());
    }

    @Test
    @DisplayName("点名的人不在候选里 ⇒ 不建议")
    void namedWorkerNotInCandidates() {
        String text = "超出我的职责范围，请改问法务数字员工。";
        assertNull(RunService.suggestWorker(text, CURRENT, candidates()));
    }

    @Test
    @DisplayName("空输入 / 空候选 / 无当前数字人 ⇒ 不建议，不抛异常")
    void guardClauses() {
        assertNull(RunService.suggestWorker(null, CURRENT, candidates()));
        assertNull(RunService.suggestWorker("  ", CURRENT, candidates()));
        assertNull(RunService.suggestWorker(REAL_ANSWER, CURRENT, null));
        assertNull(RunService.suggestWorker(REAL_ANSWER, CURRENT, List.of()));
        assertNull(RunService.suggestWorker(REAL_ANSWER, null, candidates()),
                "会话没绑数字人时无所谓「转交」，不打扰用户");
    }

    @Test
    @DisplayName("「不属于我的职责」「我不负责这件事」等同义说法也能认出来")
    void otherOutOfScopePhrasings() {
        for (String text : List.of(
                "这不在我的职责范围内，请联系文档解读数字员工。",
                "这个我不负责这类事，请咨询文档解读数字员工。",
                "职责范围之外的问题，建议找文档解读数字员工。")) {
            WorkerSuggestion s = RunService.suggestWorker(text, CURRENT, candidates());
            assertEquals(1301L, s.workerId(), text);
        }
    }

    /*
     * 以下三例覆盖「越界但没有可用目标」这条分支 —— 它对应前端的**挑人卡**。
     * 这是截图场景在真实数据下的样子：库里没有「文档解读数字员工」这个名字
     * （2026-11-06 核对 agent_worker，全租户只有「文档管理数字人/文档上传」），
     * 名字是模型自己编的。此时 suggestWorker 为 null，但正文确实越界 ⇒
     * isOutOfScope 必须为 true，前端才有一张「去挑一位」的卡，而不是只剩一句办不了的话。
     */

    @Test
    @DisplayName("isOutOfScope：越界话术为真，普通回答为假")
    void outOfScopeDetector() {
        assertTrue(RunService.isOutOfScope(REAL_ANSWER));
        assertTrue(RunService.isOutOfScope("这超出我的职责范围，请改问别的同事。"));
        assertFalse(RunService.isOutOfScope("你的年假还剩 5 天，需要我帮你提交申请吗？"));
        assertFalse(RunService.isOutOfScope(null));
        assertFalse(RunService.isOutOfScope("   "));
    }

    @Test
    @DisplayName("越界 + 点名了库里不存在的人 ⇒ 无具体目标（前端走挑人卡）")
    void outOfScopeButTargetNotInDb() {
        /* 候选按**真实库**造：租户 56 只有「文档管理数字人 / 文档上传」，
           根本没有「文档解读」—— 截图里那个名字是模型自己编的。 */
        List<HandoffCandidate> realDb = List.of(
                new HandoffCandidate(CURRENT, "请假助手", "请假申请", "LEAVE"),
                new HandoffCandidate(1314L, "文档管理数字人", "文档上传", "doc_upload"));
        String text = "这属于策划书内容解读，超出我的请假办理职责范围；请改问文档解读数字员工。";
        assertTrue(RunService.isOutOfScope(text), "越界判定要说 yes —— 否则前端连挑人卡都不给");
        assertNull(RunService.suggestWorker(text, CURRENT, realDb), "但库里没有这个人 ⇒ 不指人");
    }

    @Test
    @DisplayName("越界 + 一个都没点名 ⇒ 无具体目标（前端走挑人卡）")
    void outOfScopeButNobodyNamed() {
        String text = "这个超出我的职责范围，建议改问相关部门。";
        assertTrue(RunService.isOutOfScope(text));
        assertNull(RunService.suggestWorker(text, CURRENT, candidates()));
    }
}
