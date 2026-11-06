package cn.aios.resource.service;

import cn.aios.resource.entity.KbDocument;
import cn.aios.resource.store.KbRelationalDao;
import cn.aios.resource.support.MarkdownTable;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 表格聚合查询（docs/74 P0-2，工具 {@code kb_table_query} 的实现）。
 *
 * <p><b>为什么必须有它</b>：RAG 对「共有多少条 / 按类别分别多少」结构上无解 ——
 * topK 默认 5，1241 行的表即使用完美检索也只看到 5 行。统计摘要块解决了"总数"，
 * 但「按申报地区分别多少」「成都市有哪些」这类组合条件仍然要真聚合，只能对行做运算。</p>
 *
 * <p><b>数据从哪来</b>：直接解析 {@code kb_document.content}（Excel 被
 * {@code KbFileParser} 转成的 Markdown 表格全文）。这样做的好处是<b>存量资料无需重传</b>——
 * 原件字节在上传时就被丢弃了（{@code KbController.uploadFile} 只存解析文本），
 * 若要另建结构化行表，历史文档全部无法回溯。</p>
 *
 * <p><b>安全</b>：只解析「当前用户可见」的文档（{@link KbRelationalDao#listVisible}，
 * 与列表接口同源）。不执行任何用户输入的 SQL —— 入参只有列名与匹配值，
 * 不存在注入面。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KbTableQueryService {

    /** 单次最多扫描的数据行（防御超大表把请求拖死）。 */
    private static final int MAX_SCAN_ROWS = 200_000;

    /** 分组结果默认条数 / 上限。 */
    private static final int DEFAULT_VALUE_LIMIT = 20;
    private static final int MAX_VALUE_LIMIT = 50;

    /**
     * 回给模型的命中行**每页**条数：默认 50、上限 500，配合 {@code offset} 翻页。
     *
     * <p>2026-11-06 修（docs/76）：原先是硬上限 10 且**没有翻页参数**，
     * 于是「列出 62 门课的成绩」只能拿到 10 门 —— 用户看到的是「62 门只返回了十几门」。
     * 枚举类问题必须能翻到底，`hasMore/nextOffset` 明确告诉模型还有没有下一页。</p>
     */
    private static final int DEFAULT_ROW_LIMIT = 50;
    private static final int MAX_ROW_LIMIT = 500;

    /** 找不到文档时回给模型的候选条数。 */
    private static final int MAX_CANDIDATES = 8;

    private final KbRelationalDao dao;

    /**
     * 守卫阈值（实例字段只为了可测：200 000 行造不出来，测试用 package-private 方法调小）。
     *
     * <p>语义是「本次**读取**的物理行数」，与「命中行数」无关 —— 过滤条件命中率低的老实现
     * 拿命中序号当守卫，扫描行数永远上不去（B1）。</p>
     */
    private int scanRowGuard = MAX_SCAN_ROWS;

    /** 仅供单测把守卫调小，生产不要调用。 */
    void scanRowGuardForTest(int v) {
        this.scanRowGuard = v > 0 ? v : MAX_SCAN_ROWS;
    }

    /** 兼容旧签名（不带分页）：等价于 offset=0、limit=默认。 */
    public Map<String, Object> query(Long tenantId, Long userId, String docName, Long docId,
                                     String groupBy, String filter, Integer valueLimit) {
        return query(tenantId, userId, docName, docId, groupBy, filter, valueLimit, null, null);
    }

    /**
     * 对表格类文档做聚合 / 取行。
     *
     * @param docName    文档名（支持片段匹配，如「省级非遗项目名录」）；可为空但需给 docId
     * @param docId      文档 id（优先于 docName）
     * @param groupBy    分组列名；为空则只返回总条数
     * @param filter     筛选条件「列名=值」（值为包含匹配，忽略大小写）；可为空
     * @param valueLimit 分组结果条数上限
     * @param offset     命中行起始下标（从 0 开始），用于翻页枚举
     * @param rowLimit   本页最多返回多少行（默认 50，上限 500）
     * @return 成功 {@code {ok:true, data:{...}}}；失败 {@code {ok:false, error:"..."}}
     */
    public Map<String, Object> query(Long tenantId, Long userId, String docName, Long docId,
                                     String groupBy, String filter, Integer valueLimit,
                                     Integer offset, Integer rowLimit) {
        return query(tenantId, userId, docName, docId, groupBy, filter, valueLimit, offset, rowLimit, null);
    }

    /**
     * 同上，另可按 {@code sheet} 指定表名（一份资料有多张表时）。
     *
     * <p><b>为什么必须按表选</b>（docs/76）：成绩单里有「成绩明细」与「成绩汇总」两张表，
     * 若把两张表的数据行并在一起计数，62 门课会变成 <b>76 行</b>（62 + 汇总的 14 行），
     * 模型照着列就会把「历年平均学分绩点」当成一门课。默认选中<b>命中行最多</b>的那张表
     * （明细），要汇总表就显式传 {@code sheet="成绩汇总"}。</p>
     */
    public Map<String, Object> query(Long tenantId, Long userId, String docName, Long docId,
                                     String groupBy, String filter, Integer valueLimit,
                                     Integer offset, Integer rowLimit, String sheet) {
        long tid = tenantId == null ? 0L : tenantId;
        long uid = userId == null ? 0L : userId;
        List<KbDocument> visible = dao.listVisible(tid, uid);
        List<KbDocument> picked = pick(visible, docName, docId);
        if (picked.isEmpty()) {
            return fail(noDocError(visible, docName, docId));
        }

        String[] filterPair = splitFilter(filter);
        int limit = clamp(valueLimit);
        int start = offset == null ? 0 : Math.max(0, offset);
        int pageSize = rowLimit == null ? DEFAULT_ROW_LIMIT
                : Math.max(1, Math.min(MAX_ROW_LIMIT, rowLimit));

        // ---------- 相位 1：列出这份资料里的所有表，并算出每张表的命中行数 ----------
        List<Sheet> sheets = new ArrayList<>();
        for (KbDocument doc : picked) {
            for (MarkdownTable.Table t : MarkdownTable.parse(doc.getContent(), doc.getDocName())) {
                // -1 = 这张表没有过滤列，不参与（多表文档里别的表可能才有）
                sheets.add(new Sheet(doc, t, countMatched(t, filterPair)));
            }
        }
        if (sheets.isEmpty()) {
            return fail("《" + picked.get(0).getDocName() + "》里没有解析到表格结构（可能是纯文本资料），"
                    + "请改用 search_kb_documents 检索正文");
        }
        List<Map<String, Object>> usedDocs = new ArrayList<>();
        for (Sheet s : sheets) {
            Map<String, Object> used = new LinkedHashMap<>();
            used.put("docName", s.doc().getDocName());
            used.put("sheet", s.table().name());
            used.put("rows", s.table().rows().size());
            used.put("matched", Math.max(0, s.matched()));
            usedDocs.add(used);
        }
        if (filterPair != null && sheets.stream().allMatch(s -> s.matched() < 0)) {
            return fail("文档里没有「" + filterPair[0] + "」这一列。可用列："
                    + String.join("、", sheets.get(0).table().columns()));
        }

        // ---------- 相位 2：选一张表做本次查询 ----------
        int target = pickSheet(sheets, sheet);
        if (target < 0) {
            return fail("找不到名为「" + sheet + "」的表。可用表："
                    + sheets.stream().map(s -> s.table().name()).distinct().toList());
        }
        Sheet sel = sheets.get(target);
        MarkdownTable.Table t = sel.table();
        List<String> columns = t.columns();
        long matched = Math.max(0, sel.matched());
        if (groupBy != null && !groupBy.isBlank() && t.indexOf(groupBy) < 0) {
            return fail("表「" + t.name() + "」里没有「" + groupBy + "」这一列，无法分组。可用列："
                    + String.join("、", columns));
        }
        int groupCol = groupBy == null || groupBy.isBlank() ? -1 : t.indexOf(groupBy);
        int filterCol = filterPair == null ? -1 : t.indexOf(filterPair[0]);
        List<Integer> numCols = numericColumns(t);

        Map<String, Integer> groups = new LinkedHashMap<>();
        // 分组内的数值聚合（如「各课程性质的学分合计」）：key → {列名, 累计值}
        Map<String, Map<String, Double>> groupSums = new LinkedHashMap<>();
        // 表内数值聚合（如「学分合计 134.0」）：列名 → [累计值, 参与行数]
        Map<String, double[]> numeric = new LinkedHashMap<>();
        List<Map<String, String>> samples = new ArrayList<>();
        // idx = 命中行的序号（供 offset 分页）；scanned = 已读的物理行数（供守卫）
        // 两者必须分开：过滤 continue 时不推进 idx，若拿 idx 当守卫，
        // 「按性质过滤」这类查询的扫描行数就永远到不了 MAX_SCAN_ROWS ⇒ 守卫形同不存在。
        long idx = 0;
        long scanned = 0;
        for (List<String> row : t.rows()) {
            if (++scanned > scanRowGuard) {
                return fail("表格过大（超过 " + scanRowGuard + " 行），请缩小范围后再查");
            }
            if (filterCol >= 0) {
                String v = filterCol < row.size() ? row.get(filterCol) : "";
                if (!v.toLowerCase(Locale.ROOT).contains(filterPair[1].toLowerCase(Locale.ROOT))) {
                    continue;
                }
            }
            long seq = idx++;
            // 命中行**分页**返回：只有条数没有内容，回答不了「某门课考了多少分」；
            // 只给前 10 行，又回答不了「列出全部 62 门」。
            if (seq >= start && samples.size() < pageSize) {
                Map<String, String> one = new LinkedHashMap<>();
                for (int c = 0; c < t.columns().size(); c++) {
                    one.put(t.columnAt(c), c < row.size() ? row.get(c) : "");
                }
                samples.add(one);
            }
            String key = null;
            if (groupCol >= 0) {
                key = groupCol < row.size() ? row.get(groupCol).trim() : "";
                key = key.isEmpty() ? "(空)" : key;
                groups.merge(key, 1, Integer::sum);
            }
            for (int c : numCols) {
                Double v = number(row, c);
                if (v == null) {
                    continue;
                }
                String col = t.columnAt(c);
                double[] all = numeric.computeIfAbsent(col, k -> new double[2]);
                all[0] += v;
                all[1] += 1;
                if (key != null) {
                    groupSums.computeIfAbsent(key, k -> new LinkedHashMap<>()).merge(col, v, Double::sum);
                }
            }
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("docName", picked.get(0).getDocName());
        data.put("docs", usedDocs);
        // 本次查的是哪张表 + 这份资料还有哪些表（模型据此决定要不要换 sheet）
        data.put("sheet", t.name());
        List<String> otherSheets = sheets.stream()
                .map(s -> s.table().name()).distinct()
                .filter(n -> !n.equals(t.name())).toList();
        if (!otherSheets.isEmpty()) {
            data.put("otherSheets", otherSheets);
            data.put("sheetHint", "本资料还有其它表：" + String.join("、", otherSheets)
                    + "，需要时传 sheet 参数指定");
        }
        data.put("columns", columns);
        // totalRows 只算**本次选中的这张表**：跨表求和会让「62 门课」变成 76，
        // 正是 docs/76 想消灭的那类「数字对不上」。全资料各表行数在 docs 里逐表给出。
        data.put("totalRows", t.rows().size());
        data.put("matchedRows", matched);
        if (!samples.isEmpty()) {
            data.put("rows", samples);
        }
        data.put("returned", samples.size());
        data.put("offset", start);
        // 明确告诉模型「还有没有下一页」，否则它会把一页当全量（62 门只答 10 门的成因）
        boolean hasMore = start + samples.size() < matched;
        data.put("hasMore", hasMore);
        if (hasMore) {
            data.put("nextOffset", start + samples.size());
            data.put("nextHint", "还有 " + (matched - start - samples.size())
                    + " 行未返回，用 offset=" + (start + samples.size()) + " 继续取");
        }
        if (filterPair != null) {
            data.put("filter", filterPair[0] + " 包含 " + filterPair[1]);
        }
        // 数值列聚合：让「学分合计多少 / 平均分多少」不必靠模型自己加
        if (!numeric.isEmpty()) {
            Map<String, Object> agg = new LinkedHashMap<>();
            numeric.forEach((col, acc) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("sum", round(acc[0]));
                m.put("avg", acc[1] <= 0 ? 0.0 : round(acc[0] / acc[1]));
                m.put("count", (long) acc[1]);
                agg.put(col, m);
            });
            data.put("numeric", agg);
        }
        if (groupBy != null && !groupBy.isBlank()) {
            List<Map<String, Object>> list = groups.entrySet().stream()
                    .sorted((a, b) -> Integer.compare(b.getValue(), a.getValue()))
                    .limit(limit)
                    .map(e -> {
                        Map<String, Object> m = new LinkedHashMap<>();
                        m.put("key", e.getKey());
                        m.put("count", e.getValue());
                        Map<String, Double> sums = groupSums.get(e.getKey());
                        if (sums != null && !sums.isEmpty()) {
                            Map<String, Object> sm = new LinkedHashMap<>();
                            sums.forEach((c, v) -> sm.put(c, round(v)));
                            m.put("sums", sm);
                        }
                        return m;
                    })
                    .toList();
            data.put("groupBy", groupBy);
            data.put("groups", list);
            data.put("distinctKeys", groups.size());
            data.put("truncated", groups.size() > limit);
        }
        Map<String, Object> ok = new LinkedHashMap<>();
        ok.put("ok", true);
        ok.put("data", data);
        return ok;
    }

    /** 一张待选表：所属资料 + 表结构 + 过滤命中行数（-1 = 该表没有过滤列）。 */
    private record Sheet(KbDocument doc, MarkdownTable.Table table, long matched) {
    }

    /** 过滤后在表里的命中行数；该表没有过滤列时返回 -1（这张表不参与本次查询）。 */
    private static long countMatched(MarkdownTable.Table t, String[] filterPair) {
        if (filterPair == null) {
            return t.rows().size();
        }
        int col = t.indexOf(filterPair[0]);
        if (col < 0) {
            return -1;
        }
        String want = filterPair[1].toLowerCase(Locale.ROOT);
        long n = 0;
        for (List<String> row : t.rows()) {
            String v = col < row.size() ? row.get(col) : "";
            if (v.toLowerCase(Locale.ROOT).contains(want)) {
                n++;
            }
        }
        return n;
    }

    /**
     * 选一张表：给了 {@code sheet} 就按名字（含片段）匹配；否则取<b>命中行最多</b>的那张。
     *
     * <p>同分时取行数多的（明细优先于汇总）—— 问「有哪些」时用户要的是明细，
     * 问汇总口径时模型会显式传 {@code sheet}。找不到返回 -1。</p>
     */
    private static int pickSheet(List<Sheet> sheets, String sheet) {
        if (sheet != null && !sheet.isBlank()) {
            String want = sheet.trim().toLowerCase(Locale.ROOT);
            for (int i = 0; i < sheets.size(); i++) {
                String n = sheets.get(i).table().name();
                if (n != null && n.toLowerCase(Locale.ROOT).contains(want)) {
                    return i;
                }
            }
            return -1;
        }
        int best = -1;
        for (int i = 0; i < sheets.size(); i++) {
            long m = sheets.get(i).matched();
            if (m < 0) {
                continue;
            }
            if (best < 0 || m > sheets.get(best).matched()
                    || (m == sheets.get(best).matched()
                        && sheets.get(i).table().rows().size() > sheets.get(best).table().rows().size())) {
                best = i;
            }
        }
        return best >= 0 ? best : 0;
    }

    /** 选文档：docId 优先；否则按名字片段匹配（忽略大小写）。 */
    private List<KbDocument> pick(List<KbDocument> visible, String docName, Long docId) {
        List<KbDocument> out = new ArrayList<>();
        if (docId != null) {
            for (KbDocument d : visible) {
                if (docId.equals(d.getId())) {
                    out.add(d);
                    return out;
                }
            }
            return out;
        }
        if (docName == null || docName.isBlank()) {
            return out;
        }
        String want = docName.trim().toLowerCase(Locale.ROOT);
        for (KbDocument d : visible) {
            String n = d.getDocName() == null ? "" : d.getDocName().toLowerCase(Locale.ROOT);
            if (n.contains(want)) {
                out.add(d);
            }
        }
        // 片段没命中时退一步：拿问句里的词逐个试（模型常把整句塞进 docName）
        if (out.isEmpty() && want.length() > 6) {
            for (KbDocument d : visible) {
                String n = d.getDocName() == null ? "" : d.getDocName().toLowerCase(Locale.ROOT);
                for (String piece : want.split("[\\s，,。？?的]+")) {
                    if (piece.length() >= 2 && n.contains(piece)) {
                        out.add(d);
                        break;
                    }
                }
            }
        }
        return out;
    }

    /** 视同空白的格子（成绩单的「补考」列大量是 —）。 */
    private static final java.util.Set<String> BLANK = java.util.Set.of("", "—", "-", "/", "无", "null", "NULL");

    /**
     * 找出「整列都是数」的列：只有这种列才适合求和/求平均。
     *
     * <p>口径故意保守 —— 一列里只要有一格是「优/良/—」之外的文字就不算数值列，
     * 否则「学分」这种真数值列会因为个别脏格被整列丢掉。</p>
     */
    private static List<Integer> numericColumns(MarkdownTable.Table t) {
        List<Integer> out = new ArrayList<>();
        for (int c = 0; c < t.columns().size(); c++) {
            int filled = 0;
            boolean allNum = true;
            for (List<String> row : t.rows()) {
                String v = c < row.size() ? row.get(c).trim() : "";
                if (BLANK.contains(v)) {
                    continue;
                }
                filled++;
                if (!isNumber(v)) {
                    allNum = false;
                    break;
                }
            }
            if (allNum && filled > 0) {
                out.add(c);
            }
        }
        return out;
    }

    private static boolean isNumber(String v) {
        try {
            Double.parseDouble(v);
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private static Double number(List<String> row, int col) {
        String v = col < row.size() ? row.get(col).trim() : "";
        if (BLANK.contains(v)) {
            return null;
        }
        try {
            return Double.valueOf(v);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 保留 3 位小数：134.0 不会变成 134.00000000000003。 */
    private static double round(double v) {
        return Math.round(v * 1000.0) / 1000.0;
    }

    /** {@code 列名=值} → {@code [列名, 值]}；格式不对返回 null（视为不过滤）。 */
    private static String[] splitFilter(String filter) {
        if (filter == null || filter.isBlank()) {
            return null;
        }
        int i = filter.indexOf('=');
        if (i <= 0 || i == filter.length() - 1) {
            return null;
        }
        String col = filter.substring(0, i).trim();
        String val = filter.substring(i + 1).trim();
        return col.isEmpty() || val.isEmpty() ? null : new String[]{col, val};
    }

    private static int clamp(Integer valueLimit) {
        if (valueLimit == null) {
            return DEFAULT_VALUE_LIMIT;
        }
        return Math.max(1, Math.min(MAX_VALUE_LIMIT, valueLimit));
    }

    /** 找不到文档时给出可选项 —— 让模型能自我纠正，而不是回去猜。 */
    private String noDocError(List<KbDocument> visible, String docName, Long docId) {
        String head = docId != null ? "找不到 id=" + docId + " 的资料"
                : "找不到名为「" + (docName == null ? "" : docName) + "」的资料";
        if (visible.isEmpty()) {
            return head + "；当前用户的可见知识库里没有任何资料";
        }
        List<String> names = visible.stream().limit(MAX_CANDIDATES)
                .map(KbDocument::getDocName).toList();
        return head + "。可选资料：" + String.join("、", names)
                + (visible.size() > MAX_CANDIDATES ? " 等 " + visible.size() + " 份" : "");
    }

    private static Map<String, Object> fail(String error) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", false);
        out.put("error", error);
        return out;
    }
}
