package cn.aios.resource.service;

import cn.aios.common.exception.BizException;
import lombok.extern.slf4j.Slf4j;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.poi.hssf.usermodel.HSSFWorkbook;
import org.apache.poi.hwpf.HWPFDocument;
import org.apache.poi.hwpf.extractor.WordExtractor;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.apache.poi.xwpf.usermodel.XWPFTableCell;
import org.apache.poi.xwpf.usermodel.XWPFTableRow;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * 知识库文件解析（FR-F1）：把上传的 PDF / Word / Excel / 文本抽取为纯文本，供切片入库。
 * 支持：pdf、docx、doc、xlsx、xls、txt、md、csv、json、log。
 * 解析按文件后缀分派，不支持的类型抛 400 并提示允许的格式。
 */
@Slf4j
@Service
public class KbFileParser {

    /** 单文件上限 50MB（FR-F1）。 */
    public static final long MAX_BYTES = 50L * 1024 * 1024;

    public static final String SUPPORTED = "pdf、docx、doc、xlsx、xls、txt、md、csv";

    /** 抽取文件正文；返回纯文本（段落以换行分隔）。 */
    public String parse(String fileName, byte[] bytes) {
        if (bytes == null || bytes.length == 0) {
            throw BizException.badRequest("文件内容为空");
        }
        if (bytes.length > MAX_BYTES) {
            throw BizException.badRequest("文件超过 50MB 上限，请拆分后上传");
        }
        String lower = fileName == null ? "" : fileName.toLowerCase();
        try {
            if (lower.endsWith(".pdf")) {
                return parsePdf(bytes);
            }
            if (lower.endsWith(".docx")) {
                return parseDocx(bytes);
            }
            if (lower.endsWith(".doc")) {
                return parseDoc(bytes);
            }
            if (lower.endsWith(".xlsx")) {
                return parseXlsx(bytes);
            }
            if (lower.endsWith(".xls")) {
                return parseXls(bytes);
            }
            if (lower.endsWith(".txt") || lower.endsWith(".md") || lower.endsWith(".csv")
                    || lower.endsWith(".json") || lower.endsWith(".log")) {
                return new String(bytes, StandardCharsets.UTF_8);
            }
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            log.warn("kb file parse failed: {} {}", fileName, e.getMessage());
            throw BizException.badRequest("文件解析失败：" + e.getMessage());
        }
        throw BizException.badRequest("暂不支持的文件格式，仅支持 " + SUPPORTED);
    }

    private String parsePdf(byte[] bytes) throws Exception {
        try (org.apache.pdfbox.pdmodel.PDDocument doc = Loader.loadPDF(bytes)) {
            PDFTextStripper stripper = new PDFTextStripper();
            stripper.setSortByPosition(true);
            return stripper.getText(doc);
        }
    }

    private String parseDocx(byte[] bytes) throws Exception {
        StringBuilder sb = new StringBuilder();
        try (InputStream in = new ByteArrayInputStream(bytes);
             XWPFDocument doc = new XWPFDocument(in)) {
            for (XWPFParagraph p : doc.getParagraphs()) {
                String t = p.getText();
                if (t != null && !t.isBlank()) {
                    sb.append(t.trim()).append('\n');
                }
            }
            // 表格内容一并抽取（文档中常见结构化信息）
            for (XWPFTable table : doc.getTables()) {
                for (XWPFTableRow row : table.getRows()) {
                    List<String> cells = new ArrayList<>();
                    for (XWPFTableCell cell : row.getTableCells()) {
                        cells.add(cell.getText());
                    }
                    sb.append(String.join(" ", cells).trim()).append('\n');
                }
            }
        }
        return sb.toString();
    }

    private String parseDoc(byte[] bytes) throws Exception {
        try (InputStream in = new ByteArrayInputStream(bytes);
             HWPFDocument doc = new HWPFDocument(in);
             WordExtractor extractor = new WordExtractor(doc)) {
            String[] paras = extractor.getParagraphText();
            StringBuilder sb = new StringBuilder();
            for (String p : paras) {
                if (p != null && !p.isBlank()) {
                    sb.append(p.trim()).append('\n');
                }
            }
            return sb.toString();
        }
    }

    private String parseXlsx(byte[] bytes) throws Exception {
        return readSheet(new XSSFWorkbook(new ByteArrayInputStream(bytes)));
    }

    private String parseXls(byte[] bytes) throws Exception {
        return readSheet(new HSSFWorkbook(new ByteArrayInputStream(bytes)));
    }

    /** Excel：逐 Sheet 输出 Markdown 表格（表名标题 + 表头 + 对齐行 + 数据行）。
     *
     * <p>旧实现「行内以空格拼接」丢掉了列对齐：多列表（如报名表）抽出来的文本列错位，
     * 模型无法按行按列读表（docs/60 P2-10，2026-10-26）。Markdown 表格对模型显著更友好。</p>
     *
     * <p>细节：单元格里的 {@code |} 与换行做转义（否则破坏表格结构）；整行空白跳过；
     * 列数取「最右非空单元格」的最大值（尾部空列不撑宽表格，但行内空洞保留以维持对齐）。</p>
     */
    private String readSheet(Workbook wb) throws Exception {
        DataFormatter formatter = new DataFormatter();
        StringBuilder sb = new StringBuilder();
        try (wb) {
            for (int s = 0; s < wb.getNumberOfSheets(); s++) {
                Sheet sheet = wb.getSheetAt(s);
                int maxCols = 0;
                for (Row row : sheet) {
                    int last = row.getLastCellNum(); // short；-1 = 行内无单元格
                    for (int c = last - 1; c >= 0; c--) {
                        Cell cell = row.getCell(c);
                        String v = cell == null ? "" : formatter.formatCellValue(cell).trim();
                        if (!v.isEmpty()) {
                            if (c + 1 > maxCols) {
                                maxCols = c + 1;
                            }
                            break;
                        }
                    }
                }
                if (maxCols == 0) {
                    continue; // 整表皆空（只有格式没有内容）
                }
                sb.append("### ").append(sheet.getSheetName()).append('\n');
                boolean headerDone = false;
                for (Row row : sheet) {
                    List<String> cells = new ArrayList<>(maxCols);
                    boolean hasValue = false;
                    for (int c = 0; c < maxCols; c++) {
                        Cell cell = row.getCell(c);
                        String v = cell == null ? "" : formatter.formatCellValue(cell).trim();
                        if (!v.isEmpty()) {
                            hasValue = true;
                        }
                        v = v.replace("|", "\\|").replace("\n", " ").replace("\r", " ");
                        cells.add(v);
                    }
                    if (!hasValue) {
                        continue; // 整行空白跳过
                    }
                    sb.append("| ").append(String.join(" | ", cells)).append(" |\n");
                    if (!headerDone) {
                        sb.append("|");
                        for (int c = 0; c < maxCols; c++) {
                            sb.append(" --- |");
                        }
                        sb.append('\n');
                        headerDone = true;
                    }
                }
            }
        }
        return sb.toString();
    }
}
