package cn.aios.chat.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 会话内跨数字人转交判据 {@link RunService#matchHandoff} 的纯函数单测（不需要 Spring）。
 *
 * <p>判据只在后端这一处（matchHandoff 是「唯一判定点」），故只测它；
 * 不测 H5 / agent 里的任何二次判定（那会破坏「单一判定点」铁律）。</p>
 *
 * <p>覆盖：H1 单一他人任务名命中 → 返回该 worker；H2 当前 worker 自己也命中 → null（最关键）；
 * H3 两个不同 worker 同时命中 → null（歧义）；H4 只命中 taskCode → 返回；
 * H5 文本空/null → null；H6 taskName 只有 1 个字符不命中（防「报」这类单字误判）；
 * H7 同一 worker 两条能力都命中仍只算一个目标（不误判歧义）。</p>
 */
class RunServiceHandoffTest {

    private static RunService.HandoffCandidate c(Long workerId, String name,
                                                String taskName, String taskCode) {
        return new RunService.HandoffCandidate(workerId, name, taskName, taskCode);
    }

    @Test
    @DisplayName("H1 单一他人任务名命中 → 返回该 worker")
    void singleOtherWorkerTaskNameHit() {
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "报销助手", "费用报销", "expense_claim"),
                c(3L, "会议助手", "会议预定", "meeting_book"));
        // 文本须真正包含 taskName「费用报销」：用「我要办理费用报销」而不是「我要报销差旅费」
        // —— 后者不含「费用报销」子串，会误判不命中。
        RunService.HandoffDecision d = RunService.matchHandoff("我要办理费用报销", 1L, candidates);
        assertNotNull(d, "单一他人任务名命中应返回 decision");
        assertEquals(2L, d.toWorkerId());
        assertEquals("报销助手", d.toWorkerName());
        assertEquals("费用报销", d.taskName());
        assertEquals(1L, d.fromWorkerId());
        assertEquals("我要办理费用报销", d.question());
    }

    @Test
    @DisplayName("H2 当前 worker 自己也命中 → null（最关键）")
    void currentWorkerAlsoHitsReturnsNull() {
        // 当前数字人=1（请假），它自己凭 taskName=请假 命中，同时还有一个报销候选
        List<RunService.HandoffCandidate> candidates = List.of(
                c(1L, "请假助手", "请假", "leave_request"),
                c(2L, "报销助手", "报销", "expense_claim"));
        RunService.HandoffDecision d = RunService.matchHandoff("我要请假", 1L, candidates);
        assertNull(d, "用户在当前数字人职责内说话，绝不转交");
    }

    @Test
    @DisplayName("H3 两个不同 worker 同时命中 → null（歧义）")
    void twoWorkersBothHitReturnsNull() {
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "报销助手", "报销", "expense_claim"),
                c(3L, "会议助手", "会议", "meeting_book"));
        // 文本同时点名「报销」与「会议」，两个不同数字人都命中 → 歧义，不转交
        RunService.HandoffDecision d = RunService.matchHandoff("我要报销并预定会议", 1L, candidates);
        assertNull(d, "多个不同数字人同时命中应判为歧义、不转交");
    }

    @Test
    @DisplayName("H4 只命中 taskCode → 返回该 worker")
    void onlyTaskCodeHitReturnsWorker() {
        // 候选只有 taskCode（taskName 为空），文本含 taskCode 即命中
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "报销助手", null, "expense_claim"));
        RunService.HandoffDecision d = RunService.matchHandoff("expense_claim 怎么填", 1L, candidates);
        assertNotNull(d, "只命中 taskCode 应返回 decision");
        assertEquals(2L, d.toWorkerId());
        // 只命中 taskCode 时 taskName 为 null（来自候选的 taskName），命中来源是 taskCode 而非 taskName
        assertNull(d.taskName());
        // question 必须是「同一条已落库的用户原话」整句（需求②：不重新追问），不是只截取命中片段
        assertEquals("expense_claim 怎么填", d.question());
    }

    @Test
    @DisplayName("H5 文本为空 / null → null")
    void blankOrNullTextReturnsNull() {
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "报销助手", "报销", "expense_claim"));
        assertNull(RunService.matchHandoff(null, 1L, candidates), "null 文本不转交");
        assertNull(RunService.matchHandoff("   ", 1L, candidates), "空白文本不转交");
        assertNull(RunService.matchHandoff("我要报销", 1L, null), "空候选不转交");
        assertNull(RunService.matchHandoff("我要报销", 1L, List.of()), "空候选不转交");
    }

    @Test
    @DisplayName("H6 taskName 只有 1 个字符不命中（防「报」这类单字误判）")
    void singleCharTaskNameDoesNotHit() {
        // taskName=报（1 字）本应被忽略；taskCode 为空 ⇒ 整体不应命中
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "报销助手", "报", null));
        RunService.HandoffDecision d = RunService.matchHandoff("我要报销差旅费", 1L, candidates);
        assertNull(d, "单字任务名不得误判命中");
    }

    @Test
    @DisplayName("H7 同一 worker 两条能力都命中仍只算一个目标（不误判歧义）")
    void sameWorkerTwoCapabilitiesCountsAsOne() {
        // 同一 worker=2 有两条能力行（差旅报销 / 报销），文本都命中，按 workerId 分组只算一个目标
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "报销助手", "报销", "expense_claim"),
                c(2L, "报销助手", "差旅", "travel_claim"));
        RunService.HandoffDecision d = RunService.matchHandoff("我要报销差旅费", 1L, candidates);
        assertEquals(2L, d.toWorkerId(), "同一 worker 多能力命中不应被当成歧义");
        assertEquals(1, candidates.stream().map(RunService.HandoffCandidate::workerId).distinct().count());
    }

    // ============================ Tier B：口语 × 书面任务名的核心词重叠 ============================

    @Test
    @DisplayName("H8 ★口语「我要报销差旅费」× 任务名「费用报销申请」→ 转交（Tier B 核心词重叠）")
    void colloquialPhraseHandsOffViaCoreOverlap() {
        // 这是用户原话场景：库里任务名是书面语「费用报销申请」，整词永远匹配不上。
        // 剥掉通用词「申请」得核心词「费用报销」，与用户原话的最长公共子串 =「报销」⇒ 命中。
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "费用报销数字人", "费用报销申请", "expense_form"));
        RunService.HandoffDecision d = RunService.matchHandoff("我要报销差旅费", 1L, candidates);
        assertNotNull(d, "口语说法必须能命中（否则用户举的例子根本不触发转交）");
        assertEquals(2L, d.toWorkerId());
        assertEquals("我要报销差旅费", d.question(), "承接的必须是原话整句");
    }

    @Test
    @DisplayName("H9 Tier B 两个数字人同样像（分数并列）→ 放弃转交")
    void tierBTieGivesUp() {
        // 两位的任务名分别含「报销」/「报销」，与文本重叠长度相同 ⇒ 无法判断像谁，宁可不换
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "费用报销数字人", "费用报销申请", "expense_form"),
                c(3L, "差旅报销数字人", "差旅报销申请", "travel_form"));
        assertNull(RunService.matchHandoff("我要报销差旅费", 1L, candidates),
                "并列最高分时不得随意挑一个");
    }

    @Test
    @DisplayName("H10 Tier B 只重叠到通用词（如「申请」）→ 不转交")
    void tierBGenericWordOnlyDoesNotHit() {
        // 剥完通用词后核心词不含「申请」，用户只说「帮我办个申请」时不应跳到任何数字人
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "费用报销数字人", "费用报销申请", "expense_form"));
        assertNull(RunService.matchHandoff("帮我办个申请", 1L, candidates),
                "通用词重叠不得作为转交依据");
    }

    @Test
    @DisplayName("H11 ★当前数字人的核心词也重叠 → 不转交（不抢自己的活）")
    void tierBCurrentWorkerOverlapBlocksHandoff() {
        // 当前=1 的任务是「费用预审申请」，核心词「费用预审」与「费用」重叠；
        // 若不加此闸，用户在本数字人职责内提「费用」就会被甩给别的数字人。
        List<RunService.HandoffCandidate> candidates = List.of(
                c(1L, "预审数字人", "费用预审申请", "fee_precheck"),
                c(2L, "费用报销数字人", "费用报销申请", "expense_form"));
        assertNull(RunService.matchHandoff("我要咨询费用相关规则", 1L, candidates),
                "当前数字人也重叠时必须留在原地");
    }

    @Test
    @DisplayName("H12 coreTaskName / coreOverlap 的纯函数口径（剥通用词 + 取最长公共子串）")
    void coreNameAndOverlapHelpers() {
        assertEquals("费用报销", RunService.coreTaskName("费用报销申请"));
        assertEquals("移动签到", RunService.coreTaskName("移动签到"));
        // 只有通用词可剥时，剥完不足 2 字 ⇒ 返回原串，不返回空
        assertEquals("申请", RunService.coreTaskName("申请"));
        assertEquals("报销", RunService.coreOverlap("我要报销差旅费", "费用报销申请"));
        assertEquals("", RunService.coreOverlap("你好", "费用报销申请"), "无重叠应返回空串");
        assertEquals("", RunService.coreOverlap("帮我办个申请", "费用报销申请"), "通用词不算重叠");
    }

    @Test
    @DisplayName("H13 ★会话没绑数字人（专家/默认 AI 会话）→ 一律不转交")
    void noCurrentWorkerNeverHandsOff() {
        // 语义闸：转交是「从 A 换到 B」。专家会话没有 A，命中任何数字人都不是转交，
        // 而是把专家会话劫持成某个数字人（会突然弹出别人的业务表单）。
        List<RunService.HandoffCandidate> candidates = List.of(
                c(2L, "费用报销数字人", "费用报销申请", "expense_form"));
        assertNull(RunService.matchHandoff("我要报销差旅费", null, candidates),
                "无当前数字人时不得转交（专家会话必须留在专家自身）");
    }

    @Test
    @DisplayName("H14 ★只差通用尾缀的两个任务不得互转（公文起草 ↔ 合同起草）")
    void sameSuffixTasksNeverHandOff() {
        // 实测事故（2026-10-18）：resolveHandoff 曾把当前 worker 从候选里排除 ⇒ 闸 #1 失效，
        // 「帮我办理公文起草」被 Tier B 判成「像合同起草」（重叠「起草」），43 个数字人集体互转，
        // 表单路由普查 43 PASS → 27 PASS。候选**必须**包含当前 worker，闸 #1 才有对象可判。
        List<RunService.HandoffCandidate> candidates = List.of(
                c(1249L, "公文助手数字人", "公文起草", "doc_draft"),
                c(1216L, "合同管理数字人", "合同起草", "contract_draft"));
        assertNull(RunService.matchHandoff("帮我办理公文起草", 1249L, candidates),
                "点的是自己那张表，绝不能转到名字相近的邻居");
        assertNull(RunService.matchHandoff("帮我办理合同起草", 1216L, candidates),
                "反向同样不得转（这是“互转”的另一半）");
    }

    @Test
    @DisplayName("H15 两字通用尾缀不算业务重合（起草 / 配置）")
    void genericSuffixIsNotOverlap() {
        assertEquals("", RunService.coreOverlap("帮我办理公文起草", "合同起草"),
                "「起草」是通用动作词，不构成业务重合");
        assertEquals("", RunService.coreOverlap("帮我办理看板配置", "门户布局配置"),
                "「配置」是通用动作词，不构成业务重合");
        assertEquals("看板", RunService.coreTaskName("看板配置"));
        assertEquals("公文", RunService.coreTaskName("公文起草"));
    }
}
