package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
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

    /** Excel：逐行拼接单元格，行内以空格分隔，行间换行。 */
    private String readSheet(Workbook wb) throws Exception {
        DataFormatter formatter = new DataFormatter();
        StringBuilder sb = new StringBuilder();
        try (wb) {
            for (int s = 0; s < wb.getNumberOfSheets(); s++) {
                Sheet sheet = wb.getSheetAt(s);
                for (Row row : sheet) {
                    List<String> cells = new ArrayList<>();
                    for (Cell cell : row) {
                        String v = formatter.formatCellValue(cell);
                        if (v != null && !v.isBlank()) {
                            cells.add(v.trim());
                        }
                    }
                    if (!cells.isEmpty()) {
                        sb.append(String.join(" ", cells)).append('\n');
                    }
                }
            }
        }
        return sb.toString();
    }
}
