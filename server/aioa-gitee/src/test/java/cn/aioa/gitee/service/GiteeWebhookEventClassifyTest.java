package cn.aioa.gitee.service;

import cn.aioa.gitee.entity.GiteeEvent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * Webhook 事件头 → 平台事件类型 的归一化测试。
 *
 * <p><b>为什么这个纯函数值得单独测</b>：它是「外部事件进平台」的第一道分类，
 * 判错不会报错，只会<b>静默把数据归错类</b> —— 评论被当成任务、PR 事件整类丢失，
 * 而链路依旧 200。此前本模块没有任何 Java 测试，这类错误只能靠跑整套 Python E2E
 * 才可能发现（而且前提是 E2E 恰好覆盖了那条事件名）。</p>
 *
 * <p><b>覆盖两家托管方</b>：同一类事件在两家的名字风格不同（Gitee 用
 * {@code "Merge Request Hook"}，Gitea 用 {@code pull_request}），且存在子串包含关系
 * （{@code issue_comment} 含 {@code issue}）。下面按「平台枚举」而不是「某一家」组织用例，
 * 保证换实现时这张表仍然有效。</p>
 */
class GiteeWebhookEventClassifyTest {

    @ParameterizedTest(name = "[{index}] \"{0}\" -> {1}")
    @DisplayName("事件头归一化：Gitee 与 Gitea 两种命名风格都能正确归类")
    @CsvSource({
            // ---------- Gitee（X-Gitee-Event）：回归用例，修复前后都必须一致 ----------
            "'Push Hook',          PUSH",
            "'Tag Push Hook',      PUSH",
            "'Merge Request Hook', MERGE_REQUEST",
            "'Issue Hook',         ISSUE",
            "'Note Hook',          NOTE",
            "'Branch Hook',        OTHER",

            // ---------- Gitea（X-Gitea-Event）：本次修复的靶子 ----------
            // 下划线风格：用 "pull request"（空格）去做 contains 会失手，PR 事件曾整类丢成 OTHER
            "push,                         PUSH",
            "pull_request,                 MERGE_REQUEST",
            "pull_request_review,          MERGE_REQUEST",
            "issues,                       ISSUE",
            "issue_label,                  ISSUE",
            "issue_assign,                 ISSUE",
            // 评论类名字里含 "issue" / "pull request"，若 issue 分支排在前面会被抢走
            "issue_comment,                NOTE",
            "pull_request_comment,         NOTE",
            "pull_request_review_comment,  NOTE",

            // ---------- 与仓库无关的事件：不应被硬塞进任何一类 ----------
            "create,     OTHER",
            "delete,     OTHER",
            "repository, OTHER",
            "release,    OTHER",

            // ---------- 边界：空串 ----------
            "'', OTHER"
    })
    void classifyByEventHeader(String header, String expected) {
        assertEquals(expected, GiteeWebhookService.classify(header),
                "事件头 \"" + header + "\" 应归类为 " + expected);
    }

    @Test
    @DisplayName("null 事件头不抛异常，归为 OTHER")
    void nullHeaderIsOther() {
        assertEquals(GiteeEvent.TYPE_OTHER, GiteeWebhookService.classify(null));
    }

    @Test
    @DisplayName("回归：Gitea 的 issue_comment 必须是 NOTE，不能被 issue 分支抢走")
    void giteaIssueCommentIsNoteNotIssue() {
        assertEquals(GiteeEvent.TYPE_NOTE, GiteeWebhookService.classify("issue_comment"));
        assertEquals(GiteeEvent.TYPE_NOTE, GiteeWebhookService.classify("Issue Comment"));
    }

    @Test
    @DisplayName("回归：Gitea 的下划线式 pull_request 必须被认成合并请求")
    void giteaUnderscoredPullRequestIsMergeRequest() {
        assertEquals(GiteeEvent.TYPE_MERGE_REQUEST, GiteeWebhookService.classify("pull_request"));
        // 空格写法同样要认（Gitee 侧旧数据 / 手工触发）
        assertEquals(GiteeEvent.TYPE_MERGE_REQUEST, GiteeWebhookService.classify("Pull Request"));
    }

    @ParameterizedTest(name = "[{index}] \"{0}\" -> \"{1}\"")
    @DisplayName("归一化：小写、下划线/连字符转空格、压缩空白、去尾部 hook")
    @CsvSource({
            "'Push Hook',            'push'",
            "'Tag Push Hook',        'tag push'",
            "'  Merge  Request Hook  ', 'merge request'",
            "'ISSUE_COMMENT',        'issue comment'",
            "'pull-request',         'pull request'",
            "'hook',                 'hook'",
            "'',                     ''"
    })
    void normalizeEventHeader(String raw, String expected) {
        assertEquals(expected, GiteeWebhookService.normalizeEvent(raw));
    }

    @Test
    @DisplayName("归一化：null 得到空串（不再往下做 contains 判断）")
    void normalizeNullIsEmpty() {
        assertEquals("", GiteeWebhookService.normalizeEvent(null));
    }
}
