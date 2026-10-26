package cn.aios.resource.service;

import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayOutputStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Excel 解析输出 Markdown 表格（docs/60 P2-10，2026-10-26）。
 *
 * <p>旧实现「行内空格拼接」丢列对齐：多列表读表时列错位，模型无法按行按列理解
 * （「报名表第三行第二列」这类问题直接答不出）。此哨兵钉死 Markdown 表格三要素：
 * Sheet 标题、表头 + 对齐行、列对齐（含行内空洞保留）。</p>
 *
 * <p>用 POI 现写一个小 xlsx（内存造数，不落盘），与 {@link KbFileParser#parse} 的
 * 生产路径（按后缀分派 → parseXlsx）完全同源。</p>
 */
class KbFileParserSheetTest {

    private static byte[] buildXlsx() throws Exception {
        try (XSSFWorkbook wb = new XSSFWorkbook()) {
            org.apache.poi.ss.usermodel.Sheet sh = wb.createSheet("报名表");
            org.apache.poi.ss.usermodel.Row r0 = sh.createRow(0);
            r0.createCell(0).setCellValue("姓名");
            r0.createCell(1).setCellValue("学校");
            r0.createCell(2).setCellValue("手机号");
            org.apache.poi.ss.usermodel.Row r1 = sh.createRow(1);
            r1.createCell(0).setCellValue("张三");
            r1.createCell(1).setCellValue("重庆大学");
            org.apache.poi.ss.usermodel.Row r2 = sh.createRow(2);
            r2.createCell(0).setCellValue("李四");
            r2.createCell(2).setCellValue("13800000000"); // 第二列留空：行内空洞须保留对齐
            org.apache.poi.ss.usermodel.Row r3 = sh.createRow(3); // 整行空白：应被跳过
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            wb.write(bos);
            return bos.toByteArray();
        }
    }

    @Test
    @DisplayName("★parseXlsx：输出 Markdown 表格（Sheet 标题 + 表头对齐行 + 列对齐）")
    void parseXlsxOutputsMarkdownTable() throws Exception {
        String text = new KbFileParser().parse("报名表.xlsx", buildXlsx());

        // Sheet 标题
        assertTrue(text.contains("### 报名表"), text);
        // 表头行 + 对齐行（三列）
        assertTrue(text.contains("| 姓名 | 学校 | 手机号 |"), text);
        assertTrue(text.contains("| --- | --- | --- |"), text);
        // 数据行保持列对齐；行内空洞以空列保留
        assertTrue(text.contains("| 张三 | 重庆大学 |  |"), text);
        assertTrue(text.contains("| 李四 |  | 13800000000 |"), text);
        // 整行空白不产生表格行
        assertFalse(text.contains("|   |   |   |"), text);
    }

    @Test
    @DisplayName("★parseXlsx：单元格内的竖线被转义，不破坏表格结构")
    void parseXlsxEscapesPipes() throws Exception {
        try (XSSFWorkbook wb = new XSSFWorkbook()) {
            org.apache.poi.ss.usermodel.Sheet sh = wb.createSheet("S");
            org.apache.poi.ss.usermodel.Row r0 = sh.createRow(0);
            r0.createCell(0).setCellValue("是|否");
            r0.createCell(1).setCellValue("第二列");
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            wb.write(bos);
            String text = new KbFileParser().parse("t.xlsx", bos.toByteArray());
            assertTrue(text.contains("| 是\\|否 | 第二列 |"), text);
        }
    }

    @Test
    @DisplayName("★parseXlsx：空 Sheet（无内容）不产生标题行")
    void parseXlsxSkipsEmptySheet() throws Exception {
        try (XSSFWorkbook wb = new XSSFWorkbook()) {
            wb.createSheet("空表"); // 只有 sheet，没有任何单元格
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            wb.write(bos);
            String text = new KbFileParser().parse("t.xlsx", bos.toByteArray());
            assertEquals("", text.strip());
        }
    }
}
