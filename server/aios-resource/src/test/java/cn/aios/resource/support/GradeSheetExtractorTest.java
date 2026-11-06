package cn.aios.resource.support;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 拍平成绩单的结构化还原（docs/75）。
 *
 * <p>样本 {@code grade-sheet-sample.txt} 是<b>线上真实资料</b>的正文（kb_document id=249，
 * 四川轻化工大学学业成绩表 PDF 取出的文本），不是手写样例 —— 只有这样才覆盖得到
 * 「四栏并排被拍平、表头拆两行、汇总标签行与数值行分居两行」这些真实形态。</p>
 *
 * <p><b>金标准来自文档自身</b>（不同源交叉校验，铁律 12）：抽出的 62 门课学分合计必须等于
 * 文档里写的「已获得总学分 134.0」，9 类课程性质的学分必须逐项等于汇总行。
 * 一旦哪天正则改坏了，这两条会先红。</p>
 */
class GradeSheetExtractorTest {

    private static String raw;

    @BeforeAll
    static void load() throws IOException {
        raw = Files.readString(Path.of("src/test/resources/grade-sheet-sample.txt"), StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("识别为成绩单：抽出 62 门课，学分合计等于文档自述的已获得总学分")
    void coursesMatchSelfDeclaredCreditTotal() {
        assertTrue(GradeSheetExtractor.isGradeSheet(raw), "真实成绩单应被识别");

        List<GradeSheetExtractor.Course> cs = GradeSheetExtractor.courses(raw);
        assertEquals(62, cs.size(), "课程条数");

        double sum = cs.stream().mapToDouble(c -> Double.parseDouble(c.credit())).sum();
        String declared = GradeSheetExtractor.summaryMap(raw).get("已获得总学分");
        assertEquals(134.0, Double.parseDouble(declared), 1e-9, "文档自述总学分");
        assertEquals(Double.parseDouble(declared), sum, 1e-9, "抽出学分合计必须等于自述总学分");
    }

    @Test
    @DisplayName("按课程性质分组求和，9 类逐项等于汇总行（不同源校验）")
    void creditsByTypeMatchSummaryRow() {
        Map<String, Double> byType = new LinkedHashMap<>();
        for (GradeSheetExtractor.Course c : GradeSheetExtractor.courses(raw)) {
            byType.merge(c.type(), Double.parseDouble(c.credit()), Double::sum);
        }
        Map<String, String> sum = GradeSheetExtractor.summaryMap(raw);
        Map<String, Double> expect = new LinkedHashMap<>();
        expect.put("通识必修课", 24.0);
        expect.put("通识选修课", 5.0);
        expect.put("学基必修课", 33.0);
        expect.put("专核必修课", 23.0);
        expect.put("专业选修课", 11.0);
        expect.put("集实必修课", 3.0);
        expect.put("素实必修课", 8.0);
        expect.put("复培选修课", 12.0);
        expect.put("专基必修课", 15.0);
        assertEquals(9, byType.size(), "课程性质种类数");
        expect.forEach((label, v) -> {
            String type = label.substring(0, label.length() - 1); // 去掉尾字「课」
            assertEquals(v, byType.get(type), 1e-9, "性质 " + type + " 学分");
            assertEquals(String.valueOf(v), sum.get(label), "汇总行 " + label);
        });
    }

    @Test
    @DisplayName("汇总：标签行与下一行数值正确对齐（首格为空右对齐，不被错配到 80.26）")
    void summaryAlignsLabelRowWithValueRow() {
        Map<String, String> sum = GradeSheetExtractor.summaryMap(raw);
        assertEquals("80.26", sum.get("历年平均成绩"));
        assertEquals("2.69", sum.get("历年平均学分绩点"));
        assertEquals("150.0", sum.get("毕业应取得总学分"));
        assertEquals("134.0", sum.get("已获得总学分"));
        // 首格是空的「毕业设计(论文)题目」：不能把 80.26 配给它
        assertNotEquals("80.26", sum.getOrDefault("毕业设计(论文)题目", ""));
        // 「其中/包括」这类填充词必须被剔掉，否则后面整排会错位一格
        assertFalse(sum.containsKey("其中"));
        assertFalse(sum.containsKey("包括"));
    }

    @Test
    @DisplayName("补考列：只认「大学物理B1 56 → 62」，不把学年 2025-2026 截成 202")
    void makeupColumnIgnoresAcademicYear() {
        List<GradeSheetExtractor.Course> makeup = GradeSheetExtractor.courses(raw).stream()
                .filter(c -> !c.makeup().isEmpty()).toList();
        assertEquals(1, makeup.size(), "补考课程条数");
        assertEquals("大学物理B1", makeup.get(0).name());
        assertEquals("56", makeup.get(0).score());
        assertEquals("62", makeup.get(0).makeup());
        // 任何一条的「学分」都不该被读成年份片段
        for (GradeSheetExtractor.Course c : GradeSheetExtractor.courses(raw)) {
            assertFalse(c.credit().startsWith("202"), c.name() + " 的学分被读错：" + c.credit());
        }
    }

    @Test
    @DisplayName("回填：拼出两张 Markdown 表，下游可直接解析（幂等，不重复追加）")
    void enrichProducesParseableTablesAndIsIdempotent() {
        String enriched = GradeSheetExtractor.enrich(raw);
        assertTrue(enriched.contains("### " + GradeSheetExtractor.DETAIL_TITLE));
        assertTrue(enriched.contains("### " + GradeSheetExtractor.SUMMARY_TITLE));

        List<MarkdownTable.Table> tables = MarkdownTable.parse(enriched, "成绩单.pdf");
        assertEquals(2, tables.size(), "明细表 + 汇总表");
        MarkdownTable.Table detail = tables.get(0);
        assertEquals(List.of("课程名称", "课程性质", "学分", "成绩", "补考"), detail.columns());
        assertEquals(62, detail.rows().size(), "明细行数");
        // 汇总表两行标签各自对齐 → 3 项（成绩/绩点行）+ 11 项（学分构成行）= 14 条；
        // 「毕业设计(论文)题目」原件该格为空，渲染成 — 而不是错配成 80.26
        assertEquals(14, tables.get(1).rows().size(), "汇总行数（含空值项）");
        assertTrue(tables.get(1).rows().stream()
                .anyMatch(r -> r.get(0).equals("毕业设计(论文)题目") && r.get(1).equals("—")));

        // 幂等：再 enrich 一次结果不变，重复入库不会出现两份表
        assertEquals(enriched, GradeSheetExtractor.enrich(enriched));
        assertEquals(1, enriched.split("### " + GradeSheetExtractor.DETAIL_TITLE, -1).length - 1);
    }

    @Test
    @DisplayName("不误伤：普通文档、已回填文本都不做处理")
    void doesNotTouchOtherDocs() {
        String prose = "本项目为非遗数字化保护项目，涉及川剧、蜀绣等门类的建档与传播，"
                + "每年举办展览与培训，覆盖多个地区。";
        assertFalse(GradeSheetExtractor.isGradeSheet(prose));
        assertEquals(prose, GradeSheetExtractor.enrich(prose));

        // 只有「成绩」「学分」两个词但抽不出 3 条课程 —— 仍不动
        String loose = "本次考试成绩已公布，学分认定办法见附件。学分为 3 学分。";
        assertEquals(loose, GradeSheetExtractor.enrich(loose));

        // 已回填过的正文不再二次识别
        String enriched = GradeSheetExtractor.enrich(raw);
        assertFalse(GradeSheetExtractor.isGradeSheet(enriched));
    }
}
