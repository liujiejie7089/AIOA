package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.ScfyIntegrationProperties;
import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.tools.ScfyArgs;
import cn.aioa.integration.scfy.tools.ScfyToolSupport;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import cn.aioa.tool.sdk.LocalToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 端到端问答链路测试：<b>提问 → 匹配 → 抽参 → 调用 → 返回数据</b>。
 *
 * <p>全部离线。出网的那一跳用桩替换（{@code Stub*}），因为本测试要验证的是
 * <b>编排是否正确</b>（选对了接口、参数字段名对、拒绝不匹配的问题），
 * 而不是对方系统是否可用 —— 后者由 {@code ScfyMatrixTest} 负责，两者职责不重叠。</p>
 *
 * <p>「缺必填参数」那条路径<b>刻意用真实的校验器</b>（不是桩）：追问话术是真实逻辑
 * 产出的，桩出来的话术证明不了线上也会这么问。</p>
 */
class ScfyAgentServiceTest {

    private final ScfyAgentCatalog catalog = AgentTestSupport.catalog();
    private final ToolMatcher matcher = new LexicalToolMatcher();
    private final ScfyParamExtractor extractor = new ScfyParamExtractor();

    /** 只放桩的注册表：未打桩的接口调用会明确失败，不会悄悄去真实出网。 */
    private ScfyAgentService serviceWith(Object... stubs) {
        LocalToolRegistry registry = AgentTestSupport.registryWith(stubs);
        return new ScfyAgentService(catalog, matcher, extractor, registry, new ScfyParamValidator());
    }

    // ==================== 成功路径 ====================

    @Test
    @DisplayName("一句话直达数据：自动匹配接口、抽取参数、调用并返回结果")
    void askMatchesExtractsAndCalls() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());

        Map<String, Object> r = service.ask("成都有哪些非遗工坊");

        assertEquals(Boolean.TRUE, r.get("ok"), "应调用成功：" + r);
        assertEquals("scfy_shop_table", r.get("tool"));
        assertEquals("非遗工坊-查询列表", r.get("toolName"));
        assertTrue(String.valueOf(r.get("matchedBy")).contains("语义匹配"));
        assertNotNull(r.get("score"));
        assertFalse(String.valueOf(r.get("returns")).isBlank(), "应带上返回结构，便于模型取字段");

        @SuppressWarnings("unchecked")
        Map<String, Object> args = (Map<String, Object>) r.get("args");
        assertEquals("成都市", args.get("cityName"), "市州应抽取为简称");

        // 真正返回的数据来自桩，且参数确实透传到了工具方法里
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.get("data");
        assertEquals("蜀绣工坊", data.get("echoName"));
        assertEquals("成都市", data.get("echoArg"));
    }

    @Test
    @DisplayName("指定工具时跳过匹配，但参数仍然照抽")
    void pinnedToolStillExtractsParams() {
        ScfyAgentService service = serviceWith(new StubProjectDetailTool());

        Map<String, Object> r = service.ask("非遗项目 2-UN-1 的详情", "scfy_project_detail");

        assertEquals(Boolean.TRUE, r.get("ok"), "应调用成功：" + r);
        assertEquals("scfy_project_detail", r.get("tool"));
        assertEquals("指定工具", r.get("matchedBy"));
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.get("data");
        assertEquals("2-UN-1", data.get("echoArg"), "id 应原样传给工具");
    }

    // ==================== 失败与追问路径 ====================

    @Test
    @DisplayName("缺必填参数时如实追问，不猜参数、不硬调")
    void asksUserWhenRequiredParamMissing() {
        ScfyAgentService service = serviceWith(new StubEcoCityRoundTool());

        Map<String, Object> r = service.ask("生态保护区的地理边界长什么样", "scfy_eco_city_round");

        assertEquals(Boolean.FALSE, r.get("ok"), "缺必填参数不应算成功：" + r);
        assertEquals(Boolean.TRUE, r.get("needUserInput"), "应标记需要用户补充信息");
        String ask = String.valueOf(r.get("askUser"));
        assertTrue(ask.contains("保护区"), "追问话术应说清要什么，实际：" + ask);
        System.out.println("[agent-service] 追问话术：" + ask.replace("\n", " / "));
    }

    @Test
    @DisplayName("问题与本系统无关时明确说不匹配，并把可查范围告诉用户")
    void reportsNoMatchInsteadOfGuessing() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());

        Map<String, Object> r = service.ask("帮我订一张明天去北京的机票");

        assertEquals(Boolean.FALSE, r.get("ok"));
        assertEquals(Boolean.FALSE, r.get("matched"));
        String errors = String.valueOf(r.get("errors"));
        assertTrue(errors.contains("没有匹配到"), "应说明未匹配，实际：" + errors);
        assertTrue(errors.contains("传承人") && errors.contains("工坊"),
                "应列出可查询范围，实际：" + errors);
    }

    @Test
    @DisplayName("实测不返回数据的接口被挡在自动调用之外，并说明原因")
    void refusesInterfaceThatReturnsNoData() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());

        Map<String, Object> r = service.ask("体验基地数据", "scfy_eco_nmch_base");

        assertEquals(Boolean.FALSE, r.get("ok"));
        assertTrue(String.valueOf(r.get("errors")).contains("实测不返回数据"),
                "应说明被排除的原因，实际：" + r.get("errors"));
    }

    @Test
    @DisplayName("指定了不存在的工具时给出可行动的错误，而不是抛异常")
    void reportsUnknownTool() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());

        Map<String, Object> r = service.ask("随便问问", "scfy_not_exist");

        assertEquals(Boolean.FALSE, r.get("ok"));
        assertTrue(String.valueOf(r.get("errors")).contains("没有这个工具"));
        assertTrue(String.valueOf(r.get("errors")).contains("scfy_catalog"),
                "应指向清单工具，让调用方能自己纠正");
    }

    @Test
    @DisplayName("空问题不抛异常，返回可读提示")
    void handlesBlankQuestion() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());
        Map<String, Object> r = service.ask("   ");
        assertEquals(Boolean.FALSE, r.get("ok"));
        assertTrue(String.valueOf(r.get("errors")).contains("问题为空"));
    }

    // ==================== 清单 ====================

    @Test
    @DisplayName("清单返回每个接口的名称/用途/参数/返回结构，四要素可见")
    void catalogListExposesAllFourParts() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());

        Map<String, Object> all = service.catalogList(null, null);
        assertEquals(55, all.get("total"));
        assertEquals(54, all.get("autoMatchable"));
        assertEquals(1, all.get("excludedFromAutoMatch"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) all.get("items");
        assertEquals(55, items.size());
        for (Map<String, Object> item : items) {
            assertFalse(String.valueOf(item.get("name")).isBlank(), item + " 缺名称");
            assertFalse(String.valueOf(item.get("purpose")).isBlank(), item + " 缺用途");
            assertNotNull(item.get("inputSchema"), item + " 缺参数");
            assertFalse(String.valueOf(item.get("returns")).isBlank(), item + " 缺返回结构");
        }

        // 按分组与关键词过滤
        Map<String, Object> shopOnly = service.catalogList("工坊", null);
        assertEquals(13, shopOnly.get("matched"), "工坊域应有 13 个接口");
        Map<String, Object> filtered = service.catalogList(null, "销售额");
        assertTrue((Integer) filtered.get("matched") >= 1, "按「销售额」应能过滤到接口");
    }

    @Test
    @DisplayName("单个接口的详情包含参数明细与实测返回字段")
    void describeOneTool() {
        ScfyAgentService service = serviceWith(new StubShopTableTool());

        Map<String, Object> d = service.describe("scfy_project_count_by_area");
        assertEquals(Boolean.TRUE, d.get("ok"));
        assertTrue(String.valueOf(d.get("returns")).contains("level_name"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> params = (List<Map<String, Object>>) d.get("paramsDetail");
        assertFalse(params.isEmpty());
        assertEquals("area", params.get(0).get("name"));
        assertEquals(Boolean.TRUE, params.get(0).get("required"));

        Map<String, Object> missing = service.describe("scfy_nope");
        assertEquals(Boolean.FALSE, missing.get("ok"));
    }

    // ==================== 桩：替换出网那一跳 ====================

    /** 工坊列表桩：把收到的参数回显出来，便于断言「参数确实传到了工具里」。 */
    static class StubShopTableTool {
        @AioaTool(code = "scfy_shop_table", name = "非遗工坊-查询列表",
                description = "查询某市州的非遗工坊/店铺列表，回答「成都有哪些非遗工坊」。",
                domain = "scfy")
        public Map<String, Object> shopTable(
                @AioaToolParam(name = "cityName", description = "市州简称，如 成都市", required = false)
                String cityName) {
            return Map.of("ok", true, "data", Map.of(
                    "echoName", "蜀绣工坊",
                    "echoArg", cityName == null ? "" : cityName));
        }
    }

    /** 项目详情桩。 */
    static class StubProjectDetailTool {
        @AioaTool(code = "scfy_project_detail", name = "非遗项目-详情",
                description = "查询单个非遗项目的详情（项目名、级别、保护单位、传承谱系、简介）。",
                domain = "scfy")
        public Map<String, Object> detail(
                @AioaToolParam(name = "id", description = "项目 id", required = true) String id) {
            return Map.of("ok", true, "data", Map.of("echoArg", id == null ? "" : id));
        }
    }

    /** 保护区地理边界桩：<b>内部走真实校验器</b>，用于验证缺参追问是真逻辑产出的。 */
    static class StubEcoCityRoundTool {

        private final ScfyToolSupport support = new ScfyToolSupport(
                new ScfyClient(unroutable(), new ObjectMapper()), new ScfyParamValidator());

        @AioaTool(code = "scfy_eco_city_round", name = "生态保护区-地理边界",
                description = "查询文化生态保护区的地理边界坐标。",
                domain = "scfy")
        public Map<String, Object> cityRound(
                @AioaToolParam(name = "ecologicalAreaId", description = "保护区 id", required = true)
                String ecologicalAreaId) {
            return support.call("eco_city_round", ScfyArgs.of("ecologicalAreaId", ecologicalAreaId));
        }

        /** 指向一个必然连不通的地址：本桩只走「参数校验」这一段，不该发生真实请求。 */
        private static ScfyIntegrationProperties unroutable() {
            ScfyIntegrationProperties p = new ScfyIntegrationProperties();
            p.setEnabled(true);
            p.setBaseUrl("http://127.0.0.1:1/scfy");
            return p;
        }
    }
}
