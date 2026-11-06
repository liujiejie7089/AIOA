package cn.aios.resource.support;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Markdown 表格解析（docs/74 P0-1 / P0-2）。
 *
 * <p>测的是三件事：①表格能被还原成「列名 + 行」；②转义的 {@code \|} 不破坏列对齐；
 * ③切片每块都带列名、表头不单独成块；④统计摘要能给出总数与低基数列的分组计数。</p>
 */
class MarkdownTableTest {

    private static String sheet(String... rows) {
        return "### Sheet1\n| 序号 | 项目名称 | 类别 | 申报地区或单位 | 批次 |\n"
                + "| --- | --- | --- | --- | --- |\n"
                + String.join("\n", rows) + "\n";
    }

    @Test
    @DisplayName("还原列名与数据行")
    void parseColumnsAndRows() {
        String text = sheet("| 1 | 川剧 | 传统戏剧 | 成都市 | 第一批 |",
                "| 2 | 蜀绣 | 传统技艺 | 成都市 | 第一批 |");
        List<MarkdownTable.Table> tables = MarkdownTable.parse(text, "名录.xlsx");
        assertEquals(1, tables.size());
        MarkdownTable.Table t = tables.get(0);
        assertEquals("Sheet1", t.name());
        assertEquals(List.of("序号", "项目名称", "类别", "申报地区或单位", "批次"), t.columns());
        assertEquals(2, t.rows().size());
        assertEquals(1, t.indexOf("项目名称"));
        assertEquals(-1, t.indexOf("不存在的列"));
    }

    @Test
    @DisplayName("单元格里的 \\| 不被当成分隔符")
    void escapedPipeDoesNotSplit() {
        String text = sheet("| 1 | 川剧\\|高腔 | 传统戏剧 | 成都市 | 第一批 |");
        MarkdownTable.Table t = MarkdownTable.parse(text, "x").get(0);
        assertEquals(5, t.columns().size());
        assertEquals("川剧|高腔", t.rows().get(0).get(1));
    }

    @Test
    @DisplayName("缺少分隔行的竖线内容不当表格")
    void pipeWithoutSeparatorIsNotTable() {
        String text = "### 说明\n| 这不是表 | 只是竖线 |\n正文继续\n";
        assertTrue(MarkdownTable.parse(text, "x").isEmpty());
    }

    @Test
    @DisplayName("切片：每块都带列名，表头不单独成块")
    void chunksCarryHeaderAndDropTitle() {
        StringBuilder body = new StringBuilder();
        for (int i = 1; i <= 35; i++) {
            body.append("| ").append(i).append(" | 项目").append(i).append(" | 传统技艺 | 成都市 | 第六批 |\n");
        }
        String text = "### Sheet1\n| 序号 | 项目名称 | 类别 | 申报地区或单位 | 批次 |\n"
                + "| --- | --- | --- | --- | --- |\n" + body;
        MarkdownTable.Table t = MarkdownTable.parse(text, "2026.2省级非遗项目名录.xlsx").get(0);
        List<String> chunks = MarkdownTable.chunks("2026.2省级非遗项目名录.xlsx", t);
        assertFalse(chunks.isEmpty());
        for (String c : chunks) {
            assertTrue(c.startsWith("《2026.2省级非遗项目名录.xlsx》/Sheet1｜列: 序号/项目名称/类别/申报地区或单位/批次｜"),
                    "每块必须带表名与列名: " + c.substring(0, Math.min(60, c.length())));
            assertTrue(c.length() <= 900, "块长必须 ≤ 900（分块预算）: " + c.length());
        }
        // 35 行 > 30（小表阈值）⇒ 走 20 行/块 → 2 块；行不丢
        assertEquals(2, chunks.size(), "35 行按 20 行/块应切 2 块");
        // 首行与最后一行都可能带列名前缀（前缀与第 1 行同一行），故按行数计
        int rowTotal = 0;
        for (String c : chunks) {
            rowTotal += c.split("\n").length;
        }
        assertEquals(35, rowTotal, "行不能丢，也不能重复");
        assertFalse(chunks.stream().anyMatch(c -> c.equals("### Sheet1")), "sheet 标题不得单独成块");
    }

    @Test
    @DisplayName("小表整表一块：键值表的标签与数值必须同块（否则命中栏名时旁边没有数）")
    void smallKeyValueTableStaysInOneChunk() {
        StringBuilder body = new StringBuilder();
        String[][] kv = {{"历年平均成绩", "80.26"}, {"历年平均学分绩点", "2.69"},
                {"毕业应取得总学分", "150.0"}, {"已获得总学分", "134.0"},
                {"通识必修课", "24.0"}, {"通识选修课", "5.0"}, {"学基必修课", "33.0"},
                {"专核必修课", "23.0"}, {"专业选修课", "11.0"}, {"集实必修课", "3.0"},
                {"素实必修课", "8.0"}, {"复培选修课", "12.0"}, {"专基必修课", "15.0"}};
        for (String[] row : kv) {
            body.append("| ").append(row[0]).append(" | ").append(row[1]).append(" |\n");
        }
        String text = "### 成绩汇总\n| 项目 | 数值 |\n| --- | --- |\n" + body;
        MarkdownTable.Table t = MarkdownTable.parse(text, "成绩单.pdf").get(0);
        List<String> chunks = MarkdownTable.chunks("成绩单.pdf", t);
        assertEquals(1, chunks.size(), "13 行小表应整表一块，实际切成 " + chunks.size() + " 块");
        assertTrue(chunks.get(0).contains("| 历年平均学分绩点 | 2.69 |"),
                "绩点与数值必须在同一块里");
    }

    @Test
    @DisplayName("统计摘要：总数 + 低基数列分组，跳过每行都不同的列")
    void statsSummarizeTotalAndLowCardinality() {
        String text = sheet("| 1 | 川剧 | 传统戏剧 | 成都市 | 第一批 |",
                "| 2 | 蜀绣 | 传统技艺 | 成都市 | 第一批 |",
                "| 3 | 绵竹年画 | 传统美术 | 德阳市 | 第二批 |");
        MarkdownTable.Table t = MarkdownTable.parse(text, "名录.xlsx").get(0);
        String stats = MarkdownTable.statsText("名录.xlsx", t);
        assertTrue(stats.startsWith(MarkdownTable.STATS_MARK), "必须以固定前缀开头，检索层靠它识别");
        assertTrue(stats.contains("数据行合计：3 条"), stats);
        assertTrue(stats.contains("成都市 2 条"), stats);
        // 序号列 3 个取值（= 行数）虽是低基数，但一次表里它没有分组意义；此处仅要求
        // 项目名称这类高基数列被跳过（3 行时也是 3 个取值，故用更大表验证）
        assertTrue(stats.contains("按「批次」"), stats);
    }

    @Test
    @DisplayName("统计摘要：高基数列（每行都不同）被跳过")
    void statsSkipUniqueColumns() {
        StringBuilder body = new StringBuilder();
        for (int i = 1; i <= 40; i++) {
            body.append("| ").append(i).append(" | 项目").append(i).append("号 | 传统技艺 | 成都市 | 第六批 |\n");
        }
        String text = "### Sheet1\n| 序号 | 项目名称 | 类别 | 申报地区或单位 | 批次 |\n"
                + "| --- | --- | --- | --- | --- |\n" + body;
        MarkdownTable.Table t = MarkdownTable.parse(text, "名录.xlsx").get(0);
        String stats = MarkdownTable.statsText("名录.xlsx", t);
        assertTrue(stats.contains("数据行合计：40 条"), stats);
        assertFalse(stats.contains("按「项目名称」"), "每行都不同的列不该分组: " + stats);
        assertTrue(stats.contains("按「批次」"), stats);
    }

    @Test
    @DisplayName("空表（只有表头）也要保留一块，别把「有表无数据」吞掉")
    void emptyTableKeepsOneChunk() {
        String text = "### Sheet1\n| 序号 | 项目名称 |\n| --- | --- |\n";
        MarkdownTable.Table t = MarkdownTable.parse(text, "x.xlsx").get(0);
        assertTrue(t.rows().isEmpty());
        assertEquals(1, MarkdownTable.chunks("x.xlsx", t).size());
        assertEquals("", MarkdownTable.statsText("x.xlsx", t), "无数据不生成统计摘要");
    }
}
