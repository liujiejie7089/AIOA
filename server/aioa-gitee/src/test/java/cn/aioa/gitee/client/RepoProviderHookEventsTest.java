package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「Webhook 事件名」必须按托管方的词表给出 —— 这张列表直接渲染在项目详情页上。
 *
 * <p><b>守住的是什么</b>：真机实测（2026-09-18）发现项目详情页对 Gitea 项目显示
 * {@code push,merge_requests,issues,notes}，而仓库上真实订阅的是
 * {@code push,pull_request,issues,issue_comment,…}。根因是落库时写死了 Gitee 词表。
 * 这类缺陷「编译能过、启动能起、桩环境永远绿」，只有在真机上比对界面与实际订阅才看得见，
 * 所以这里用两个 provider 的**互斥**断言把它钉死：任何一家的列表里都不准出现另一家的词。</p>
 */
class RepoProviderHookEventsTest {

    private static final List<String> GITEE_ONLY = List.of("merge_requests", "notes");
    private static final List<String> GITEA_ONLY = List.of("pull_request", "issue_comment");

    private static RepoProviderClient gitee() {
        return new GiteeClient(new GiteeProperties(), new ObjectMapper());
    }

    private static RepoProviderClient gitea() {
        return new GiteaProviderClient(new GiteaProperties(), new ObjectMapper());
    }

    @Test
    @DisplayName("Gitee 落 Gitee 词表：merge_requests / notes")
    void giteeUsesGiteeVocabulary() {
        assertEquals(List.of("push", "merge_requests", "issues", "notes"),
                gitee().hookEventNames(true, true, true, true));
    }

    @Test
    @DisplayName("Gitea 落 Gitea 词表：pull_request / issue_comment，且不得出现 Gitee 词")
    void giteaUsesGiteaVocabulary() {
        List<String> all = gitea().hookEventNames(true, true, true, true);
        assertTrue(all.containsAll(List.of("push", "pull_request", "issues", "issue_comment")),
                "四类核心事件都应在列表里：" + all);
        for (String bad : GITEE_ONLY) {
            assertFalse(all.contains(bad), "Gitea 上不存在事件 " + bad + "（Gitee 词表），出现即误导：" + all);
        }
    }

    @Test
    @DisplayName("两家的词表互斥：谁都不准出现对方的专有事件名")
    void vocabulariesAreMutuallyExclusive() {
        List<String> giteeAll = gitee().hookEventNames(true, true, true, true);
        List<String> giteaAll = gitea().hookEventNames(true, true, true, true);

        for (String ev : GITEA_ONLY) {
            assertFalse(giteeAll.contains(ev), "Gitee 列表混入 Gitea 事件名 " + ev + "：" + giteeAll);
        }
        for (String ev : GITEE_ONLY) {
            assertFalse(giteaAll.contains(ev), "Gitea 列表混入 Gitee 事件名 " + ev + "：" + giteaAll);
        }
        assertFalse(giteeAll.equals(giteaAll),
                "两家的词表不可能相同，相同说明有一侧写死了另一家的词：" + giteeAll);
    }

    @Test
    @DisplayName("展示词表必须与建钩子的开关同源：全关则为空，不凭空多出事件")
    void allOffYieldsEmpty() {
        assertTrue(gitee().hookEventNames(false, false, false, false).isEmpty());
        assertTrue(gitea().hookEventNames(false, false, false, false).isEmpty());
        assertEquals(List.of("push"), gitea().hookEventNames(true, false, false, false));
    }
}
