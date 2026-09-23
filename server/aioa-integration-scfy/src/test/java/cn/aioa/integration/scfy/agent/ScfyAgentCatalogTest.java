package cn.aioa.integration.scfy.agent;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 注册表自检：注册项的「名称 / 用途 / 参数 / 返回结构」是否真的齐备。
 *
 * <p>这些断言存在的意义：注册表是本功能对 agent 的承诺。少一项就是一次
 * 「模型不知道该怎么用」的运行时故障，而它不会以异常形式出现 ——
 * 只会表现为答案不好。所以必须在构建期钉死。</p>
 */
class ScfyAgentCatalogTest {

    @Test
    @DisplayName("注册表覆盖契约全部可用接口，且排除恒空接口时的理由是明确的")
    void coversAllAvailableEndpoints() {
        ScfyAgentCatalog catalog = AgentTestSupport.catalog();

        assertEquals(55, catalog.size(), "契约里 55 个可用接口都应出现在注册表里");
        assertEquals(54, catalog.registered().size(),
                "可直接自动调用的应为 54 个（排除 1 个实测恒空接口）");
        assertEquals(1, catalog.excluded().size(), "应恰好排除 1 个接口");
        assertEquals("eco_nmch_base", catalog.excluded().get(0).endpointId(),
                "被排除的应是实测恒空的 eco_nmch_base；若换成别的接口，说明返回结构采集或契约变了");
        assertTrue(catalog.dangling().isEmpty(),
                "不应有工具指向契约外/已废弃接口：" + catalog.dangling());
        assertTrue(catalog.toolMissing().isEmpty(),
                "契约可用接口不应有缺工具的：" + catalog.toolMissing());
    }

    @Test
    @DisplayName("每个注册项的四要素齐备：名称 / 用途 / 参数 / 返回结构")
    void everyDescriptorIsComplete() {
        ScfyAgentCatalog catalog = AgentTestSupport.catalog();

        Map<String, List<String>> incomplete = catalog.incompleteness();
        assertTrue(incomplete.isEmpty(), "注册项四要素不齐备，不能对外注册：" + incomplete);

        for (ScfyToolDescriptor d : catalog.all()) {
            assertFalse(d.name() == null || d.name().isBlank(), d.toolCode() + " 缺名称");
            assertFalse(d.purpose() == null || d.purpose().isBlank(), d.toolCode() + " 缺用途描述");
            assertNotNull(d.inputSchema(), d.toolCode() + " 缺入参 Schema");
            assertTrue(d.hasReturnStructure(), d.toolCode() + " 缺返回结构（observed=" + d.observed() + "）");
            assertTrue(d.toolCode().startsWith("scfy_"), d.toolCode() + " 编码前缀应为 scfy_");
            assertNotNull(d.path(), d.toolCode() + " 缺接口路径");
            assertNotNull(d.group(), d.toolCode() + " 缺分组");
        }
    }

    @Test
    @DisplayName("返回结构来自实测：抽查已知接口的字段名与真实响应一致")
    void returnStructureComesFromRealObservation() {
        ScfyAgentCatalog catalog = AgentTestSupport.catalog();

        ScfyToolDescriptor count = catalog.byEndpointId("project_count_by_area");
        assertNotNull(count);
        assertEquals("OK_DATA", count.observed(), "该接口在矩阵中实测返回数据");
        assertTrue(count.returnsText().contains("level_name"),
                "返回结构应含实测字段 level_name，实际：" + count.returnsText());
        assertTrue(count.returnsText().contains("num"),
                "返回结构应含实测字段 num，实际：" + count.returnsText());

        ScfyToolDescriptor list = catalog.byEndpointId("project_list_by_area");
        assertNotNull(list);
        assertTrue(list.returnsText().contains("dataList"),
                "列表接口的返回结构应含 dataList，实际：" + list.returnsText());
        assertTrue(list.returnsText().contains("project_base_id"),
                "列表接口的元素字段应含 project_base_id（详情查询要用它），实际：" + list.returnsText());

        // 恒空接口不得凭空编出返回结构 —— 只声明「观测到的那个空数组字段」
        ScfyToolDescriptor empty = catalog.byEndpointId("eco_nmch_base");
        assertNotNull(empty);
        assertFalse(empty.returnsData(), "恒空接口不应被标记为返回数据");
        assertTrue(empty.returnsText().contains("nmchBaseDataList") || empty.returnsText().contains("未观测到"),
                "恒空接口的返回结构只能如实反映实测，实际：" + empty.returnsText());
    }

    @Test
    @DisplayName("检索文本包含返回字段名 —— 用户按结果字段提问时才能命中")
    void searchTextIncludesFieldNames() {
        ScfyAgentCatalog catalog = AgentTestSupport.catalog();
        ScfyToolDescriptor shopTable = catalog.byEndpointId("shop_table");
        assertNotNull(shopTable);
        assertTrue(shopTable.searchText().contains("subject_name"),
                "检索文本应含实测字段 subject_name（工坊名），否则按字段提问命中不了");
        assertTrue(shopTable.searchText().contains("sales"),
                "检索文本应含实测字段 sales（销售额）");
    }

    @Test
    @DisplayName("返回结构采集来源被记录，便于追溯是哪一次实测")
    void shapeMetaIsRecorded() {
        ScfyAgentCatalog catalog = AgentTestSupport.catalog();
        assertNotNull(catalog.shapeMeta().get("generatedFrom"), "应记录采集环境");
        assertNotNull(catalog.shapeMeta().get("coverage"), "应记录采集覆盖数");
        assertEquals(55, ((Number) catalog.shapeMeta().get("coverage")).intValue());
    }
}
