package cn.aios.resource.service;

import cn.aios.resource.entity.KbDocument;
import cn.aios.resource.store.KbRelationalDao;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 表格取行的**分页**（docs/76）。
 *
 * <p>回归的是「62 门课只返回 14 门 / 10 门」：原实现回给模型的命中行硬上限 10 行，
 * 且没有 offset 参数 —— 枚举类问题结构上取不全，模型只能答一部分（或者老实说
 * 「接口只返回前 10 行」）。现在按 limit 翻页，并用 hasMore / nextOffset 明确告知还有没有下一页。</p>
 */
class KbTableQueryPagingTest {

    private static final int ROWS = 62;

    private KbTableQueryService service;

    @BeforeEach
    void setUp() {
        KbRelationalDao dao = mock(KbRelationalDao.class);
        when(dao.listVisible(anyLong(), anyLong())).thenReturn(List.of(doc()));
        service = new KbTableQueryService(dao);
    }

    private static KbDocument doc() {
        KbDocument d = new KbDocument();
        d.setId(249L);
        d.setTenantId(56L);
        d.setUserId(3240L);
        d.setDocName("成绩单.pdf");
        StringBuilder sb = new StringBuilder("### 成绩明细\n")
                .append("| 课程名称 | 课程性质 | 学分 | 成绩 |\n")
                .append("| --- | --- | --- | --- |\n");
        for (int i = 1; i <= ROWS; i++) {
            sb.append("| 课程").append(i).append(" | 学基必修 | 3.0 | ").append(60 + i % 40).append(" |\n");
        }
        d.setContent(sb.toString());
        return d;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> data(Map<String, Object> res) {
        assertEquals(Boolean.TRUE, res.get("ok"), "调用必须成功：" + res);
        return (Map<String, Object>) res.get("data");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, String>> rows(Map<String, Object> d) {
        return (List<Map<String, String>>) d.get("rows");
    }

    @Test
    @DisplayName("默认一页 50 行：62 门时返回 50 行，并明确告知还有 12 行")
    void defaultPageReturnsFiftyRows() {
        Map<String, Object> d = data(service.query(56L, 3240L, "成绩单", null, null, null, null));
        assertEquals(ROWS, ((Number) d.get("matchedRows")).intValue());
        assertEquals(50, rows(d).size(), "默认每页 50 行");
        assertEquals(50, ((Number) d.get("returned")).intValue());
        assertEquals(Boolean.TRUE, d.get("hasMore"), "还有 12 行 ⇒ hasMore 必须为 true");
        assertEquals(50, ((Number) d.get("nextOffset")).intValue());
        assertTrue(String.valueOf(d.get("nextHint")).contains("12"), "提示剩余行数：" + d.get("nextHint"));
    }

    @Test
    @DisplayName("翻页取第二页：拿到剩下 12 行，hasMore=false（能取全 62 行）")
    void secondPageCompletesTheList() {
        Map<String, Object> d = data(service.query(56L, 3240L, "成绩单", null, null, null, null, 50, 50));
        List<Map<String, String>> page2 = rows(d);
        assertEquals(12, page2.size());
        assertEquals("课程51", page2.get(0).get("课程名称"), "第二页必须从第 51 行开始");
        assertEquals("课程62", page2.get(11).get("课程名称"));
        assertEquals(Boolean.FALSE, d.get("hasMore"));
        // 两页拼起来 = 不丢不重
        Map<String, Object> p1 = data(service.query(56L, 3240L, "成绩单", null, null, null, null, 0, 50));
        java.util.Set<String> names = new java.util.HashSet<>();
        rows(p1).forEach(r -> names.add(r.get("课程名称")));
        page2.forEach(r -> names.add(r.get("课程名称")));
        assertEquals(ROWS, names.size(), "两页合计应覆盖全部 62 门，不重不漏");
    }

    @Test
    @DisplayName("一次取全：limit 上限 500 生效，62 行一页给完")
    void singleCallCanReturnAll() {
        Map<String, Object> d = data(service.query(56L, 3240L, "成绩单", null, null, null, null, 0, 500));
        assertEquals(ROWS, rows(d).size());
        assertEquals(Boolean.FALSE, d.get("hasMore"));
    }

    @Test
    @DisplayName("过滤 + 分页共存：按性质过滤后仍能翻页")
    void filterAndPagingCompose() {
        Map<String, Object> d = data(service.query(56L, 3240L, "成绩单", null, null,
                "课程性质=学基必修", null, 10, 10));
        assertEquals(ROWS, ((Number) d.get("matchedRows")).intValue());
        assertEquals(10, rows(d).size(), "第二页 10 行");
        assertEquals("课程11", rows(d).get(0).get("课程名称"));
    }

    @Test
    @DisplayName("分页不改聚合：numeric / groups 始终是全量口径")
    void aggregatesStayGlobalAcrossPages() {
        Map<String, Object> d = data(service.query(56L, 3240L, "成绩单", null, "课程性质", null, null, 10, 5));
        assertEquals(5, rows(d).size(), "本页只 5 行");
        assertEquals(ROWS, ((Number) d.get("matchedRows")).intValue(), "但总数仍是 62");
        @SuppressWarnings("unchecked")
        Map<String, Object> credit = (Map<String, Object>) ((Map<String, Object>) d.get("numeric")).get("学分");
        assertEquals(186.0, ((Number) credit.get("sum")).doubleValue(), 1e-6, "62 × 3.0");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> groups = (List<Map<String, Object>>) d.get("groups");
        assertEquals(ROWS, ((Number) groups.get(0).get("count")).intValue(), "分组计数不受分页影响");
    }

    @Test
    @DisplayName("offset 越界：不给行、不报错，hasMore=false")
    void offsetBeyondEndIsEmpty() {
        Map<String, Object> d = data(service.query(56L, 3240L, "成绩单", null, null, null, null, 999, 50));
        assertTrue(rows(d) == null || rows(d).isEmpty());
        assertEquals(Boolean.FALSE, d.get("hasMore"));
        assertFalse(d.containsKey("nextOffset"));
    }

    // ---------- 多表资料：62 门课不能被汇总表的 14 行「注水」成 76 ----------

    private static KbTableQueryService serviceWithBothTables() {
        KbDocument d = doc();
        d.setContent(d.getContent() + "\n### 成绩汇总\n| 项目 | 数值 |\n| --- | --- |\n"
                + "| 历年平均成绩 | 80.26 |\n"
                + "| 历年平均学分绩点 | 2.69 |\n"
                + "| 已获得总学分 | 134.0 |\n");
        KbRelationalDao dao = mock(KbRelationalDao.class);
        when(dao.listVisible(anyLong(), anyLong())).thenReturn(List.of(d));
        return new KbTableQueryService(dao);
    }

    @Test
    @DisplayName("多表：默认选命中行最多的「成绩明细」，行数就是 62（不是 62+3）")
    void defaultsToLargestSheet() {
        KbTableQueryService svc = serviceWithBothTables();
        Map<String, Object> d = data(svc.query(56L, 3240L, "成绩单", null, null, null, null));
        assertEquals("成绩明细", d.get("sheet"));
        assertEquals(ROWS, ((Number) d.get("matchedRows")).intValue(), "只数明细表，不把汇总行混进来");
        // B2：totalRows 必须是**所选表**的物理行数。跨表求和会给出 65，
        // 模型拿它跟 matchedRows=62 一比就得出「还有 3 行没取」⇒ 又变成数字对不上。
        assertEquals(ROWS, ((Number) d.get("totalRows")).intValue(), "totalRows 与所选表一致");
        assertTrue(String.valueOf(d.get("otherSheets")).contains("成绩汇总"), "要告知还有别的表");
        // 全资料各表行数不丢：在 docs 里逐表给出（成绩汇总 3 行仍可见）
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> docs = (List<Map<String, Object>>) d.get("docs");
        assertEquals(2, docs.size(), "两张表都要列出来：" + docs);
        Map<String, Object> sum = docs.stream()
                .filter(m -> "成绩汇总".equals(m.get("sheet"))).findFirst().orElseThrow();
        assertEquals(3, ((Number) sum.get("rows")).intValue(), "汇总表行数仍在 docs 里");
    }

    @Test
    @DisplayName("B1 守卫：过滤后命中很少也要受 MAX_SCAN_ROWS 约束（计扫描行，不计命中行）")
    void scanGuardCountsScannedRowsNotHits() {
        KbTableQueryService svc = new KbTableQueryService(mockDaoFor(doc()));
        svc.scanRowGuardForTest(10);   // 62 行的表，守卫 10 ⇒ 必然触发
        // 关键：过滤条件只命中 1 行。老实现拿命中序号当守卫，扫描 62 行也只会到 1，守卫失效。
        Map<String, Object> res = svc.query(56L, 3240L, "成绩单", null, null,
                "课程名称=课程1", null, 0, 50);
        assertEquals(Boolean.FALSE, res.get("ok"), "扫描行数超阈值必须拦下：" + res);
        assertTrue(String.valueOf(res.get("error")).contains("表格过大"), String.valueOf(res.get("error")));
    }

    private static KbRelationalDao mockDaoFor(KbDocument d) {
        KbRelationalDao dao = mock(KbRelationalDao.class);
        when(dao.listVisible(anyLong(), anyLong())).thenReturn(List.of(d));
        return dao;
    }

    @Test
    @DisplayName("多表：传 sheet 能切到汇总表，列变成「项目/数值」")
    void canSwitchToSummarySheet() {
        KbTableQueryService svc = serviceWithBothTables();
        Map<String, Object> d = data(svc.query(56L, 3240L, "成绩单", null, null, null, null, 0, 50, "成绩汇总"));
        assertEquals("成绩汇总", d.get("sheet"));
        assertEquals(3, ((Number) d.get("matchedRows")).intValue());
        assertEquals(List.of("项目", "数值"), d.get("columns"));
        assertTrue(rows(d).get(1).containsValue("2.69"), "汇总行要带回数值：" + rows(d).get(1));
    }

    @Test
    @DisplayName("多表：按汇总表的列过滤时自动选中汇总表（该列只有它有）")
    void filterPicksSheetThatHasTheColumn() {
        KbTableQueryService svc = serviceWithBothTables();
        Map<String, Object> d = data(svc.query(56L, 3240L, "成绩单", null, null,
                "项目=历年平均学分绩点", null));
        assertEquals("成绩汇总", d.get("sheet"));
        assertEquals(1, ((Number) d.get("matchedRows")).intValue());
        assertTrue(rows(d).get(0).containsValue("2.69"));
    }

    @Test
    @DisplayName("多表：sheet 写错时给出可选表名（可自我纠正）")
    void unknownSheetGivesCandidates() {
        KbTableQueryService svc = serviceWithBothTables();
        Map<String, Object> res = svc.query(56L, 3240L, "成绩单", null, null, null, null, 0, 10, "不存在的表");
        assertEquals(Boolean.FALSE, res.get("ok"));
        assertTrue(String.valueOf(res.get("error")).contains("可用表"), String.valueOf(res.get("error")));
    }
}
