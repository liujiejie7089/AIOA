package cn.aios.gitee.support;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * L1：仓库名双连字符修复。中文段坍塌后产生的相邻 {@code --} 必须被折叠为单个 {@code -}，
 * 且正常（纯 ASCII）名字逐字不变。
 */
class GiteeNamingDoubleHyphenTest {

    @Test
    @DisplayName("中文段坍塌产生的 sim--1002 被修正为 sim-1002（无双连字符）")
    void chineseCollapseNoDoubleHyphen() {
        // 复现原缺陷输入：sim-项目-1002 => 旧代码产出 dept11-sim--1002-xxxx
        String name = GiteeNaming.repoPath("sim-项目-1002", 50, "dept11-");
        assertFalse(name.contains("--"), "不允许出现双连字符，实际=" + name);
        assertTrue(name.startsWith("dept11-sim-1002"), "前缀与主体应保持单连字符，实际=" + name);
    }

    @Test
    @DisplayName("其它中文段组合也不产生双连字符")
    void mixedChineseNoDoubleHyphen() {
        String name = GiteeNaming.repoPath("方案A-测试-部门B", 60, "dept3-");
        assertFalse(name.contains("--"), "不允许出现双连字符，实际=" + name);
    }

    @Test
    @DisplayName("正常 ASCII 名字逐字不变")
    void normalNameUnchanged() {
        assertEquals("my-project-2024", GiteeNaming.repoPath("my-project-2024", 50, ""));
        assertEquals("dept1-hello-world", GiteeNaming.repoPath("hello-world", 50, "dept1-"));
    }

    @Test
    @DisplayName("纯中文名退化为确定性短哈希（无双连字符）")
    void pureChineseFallsBackToHash() {
        String name = GiteeNaming.repoPath("政务数据中台", 50, "dept5-");
        assertFalse(name.contains("--"), "不允许出现双连字符，实际=" + name);
        assertTrue(name.startsWith("dept5-proj-"), "纯中文应退化为 proj-<hash>，实际=" + name);
    }
}
