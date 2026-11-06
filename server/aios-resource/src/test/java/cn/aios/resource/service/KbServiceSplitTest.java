package cn.aios.resource.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 切分：表格走「列名 + 连续 N 行」，其余走段落（docs/74 P0-1）。
 *
 * <p>回归的是这条链路：{@code KbFileParser.readSheet()} 每个数据行写一个 {@code \n}，
 * 而切分按 {@code \n} 切段、单段 ≤500 字直接成块 ⇒ 500 行的表被切成 503 块、
 * 带列名的只有 1 块，模型看到的是「没有列名的裸行」。</p>
 */
class KbServiceSplitTest {

    private static String tableText(int rows) {
        StringBuilder sb = new StringBuilder("### Sheet1\n")
                .append("| 序号 | 项目名称 | 类别 | 申报地区或单位 | 批次 |\n")
                .append("| --- | --- | --- | --- | --- |\n");
        for (int i = 1; i <= rows; i++) {
            sb.append("| ").append(i).append(" | 项目").append(i)
                    .append(" | 传统技艺 | 成都市 | 第六批 |\n");
        }
        return sb.toString();
    }

    @Test
    @DisplayName("表格：切出的块数远小于行数，且每块带列名")
    void tableIsNotOneRowPerChunk() {
        List<String> chunks = KbService.split(tableText(500), 500, 50, "省级名录.xlsx");
        // 原实现是 503 块（每行一块）；现在按 20 行/块合并
        assertTrue(chunks.size() < 80, "块数应显著下降，实际 " + chunks.size());
        for (String c : chunks) {
            assertTrue(c.startsWith("《省级名录.xlsx》/Sheet1｜列: 序号/项目名称/类别/申报地区或单位/批次｜"),
                    "每块必须带列名: " + c.substring(0, Math.min(50, c.length())));
            assertTrue(c.length() <= 900, "单块 ≤ 分块预算 900: " + c.length());
        }
        assertFalse(chunks.stream().anyMatch(c -> c.trim().equals("### Sheet1")), "sheet 标题不得单独成块");
    }

    @Test
    @DisplayName("PDF 拍平正文：按段落合并，不再「一行一块」")
    void pdfProseMergesIntoParagraphs() {
        // 真实形态：PDF 取出的每一行 = 4 门课（约 45 字），一行一块会把 1800 字切成 38 块，
        // 每块既没有列名也凑不出完整表格 —— 检索命中了也用不上（docs/76）。
        StringBuilder sb = new StringBuilder();
        for (int i = 1; i <= 38; i++) {
            sb.append("课程").append(i).append(" 学基必修 3.0 8").append(i % 10)
                    .append(" 课程").append(i).append("甲 通识必修 2.0 优\n");
        }
        String text = sb.toString();
        List<String> chunks = KbService.split(text, 500, 50, "成绩单.pdf");
        assertTrue(chunks.size() <= 5, "38 行应合并成 ≤5 块，实际 " + chunks.size());
        for (String c : chunks) {
            assertTrue(c.length() <= 500, "单块 ≤ chunkSize: " + c.length());
        }
        // 行不丢：所有行内容都还在（按行累加）
        int lines = 0;
        for (String c : chunks) {
            lines += c.split("\n").length;
        }
        assertEquals(38, lines, "行不能丢");
    }

    @Test
    @DisplayName("表格：行不丢不重")
    void tableRowsArePreserved() {
        List<String> chunks = KbService.split(tableText(37), 500, 50, "x.xlsx");
        // 前缀与第 1 行同行，所以「行数 = 换行分隔后的段数」
        int rows = 0;
        for (String c : chunks) {
            rows += c.split("\n").length;
        }
        assertEquals(37, rows);
    }

    @Test
    @DisplayName("纯文本：行为与改动前一致（按段落成块）")
    void plainTextUnchanged() {
        assertEquals(List.of("第一段", "第二段"),
                KbService.split("第一段\n\n  第二段  \n", 500, 50, "a.txt"));
        assertTrue(KbService.split(null, 500, 50, "a.txt").isEmpty());
        assertTrue(KbService.split("   \n\n  ", 500, 50, "a.txt").isEmpty());
    }

    @Test
    @DisplayName("超长段落仍按 size-overlap 滑窗")
    void longParagraphSlides() {
        String longText = "字".repeat(1200);
        List<String> chunks = KbService.split(longText, 500, 50, "a.txt");
        assertEquals(3, chunks.size(), "1200 字 / 步长 450 → 3 块，实际 " + chunks.size());
        assertEquals(500, chunks.get(0).length());
    }

    @Test
    @DisplayName("文档名未知时前缀退化为《文档》，不抛异常")
    void nullDocNameTolerated() {
        List<String> chunks = KbService.split(tableText(3), 500, 50, null);
        assertFalse(chunks.isEmpty());
        assertTrue(chunks.get(0).startsWith("《文档》/Sheet1｜列: "));
    }
}
