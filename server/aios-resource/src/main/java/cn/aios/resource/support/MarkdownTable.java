package cn.aios.resource.support;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Markdown 表格解析（Excel → Markdown 之后的唯一结构化入口，docs/74）。
 *
 * <p>为什么需要它：{@code KbFileParser.readSheet()} 把 Excel 输出成 Markdown 表格，
 * <b>每个数据行以 {@code \n} 结尾</b>；而 {@code KbService.split()} 按 {@code \n} 切段、
 * 单段 ≤ chunkSize 直接成块 ⇒ <b>表格被切成「一行一块」</b>，500 行的表切出 503 块，
 * 其中带列名的只有 1 块（表头）。模型拿到的是
 * {@code | 1 | 川剧 | 传统技艺 | 成都市 | 第六批 |} —— 不知道哪列是"序号"、哪列是"批次"。</p>
 *
 * <p>本类把 Markdown 表格还原成「表名 + 列名 + 行」，供三处使用：</p>
 * <ol>
 *   <li>切片：每块前置「《doc》/sheet｜列: a/b/c｜」，列名覆盖率 1/503 → 100%；</li>
 *   <li>统计摘要：入库时生成 {@code 【统计摘要】} 块，回答「共有多少条 / 分类计数」；</li>
 *   <li>聚合查询：{@code kb_table_query} 工具直接对行做 count / group by。</li>
 * </ol>
 *
 * <p>实现约束：单元格里的 {@code |} 被转义成 {@code \|}（见 {@code KbFileParser}），
 * 拆分时必须尊重转义，否则列会错位 —— 这是本类最容易写错的地方。</p>
 */
public final class MarkdownTable {

    /** 统计摘要块的固定前缀：检索层（{@code MysqlKnowledgeStore}）靠它识别并置顶。 */
    public static final String STATS_MARK = "【统计摘要】";

    /** 单块最多容纳的数据行数（配合 900 字预算，通常 15~22 行）。 */
    private static final int MAX_ROWS_PER_CHUNK = 20;

    /** 分块字符预算（略小于常用 chunkSize，留出列名前缀的余量）。 */
    private static final int CHUNK_BUDGET = 900;

    /**
     * 「小表整表一块」的行数上限。
     *
     * <p>键值表（成绩汇总、配置清单）行数少且<b>标签与数值成对</b>，切开会把「历年平均学分绩点」
     * 和「2.69」分到两块里 —— 检索命中前者时旁边没有数，模型只能答「没有相邻的数值」。
     * 小表整表一块后，一条命中就能带回全部键值对。</p>
     */
    private static final int MAX_ROWS_SINGLE_CHUNK = 30;

    /** 小表整表成块时的总字数上限（防止「行数少但每行很长」把单块撑爆）。 */
    private static final int SINGLE_CHUNK_MAX_CHARS = 1800;

    /** 统计摘要里参与分组的列，取值基数上限（超过就是"每行都不同"的 id 类列，无意义）。 */
    private static final int MAX_CARDINALITY = 20;

    private MarkdownTable() {
    }

    /** 一张表：表名（sheet 名或文档名）+ 列名 + 数据行。 */
    public static final class Table {
        private final String name;
        private final List<String> columns;
        private final List<List<String>> rows;
        /** 表格在正文里的起止行号（含），供切片时原位替换。 */
        private final int startLine;
        private final int endLine;

        Table(String name, List<String> columns, List<List<String>> rows, int startLine, int endLine) {
            this.name = name;
            this.columns = columns;
            this.rows = rows;
            this.startLine = startLine;
            this.endLine = endLine;
        }

        public String name() {
            return name;
        }

        public List<String> columns() {
            return columns;
        }

        public List<List<String>> rows() {
            return rows;
        }

        public int startLine() {
            return startLine;
        }

        public int endLine() {
            return endLine;
        }

        /** 列号 → 列名（越界返回 {@code 列N}），聚合时用来把入参列名对到下标。 */
        public String columnAt(int i) {
            return i >= 0 && i < columns.size() ? columns.get(i) : ("列" + (i + 1));
        }

        /** 按列名取下标（先精确、再去空白/忽略大小写），找不到返回 -1。 */
        public int indexOf(String column) {
            if (column == null) {
                return -1;
            }
            String want = column.trim();
            for (int i = 0; i < columns.size(); i++) {
                if (columns.get(i).equals(want)) {
                    return i;
                }
            }
            for (int i = 0; i < columns.size(); i++) {
                if (columns.get(i).trim().equalsIgnoreCase(want)) {
                    return i;
                }
            }
            return -1;
        }
    }

    /**
     * 解析正文中所有 Markdown 表格。
     *
     * <p>识别口径：一行以 {@code |} 开头且含至少两个 {@code |}，<b>且下一行是分隔行</b>
     * （{@code | --- | --- |}）才认定为表头 —— 只看 {@code |} 会把正文里偶然的竖线当成表。
     * 表名取表格上方最近的 {@code ### xxx} 标题（Excel 的 sheet 名），没有就用 docName。</p>
     */
    public static List<Table> parse(String content, String docName) {
        List<Table> out = new ArrayList<>();
        if (content == null || content.isEmpty()) {
            return out;
        }
        String[] lines = content.replace("\r", "").split("\n", -1);
        String sheet = docName;
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i].trim();
            if (line.startsWith("###")) {
                String t = line.substring(3).trim();
                if (!t.isEmpty()) {
                    sheet = t;
                }
                continue;
            }
            if (!isRow(line) || i + 1 >= lines.length || !isSeparator(lines[i + 1])) {
                continue;
            }
            List<String> columns = cells(line);
            List<List<String>> rows = new ArrayList<>();
            int j = i + 2;
            for (; j < lines.length; j++) {
                String r = lines[j].trim();
                if (!isRow(r)) {
                    break;
                }
                List<String> cells = cells(r);
                if (isBlank(cells)) {
                    continue;
                }
                rows.add(cells);
            }
            out.add(new Table(sheet == null || sheet.isBlank() ? "表格" : sheet,
                    columns, rows, i, j - 1));
            i = j - 1;
        }
        return out;
    }

    /** 单张表的「列名前缀」：{@code 《doc》/sheet｜列: a/b/c｜}，每个数据块都带，防止列义丢失。 */
    public static String headerPrefix(String docName, Table t) {
        StringBuilder sb = new StringBuilder();
        sb.append('《').append(docName == null || docName.isBlank() ? "文档" : docName).append('》');
        if (t.name() != null && !t.name().isBlank() && !t.name().equals(docName)) {
            sb.append('/').append(t.name());
        }
        sb.append("｜列: ").append(String.join("/", t.columns())).append('｜');
        return sb.toString();
    }

    /**
     * 把一张表切成「列名 + 连续 N 行」的块（P0-1 的核心）。
     *
     * <p><b>按表形态选策略</b>（docs/76）：</p>
     * <ul>
     *   <li><b>小表</b>（行数 ≤ {@value #MAX_ROWS_SINGLE_CHUNK} 且总字数 ≤
     *       {@value #SINGLE_CHUNK_MAX_CHARS}）→ <b>整表一块</b>。键值表的标签与数值必须同块，
     *       切开就会出现「命中栏名但旁边没有数」。</li>
     *   <li><b>大表</b>（明细/台账）→ 每块 ≤ {@value #MAX_ROWS_PER_CHUNK} 行、≤
     *       {@value #CHUNK_BUDGET} 字，每块都带列名前缀。</li>
     * </ul>
     * <p>表头与分隔行**不再单独成块** —— 列名已进每块的前缀，单独成块只会白占一个检索位。</p>
     */
    public static List<String> chunks(String docName, Table t) {
        List<String> out = new ArrayList<>();
        String prefix = headerPrefix(docName, t);
        if (t.rows().isEmpty()) {
            // 空表（只有表头）：保留一块，让「有这张表但没数据」也被检索到
            out.add(prefix);
            return out;
        }
        if (fitsSingleChunk(t, prefix)) {
            // 与多块路径保持同一种排版：前缀与第 1 行同行（这样「行数 = 换行段数」对两者都成立）
            StringBuilder sb = new StringBuilder(prefix);
            for (int i = 0; i < t.rows().size(); i++) {
                if (i > 0) {
                    sb.append('\n');
                }
                sb.append(rowLine(t.rows().get(i)));
            }
            out.add(sb.toString());
            return out;
        }
        List<String> group = new ArrayList<>();
        int len = prefix.length();
        for (List<String> row : t.rows()) {
            String line = rowLine(row);
            if (!group.isEmpty()
                    && (len + line.length() + 1 > CHUNK_BUDGET || group.size() >= MAX_ROWS_PER_CHUNK)) {
                out.add(prefix + String.join("\n", group));
                group = new ArrayList<>();
                len = prefix.length();
            }
            group.add(line);
            len += line.length() + 1;
        }
        if (!group.isEmpty()) {
            out.add(prefix + String.join("\n", group));
        }
        return out;
    }

    /** 这张表是否小到可以整表一块（键值表/汇总表/小配置表）。 */
    private static boolean fitsSingleChunk(Table t, String prefix) {
        if (t.rows().size() > MAX_ROWS_SINGLE_CHUNK) {
            return false;
        }
        int len = prefix.length();
        for (List<String> row : t.rows()) {
            len += rowLine(row).length() + 1;
            if (len > SINGLE_CHUNK_MAX_CHARS) {
                return false;
            }
        }
        return true;
    }

    /**
     * 生成统计摘要块（P0-2）：回答「共有多少条 / 某列分别多少个」。
     *
     * <p>为什么必须单独生成：topK 默认 5，即使检索完美也只覆盖 5/1241 行，
     * 拿 5 行明细问总数是结构性不可能（docs/74 根因 2）。摘要块把「行数 + 低基数列的
     * 分组计数」压成一块，让聚合问题第一次就有了答案。</p>
     *
     * <p>选列口径：只统计不同取值数 ≤ {@value #MAX_CARDINALITY} 的列。
     * 序号/项目名称这种"每行都不同"的列会被自动跳过（对计数毫无意义，还会撑爆预算）。</p>
     */
    public static String statsText(String docName, Table t) {
        if (t.rows().isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        sb.append(STATS_MARK).append('《')
                .append(docName == null || docName.isBlank() ? "文档" : docName).append('》');
        if (t.name() != null && !t.name().isBlank() && !t.name().equals(docName)) {
            sb.append('/').append(t.name());
        }
        sb.append("｜数据行合计：").append(t.rows().size()).append(" 条");
        sb.append("｜列：").append(String.join("/", t.columns()));
        for (int c = 0; c < t.columns().size(); c++) {
            Map<String, Integer> counts = countColumn(t, c);
            // 每行都不同 = 键列（序号 / 项目名称 / 键值表的「项目」），分组只会得到
            // 「xxx 1 条、yyy 1 条…」的噪声，直接跳过。
            if (counts.size() < 1 || counts.size() > MAX_CARDINALITY
                    || counts.size() == t.rows().size()) {
                continue;
            }
            StringBuilder part = new StringBuilder();
            counts.entrySet().stream()
                    .sorted((a, b) -> Integer.compare(b.getValue(), a.getValue()))
                    .limit(MAX_CARDINALITY)
                    .forEach(e -> part.append(part.isEmpty() ? "" : "、")
                            .append(e.getKey().isEmpty() ? "(空)" : e.getKey())
                            .append(' ').append(e.getValue()).append(" 条"));
            String piece = "｜按「" + t.columnAt(c) + "」：" + part;
            if (sb.length() + piece.length() > CHUNK_BUDGET) {
                continue; // 预算不足就跳过该列，宁可少一维分组也不切断摘要
            }
            sb.append(piece);
        }
        return sb.toString();
    }

    /** 统计某列各取值出现次数（保序：按首次出现顺序，调用方再按次数排序）。 */
    public static Map<String, Integer> countColumn(Table t, int col) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (List<String> row : t.rows()) {
            String v = col >= 0 && col < row.size() ? row.get(col).trim() : "";
            counts.merge(v, 1, Integer::sum);
        }
        return counts;
    }

    /** 行 → Markdown 行文本（与 {@code KbFileParser} 输出保持一致）。 */
    public static String rowLine(List<String> row) {
        return "| " + String.join(" | ", row) + " |";
    }

    /** 是否是表格数据行：以 {@code |} 开头，且（未转义的）竖线至少两个。 */
    static boolean isRow(String line) {
        if (line == null) {
            return false;
        }
        String s = line.trim();
        if (!s.startsWith("|")) {
            return false;
        }
        return cells(s).size() >= 1 && countPipes(s) >= 2;
    }

    /** 是否分隔行：{@code | --- | :--: |} —— 每个单元格只由 {@code - : 空格} 组成且至少一个 {@code -}。 */
    static boolean isSeparator(String line) {
        if (line == null || !line.trim().startsWith("|")) {
            return false;
        }
        List<String> cs = cells(line);
        if (cs.isEmpty()) {
            return false;
        }
        for (String c : cs) {
            String v = c.trim();
            if (v.isEmpty() || !v.matches(":?-{1,}:?")) {
                return false;
            }
        }
        return true;
    }

    /**
     * 拆单元格：尊重 {@code \|} 转义（Excel 单元格里的字面竖线），
     * 首尾的空壳单元（行首/行尾的 {@code |} 产生的）丢弃。
     */
    static List<String> cells(String line) {
        List<String> out = new ArrayList<>();
        String s = line.trim();
        StringBuilder cur = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch == '\\' && i + 1 < s.length() && s.charAt(i + 1) == '|') {
                cur.append('|');
                i++;
                continue;
            }
            if (ch == '|') {
                out.add(cur.toString().trim());
                cur.setLength(0);
                continue;
            }
            cur.append(ch);
        }
        out.add(cur.toString().trim());
        // 行以 | 开头 ⇒ 第一个元素是空壳；行以 | 结尾 ⇒ 最后一个也是
        if (!out.isEmpty() && out.get(0).isEmpty()) {
            out.remove(0);
        }
        if (!out.isEmpty() && out.get(out.size() - 1).isEmpty()) {
            out.remove(out.size() - 1);
        }
        return out;
    }

    private static int countPipes(String s) {
        int n = 0;
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch == '\\') {
                i++;
                continue;
            }
            if (ch == '|') {
                n++;
            }
        }
        return n;
    }

    private static boolean isBlank(List<String> cells) {
        for (String c : cells) {
            if (!c.isEmpty()) {
                return false;
            }
        }
        return true;
    }
}
