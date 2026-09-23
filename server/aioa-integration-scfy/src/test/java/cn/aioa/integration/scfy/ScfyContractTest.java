package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 契约与工具声明的一致性测试 —— 取代「靠人记得两处同步」。
 *
 * <p>{@code @AioaTool} 是编译期注解，无法引用运行时的 {@link ScfyCatalog}，
 * 所以「接口清单」和「工具参数」必然存在两份文本。既然无法消除重复，
 * 就让<b>不一致直接测试失败</b>：这比在两边都写注释提醒可靠。</p>
 */
class ScfyContractTest {

    private static final List<Class<?>> TOOL_CLASSES = List.of(
            cn.aioa.integration.scfy.tools.ScfyInheritorTools.class,
            cn.aioa.integration.scfy.tools.ScfyProjectTools.class,
            cn.aioa.integration.scfy.tools.ScfyShopTools.class,
            cn.aioa.integration.scfy.tools.ScfyEcologyTools.class,
            cn.aioa.integration.scfy.tools.ScfyTravelTools.class);

    @Test
    @DisplayName("契约完整性：id 唯一、可用/废弃互斥、必填参数有说明")
    void catalogIsWellFormed() {
        Set<String> ids = new LinkedHashSet<>();
        for (ScfyEndpoint ep : ScfyCatalog.all()) {
            assertTrue(ids.add(ep.id()), "接口 id 重复：" + ep.id());
            assertNotNull(ep.summary(), ep.id() + " 缺少 summary");
            assertFalse(ep.summary().isBlank(), ep.id() + " 的 summary 为空");
            if (ep.available()) {
                for (ScfyParam p : ep.params()) {
                    assertNotNull(p.description(), ep.id() + "." + p.name() + " 缺少 description");
                    assertFalse(p.description().isBlank(), ep.id() + "." + p.name() + " 说明为空");
                    if (p.hasEnums() && p.example() != null) {
                        assertTrue(p.enums().contains(p.example()) || p.name().equals("area")
                                        || p.name().equals("cityName"),
                                ep.id() + "." + p.name() + " 的 example 不在枚举内：" + p.example());
                    }
                }
            } else {
                assertTrue(ep.note() != null && !ep.note().isBlank(),
                        "废弃接口必须写明原因，否则下一个人会重新踩：" + ep.id());
                assertTrue(ep.params().isEmpty(), "废弃接口不应携带参数契约：" + ep.id());
            }
        }
        // 数字与调试文档一一对应：56 可用 + 11 废弃 = 67（全量探测数）
        assertEquals(56, ScfyCatalog.availableCount(), "可用接口数应与实测通过的接口数一致");
        assertEquals(11, ScfyCatalog.deprecated().size(), "废弃接口数应与实测废弃清单一致");
        assertEquals(67, ScfyCatalog.all().size(), "契约总数应等于全量探测的 67 个接口");
    }

    @Test
    @DisplayName("工具声明与契约一致：code 可映射、参数名与必填性完全对齐")
    void toolsMatchCatalog() {
        List<String> problems = new ArrayList<>();

        for (Class<?> clazz : TOOL_CLASSES) {
            for (Method m : clazz.getDeclaredMethods()) {
                AioaTool tool = m.getAnnotation(AioaTool.class);
                if (tool == null) {
                    continue;
                }
                assertTrue(tool.code().startsWith(ScfyAutoConfiguration.TOOL_PREFIX),
                        tool.code() + " 未使用 scfy_ 前缀，一致性对账会漏掉它");
                String endpointId = tool.code().substring(ScfyAutoConfiguration.TOOL_PREFIX.length());
                ScfyEndpoint ep = ScfyCatalog.byId(endpointId);
                if (ep == null) {
                    problems.add(tool.code() + " → 契约中不存在该接口");
                    continue;
                }
                if (!ep.available()) {
                    problems.add(tool.code() + " → 指向已废弃接口");
                    continue;
                }

                // 注解声明的参数（名 → 是否必填）应与契约逐项一致
                Map<String, Boolean> annotated = new LinkedHashMap<>();
                for (Parameter p : m.getParameters()) {
                    AioaToolParam ap = p.getAnnotation(AioaToolParam.class);
                    if (ap != null) {
                        annotated.put(ap.name(), ap.required());
                    }
                }
                Map<String, Boolean> contractual = new LinkedHashMap<>();
                for (ScfyParam p : ep.params()) {
                    contractual.put(p.name(), p.required());
                }
                if (!annotated.equals(contractual)) {
                    problems.add(tool.code() + " 参数不一致：\n      注解=" + annotated
                            + "\n      契约=" + contractual);
                }
            }
        }

        assertTrue(problems.isEmpty(), "工具与契约已漂移：\n  - " + String.join("\n  - ", problems));
    }

    @Test
    @DisplayName("契约覆盖完整：每个可用接口都有且仅有一个工具")
    void everyAvailableEndpointHasExactlyOneTool() {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Class<?> clazz : TOOL_CLASSES) {
            for (Method m : clazz.getDeclaredMethods()) {
                AioaTool tool = m.getAnnotation(AioaTool.class);
                if (tool != null) {
                    counts.merge(tool.code(), 1, Integer::sum);
                }
            }
        }
        Set<String> missing = new TreeSet<>();
        for (ScfyEndpoint ep : ScfyCatalog.available()) {
            String code = ScfyAutoConfiguration.TOOL_PREFIX + ep.id();
            Integer n = counts.get(code);
            if (n == null) {
                missing.add(ep.id() + "（" + ep.group() + "）");
            } else {
                assertEquals(1, n, code + " 被声明了多次");
            }
        }
        assertTrue(missing.isEmpty(), "以下可用接口没有对应工具：" + String.join(", ", missing));
    }

    @Test
    @DisplayName("实测校正已固化：参数名/必填/警示三处都能查到依据")
    void correctionsAreRecorded() {
        // 文档写 shopId、实测是 id —— 契约必须是 id，且注明差异
        ScfyEndpoint shopDetail = ScfyCatalog.byId("shop_detail");
        assertNotNull(shopDetail.param("id"), "shop_detail 的参数必须是实测确认的 id");
        assertTrue(shopDetail.param("id").docNote().contains("shopId"),
                "shop_detail 必须记录「文档写 shopId」这一差异");

        // 文档漏标 travelId 必填
        assertTrue(ScfyCatalog.byId("travel_road_type_count").param("travelId").required(),
                "travel_road_type_count 的 travelId 必须标为必填（文档漏标）");
        assertTrue(ScfyCatalog.byId("travel_road_distribute").param("travelId").required(),
                "travel_road_distribute 的 travelId 必须标为必填（文档漏标）");

        // 市州必须用简称：枚举只含简称，不含全称
        ScfyParam area = ScfyCatalog.byId("inheritor_list_by_area").param("area");
        assertTrue(area.enums().contains("甘孜州"), "市州枚举应含简称「甘孜州」");
        assertFalse(area.enums().contains("甘孜藏族自治州"),
                "市州枚举不应含全称 —— 实测全称返回 0 条");

        // level 的静默失效必须记录在案
        assertTrue(ScfyCatalog.byId("project_list_by_area").param("level").docNote().contains("忽略"),
                "project_list_by_area 的 level 必须记录「实测被忽略」");
    }
}
