package cn.aios.resource.support;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 成绩单等「拍平表格」的结构化还原（docs/75）。
 *
 * <p><b>问题</b>：PDF 成绩表常见「四栏并排排版」，PDF 取文本后列结构全丢，只剩一串用空格
 * 分隔的 token，且表头被拆成两行、汇总的<b>标签行与数值行是两行</b>：</p>
 * <pre>
 * 课    程 课程 学 成 补 重 课    程 课程 学 成 补 重 …   ← 表头被拆成两行 ×4 组
 * 名    称 性质 分 绩 考 修 名    称 性质 分 绩 考 修 …
 * 高等数学A1 学基必修 6.0 73 概率论与数理统计 学基必修 2.0 82 …
 * 毕业设计(论文)题目 历年平均成绩 历年平均学分绩点        ← 只有栏名
 * 80.26 2.69                                        ← 数值在下一行
 * </pre>
 * <p>于是切片只能切出「栏名」和「数值」两个互不相邻的碎片，检索到「历年平均成绩」那一段时
 * <b>旁边没有 80.26</b>，模型只能回答「未取得数值」。这不是检索坏了，是<b>结构没被还原</b>。</p>
 *
 * <p><b>做法</b>：把拍平文本按「名称 → 性质 → 学分 → 成绩 →（补考）」的固定顺序用正则还原成记录，
 * 再把「标签行 + 下一行数值」按 token 位对齐成键值对，最后<b>重新渲染成 Markdown 表格</b>拼回正文尾部。
 * 一旦变成 Markdown 表格，下游全部复用（{@link MarkdownTable} 的列名分块 + 统计摘要 +
 * {@code kb_table_query} 聚合），不需要为 PDF 再开一条链路。</p>
 *
 * <p><b>为什么回填到正文而不是另存结构</b>：{@code retry} 只从 {@code kb_document.content} 重切片，
 * 回填后<b>存量 PDF 无需重新上传</b>即可修复；{@link #enrich} 对已回填文本幂等，
 * 重复入库不会出现两份表。</p>
 *
 * <p><b>校验方式</b>：用文档<b>自带的汇总数</b>做交叉验证（不同源）—— 抽出的学分合计必须等于
 * 「已获得总学分」，各课程性质的学分必须逐项等于汇总里的分类学分。实测某份成绩单：
 * 62 门课 / 134.0 学分，9 个分类逐项吻合（见 {@code GradeSheetExtractorTest}）。</p>
 */
public final class GradeSheetExtractor {

    /** 明细表回填时的固定标题：既给切片当表名，也用作幂等标记。 */
    public static final String DETAIL_TITLE = "成绩明细";

    /** 汇总表回填时的固定标题。 */
    public static final String SUMMARY_TITLE = "成绩汇总";

    /** 课程性质：2~4 个汉字 + 必修/选修（通识必修、专业选修、专核必修…）。 */
    private static final String TYPE_RE = "[\\u4e00-\\u9fa5]{2,4}(?:必修|选修)";

    /** 成绩：百分制数字或五级制文字。 */
    private static final String SCORE_RE = "(?:\\d{1,3}|优|良|中|及格|不及格|合格|不合格)";

    /** 学分：允许 "1" 与 "3.0" 两种写法。 */
    private static final String CREDIT_RE = "\\d+(?:\\.\\d+)?";

    /**
     * 一条课程记录。补考分要求「后面是空白或结束」，否则会把下一行的
     * {@code 2025-2026学年} 截成 {@code 202} 当成补考分（实测踩过）。
     */
    private static final Pattern COURSE = Pattern.compile(
            "([\\u4e00-\\u9fa5A-Za-z0-9()（）·\\-]+)\\s+(" + TYPE_RE + ")\\s+(" + CREDIT_RE + ")\\s+("
                    + SCORE_RE + ")(?:\\s+(\\d{1,3})(?=\\s|$))?");

    /** 汇总标签行：出现这些词就认为这一行是「只有栏名」的那一行。 */
    private static final String[] SUMMARY_HINTS = {"历年平均", "总学分", "毕业设计"};

    /** 标签/数值两侧的对齐填充词（"其中 通识必修课…" / "150.0 134.0 包括 24.0…"）。 */
    private static final Set<String> FILLER = Set.of("其中", "包括", "含", "其中：", "包括：");

    /** 至少识别出这么多条课程，才认为这是一份成绩单（防误伤普通文档）。 */
    private static final int MIN_COURSES = 3;

    private GradeSheetExtractor() {
    }

    /** 一条课程：名称 / 性质 / 学分 / 成绩 / 补考（可空）。 */
    public record Course(String name, String type, String credit, String score, String makeup) {
    }

    /** 一条汇总：项目 / 数值（可能为空串，表示原件该格是空的）。 */
    public record Summary(String label, String value) {
    }

    /** 从正文还原课程记录（按出现顺序）。 */
    public static List<Course> courses(String text) {
        List<Course> out = new ArrayList<>();
        if (text == null || text.isEmpty()) {
            return out;
        }
        Matcher m = COURSE.matcher(text);
        while (m.find()) {
            out.add(new Course(m.group(1), m.group(2), m.group(3), m.group(4),
                    m.group(5) == null ? "" : m.group(5)));
        }
        return out;
    }

    /**
     * 还原「标签行 + 下一行数值」的汇总。
     *
     * <p>对齐规则：两侧去掉填充词（其中/包括）后按 token 位对齐；数值比标签少时<b>右对齐</b>
     * （首格为空的 {@code 毕业设计(论文)题目} 因此不会被错配成 80.26）。</p>
     */
    public static List<Summary> summary(String text) {
        List<Summary> out = new ArrayList<>();
        if (text == null || text.isEmpty()) {
            return out;
        }
        String[] lines = text.replace("\r", "").split("\n", -1);
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i].trim();
            if (!isSummaryLabelLine(line)) {
                continue;
            }
            String next = "";
            for (int j = i + 1; j < lines.length; j++) {
                if (!lines[j].trim().isEmpty()) {
                    next = lines[j].trim();
                    break;
                }
            }
            if (next.isEmpty()) {
                continue;
            }
            List<String> labels = tokens(line);
            List<String> values = tokens(next);
            if (values.isEmpty()) {
                continue;
            }
            // 对齐以**右端**为基准：off<0（数值少于标签）时右对齐，首格为空的
            // 「毕业设计(论文)题目」因此不会被错配成 80.26。
            // off>0（数值多于标签）时同一条规则会跳过前 off 个数值 —— 若多出来的值其实
            // 在末尾，整段会偏移一位。没有可靠信号判断多余值在头还是在尾，故保持单一
            // 规则、不猜（B6 记为已知风险，靠「标签行与数值行 token 数一致」的上游约束规避）。
            // 原代码还有一处 `off < -labels.size()` 判断：因 values 非空 ⇒
            // off ≥ 1-labels.size() > -labels.size()，该条件恒假，是死检查，已删。
            int off = values.size() - labels.size();
            for (int j = 0; j < labels.size(); j++) {
                int vi = j + off;
                String v = vi >= 0 && vi < values.size() ? values.get(vi) : "";
                out.add(new Summary(labels.get(j), v));
            }
        }
        return out;
    }

    /** 是否是成绩单类资料：含「成绩」+「学分」，且能抽出 ≥ {@value #MIN_COURSES} 条课程。 */
    public static boolean isGradeSheet(String text) {
        if (text == null || text.isEmpty()) {
            return false;
        }
        if (!text.contains("成绩") || !text.contains("学分")) {
            return false;
        }
        if (text.contains(DETAIL_TITLE) || text.contains("| 课程名称 |")) {
            return false; // 已回填过，别再判一次
        }
        return courses(text).size() >= MIN_COURSES;
    }

    /**
     * 把结构化的两张表用 Markdown 拼回正文尾部（幂等：已回填则原样返回）。
     *
     * <p>回填后 {@link MarkdownTable#parse} 就能解析出「课程名称/课程性质/学分/成绩」列，
     * 于是分块带列名、统计摘要给出「62 条 + 按性质计数」、{@code kb_table_query} 能
     * 精确计数与求和 —— PDF 与 Excel 走同一条下游链路。</p>
     */
    public static String enrich(String text) {
        if (text == null || text.isEmpty() || text.contains("### " + DETAIL_TITLE)) {
            return text;
        }
        if (!isGradeSheet(text)) {
            return text;
        }
        List<Course> cs = courses(text);
        StringBuilder sb = new StringBuilder(text.length() + 4096);
        sb.append(text).append("\n\n### ").append(DETAIL_TITLE).append('\n');
        sb.append("| 课程名称 | 课程性质 | 学分 | 成绩 | 补考 |\n");
        sb.append("| --- | --- | --- | --- | --- |\n");
        for (Course c : cs) {
            sb.append("| ").append(c.name()).append(" | ").append(c.type()).append(" | ")
                    .append(c.credit()).append(" | ").append(c.score()).append(" | ")
                    .append(c.makeup() == null || c.makeup().isEmpty() ? "—" : c.makeup())
                    .append(" |\n");
        }
        List<Summary> sums = summary(text);
        if (!sums.isEmpty()) {
            sb.append("\n### ").append(SUMMARY_TITLE).append('\n');
            sb.append("| 项目 | 数值 |\n| --- | --- |\n");
            for (Summary s : sums) {
                sb.append("| ").append(s.label()).append(" | ")
                        .append(s.value() == null || s.value().isEmpty() ? "—" : s.value()).append(" |\n");
            }
        }
        return sb.toString();
    }

    /** 汇总 → 标签到数值的映射（调试与验收用）。 */
    public static java.util.Map<String, String> summaryMap(String text) {
        java.util.Map<String, String> out = new java.util.LinkedHashMap<>();
        for (Summary s : summary(text)) {
            out.put(s.label(), s.value());
        }
        return out;
    }

    private static boolean isSummaryLabelLine(String line) {
        if (line.isEmpty() || line.startsWith("|")) {
            return false;
        }
        boolean hinted = false;
        for (String h : SUMMARY_HINTS) {
            if (line.contains(h)) {
                hinted = true;
                break;
            }
        }
        return hinted && tokens(line).size() >= 2;
    }

    private static List<String> tokens(String line) {
        List<String> out = new ArrayList<>();
        for (String t : line.trim().split("\\s+")) {
            if (t.isEmpty() || FILLER.contains(t)) {
                continue;
            }
            out.add(t);
        }
        return out;
    }
}
