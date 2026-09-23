package cn.aioa.integration.scfy.agent;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 参数抽取的规则钉死。
 *
 * <p>这一层的错误后果最严重：scfy 对错误参数<b>不报错</b>，只返回空结果。
 * 所以每条规则都要有正例（该抽到）与反例（不该抽到也不能硬凑）。</p>
 */
class ScfyParamExtractorTest {

    private final ScfyParamExtractor extractor = new ScfyParamExtractor();
    private final ScfyAgentCatalog catalog = AgentTestSupport.catalog();

    private ScfyToolDescriptor tool(String endpointId) {
        ScfyToolDescriptor d = catalog.byEndpointId(endpointId);
        assertNotNull(d, "契约里应有 " + endpointId);
        return d;
    }

    // ==================== 市州名归一化 ====================

    @Test
    @DisplayName("官方长名必须归一化成实测可用的简称 —— 长名会静默返回 0 条")
    void normalisesOfficialLongCityNames() {
        assertEquals("甘孜州", ScfyParamExtractor.city("甘孜藏族自治州有哪些非遗项目"));
        assertEquals("阿坝州", ScfyParamExtractor.city("阿坝藏族羌族自治州的项目"));
        assertEquals("凉山州", ScfyParamExtractor.city("凉山彝族自治州有多少传承人"));
    }

    @Test
    @DisplayName("简称与省略后缀口语写法都能识别")
    void recognisesShortAndColloquialCityNames() {
        assertEquals("成都市", ScfyParamExtractor.city("成都有哪些非遗工坊"));
        assertEquals("甘孜州", ScfyParamExtractor.city("甘孜州有多少非遗项目"));
        assertEquals("凉山州", ScfyParamExtractor.city("凉山非遗项目"));
        assertNull(ScfyParamExtractor.city("四川省非遗项目总量"));
        assertNull(ScfyParamExtractor.city("国家级非遗项目有多少"));
    }

    // ==================== 等级 ====================

    @Test
    @DisplayName("等级说法映射到契约枚举；不认孤立的「省」「市」以免与地名相撞")
    void mapsLevelWords() {
        assertEquals("country", ScfyParamExtractor.levelWord("国家级非遗项目有多少"));
        assertEquals("un", ScfyParamExtractor.levelWord("联合国级的非遗项目"));
        assertEquals("un", ScfyParamExtractor.levelWord("列入联合国教科文组织名录的项目"));
        assertEquals("province", ScfyParamExtractor.levelWord("省级非遗项目数量"));
        assertEquals("county", ScfyParamExtractor.levelWord("县级非遗项目"));
        // 孤立的一个「市」字不能当等级，否则「成都市非遗」会被当成 level=city
        assertNull(ScfyParamExtractor.levelWord("成都市非遗项目"));
    }

    // ==================== 12 位行政区划编码 ====================

    @Test
    @DisplayName("行政区划编码类参数只认 12 位编码，名称一律不抽（名称会静默返回全零）")
    void areaCodeRequiresTwelveDigits() {
        ScfyToolDescriptor county = tool("eco_tourist_county_data");
        ScfyParamExtractor.Extraction ok = extractor.extract("青羊区 510105000000 的非遗资源", county);
        assertEquals("510105000000", ok.args().get("area"));

        ScfyParamExtractor.Extraction nameOnly = extractor.extract("青羊区的非遗资源", county);
        assertFalse(nameOnly.args().containsKey("area"),
                "只给名称时不能抽——传名称实测返回全零且不报错，必须转成向用户追问");
    }

    // ==================== 数量与分页 ====================

    @Test
    @DisplayName("条数 / 页码 / 前 N 条分别落到 pageSize / pageNum / topNum，并夹到合法区间")
    void extractsNumericParams() {
        ScfyToolDescriptor list = tool("project_list_by_area");
        assertEquals(30, extractor.extract("查前30条非遗项目", list).args().get("pageSize"));
        assertEquals(2, extractor.extract("非遗项目列表第2页", list).args().get("pageNum"));
        // 上限 100：超出要被夹住，不能把 999 直接透给后端
        assertEquals(100, extractor.extract("查前999条非遗项目", list).args().get("pageSize"));

        ScfyToolDescriptor top = tool("travel_route_top_list");
        assertEquals(5, extractor.extract("最热门的5条非遗旅游线路", top).args().get("topNum"));
    }

    // ==================== id 类 ====================

    @Test
    @DisplayName("项目编码 / UUID / 带后缀的传承人 id 都能抽到，且不改写原值")
    void extractsIdsVerbatim() {
        ScfyToolDescriptor detail = tool("project_detail");
        assertEquals("2-UN-1", extractor.extract("非遗项目 2-UN-1 的详情", detail).args().get("id"));

        ScfyToolDescriptor video = tool("inheritor_video");
        String uuidWithSuffix = "6df60302-f201-4fee-8758-e93d0e4c3112_country";
        assertEquals(uuidWithSuffix,
                extractor.extract("传承人 " + uuidWithSuffix + " 的视频地址", video).args().get("inheritorId"),
                "id 必须原样传递：截掉 _country 后缀会拿到另一条记录或空结果");

        ScfyToolDescriptor shopDetail = tool("shop_detail");
        assertEquals("140", extractor.extract("成都市工坊 id=140 的详情", shopDetail).args().get("id"));
    }

    @Test
    @DisplayName("不会把年份、条数之类的数字误当成 id")
    void doesNotMistakeNumbersForIds() {
        ScfyToolDescriptor detail = tool("project_detail");
        assertFalse(extractor.extract("2023 年新增的非遗项目详情", detail).args().containsKey("id"),
                "2023 是年份，不是 id");
        assertFalse(extractor.extract("前 10 条非遗项目的详情", detail).args().containsKey("id"),
                "10 是条数，不是 id");
    }

    // ==================== 区县名 ====================

    @Test
    @DisplayName("区县名只落在 areaName 参数上，不会被当成市州")
    void extractsDistrictForAreaName() {
        ScfyToolDescriptor shopMap = tool("shop_map_chart");
        Map<String, Object> args = extractor.extract("成都市锦江区的工坊分布", shopMap).args();
        assertEquals("成都市", args.get("cityName"));
        assertEquals("锦江区", args.get("areaName"));
    }

    @Test
    @DisplayName("抽不到就留空：不猜默认值（猜错会静默返回空结果）")
    void leavesUnmentionnedParamsAbsent() {
        ScfyToolDescriptor county = tool("eco_tourist_county_data");
        ScfyParamExtractor.Extraction ex = extractor.extract("这个县的非遗资源怎么样", county);
        assertTrue(ex.args().isEmpty(), "没给编码就不能编一个出来，实际：" + ex.args());

        ScfyToolDescriptor detail = tool("project_detail");
        assertTrue(extractor.extract("某个非遗项目的详情", detail).args().isEmpty());
    }
}
