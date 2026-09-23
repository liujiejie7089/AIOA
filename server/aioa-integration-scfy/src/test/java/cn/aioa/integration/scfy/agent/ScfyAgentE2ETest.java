package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.ScfyIntegrationProperties;
import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.tools.ScfyEcologyTools;
import cn.aioa.integration.scfy.tools.ScfyInheritorTools;
import cn.aioa.integration.scfy.tools.ScfyProjectTools;
import cn.aioa.integration.scfy.tools.ScfyShopTools;
import cn.aioa.integration.scfy.tools.ScfyToolSupport;
import cn.aioa.integration.scfy.tools.ScfyTravelTools;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import cn.aioa.tool.sdk.LocalToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * 端到端链路验证：<b>真实出网</b>跑「提问 → 匹配 → 抽参 → 调用 → 拿到数据」。
 *
 * <p>与 {@code ScfyAgentServiceTest} 的分工：那个用桩验证<b>编排正确性</b>（离线、每次都跑）；
 * 这个验证<b>这条链路对真实系统确实能拿到数据</b>（出网、默认不跑）。
 * 两者都不能省：只有桩会漏掉「参数名对但对方不认」这类问题，
 * 只有真实调用则每次构建都依赖外部系统可用性。</p>
 *
 * <p>开启方式：{@code -Dscfy.agent=true}（可配合 {@code -Dscfy.baseUrl=} 换环境）。
 * 全程只发 GET，无写操作。</p>
 */
class ScfyAgentE2ETest {

    private static ScfyAgentService service;
    private static String target;

    @BeforeAll
    static void setUp() {
        assumeTrue(Boolean.getBoolean("scfy.agent"),
                "未开启 agent 端到端：加 -Dscfy.agent=true 才真实出网调用");

        ScfyIntegrationProperties props = new ScfyIntegrationProperties();
        props.setEnabled(true);
        props.setVerifySsl(true);
        String override = System.getProperty("scfy.baseUrl");
        if (override != null && !override.isBlank()) {
            props.setBaseUrl(override);
        }
        target = props.getBaseUrl();

        ScfyClient client = new ScfyClient(props, new ObjectMapper());
        ScfyToolSupport support = new ScfyToolSupport(client, new ScfyParamValidator());
        // 用真实 support 装配工具 Bean，走与生产完全一致的扫描与注册路径
        LocalToolRegistry registry = AgentTestSupport.registryWith(
                new ScfyInheritorTools(support),
                new ScfyProjectTools(support),
                new ScfyShopTools(support),
                new ScfyEcologyTools(support),
                new ScfyTravelTools(support));
        ScfyAgentCatalog catalog = ScfyAgentCatalog.load(registry, new ObjectMapper());
        service = new ScfyAgentService(catalog, new LexicalToolMatcher(),
                new ScfyParamExtractor(), registry, new ScfyParamValidator());
        System.out.println("[agent-e2e] 环境=" + target + " 注册接口=" + catalog.size()
                + " 可直接匹配=" + catalog.registered().size());
    }

    /** 期望：这句话应命中该接口，且真的能拿回非空数据。 */
    private record Case(String question, String expectTool) {
    }

    private static final List<Case> CASES = List.of(
            new Case("成都有哪些非遗工坊", "scfy_shop_table"),
            new Case("甘孜州有多少非遗项目", "scfy_project_count_by_area"),
            new Case("四川有哪些文化生态保护区", "scfy_eco_area_top_list"),
            new Case("非遗旅游线路有哪些", "scfy_travel_route_top_list"),
            new Case("国家级非遗项目的门类分布是怎样的", "scfy_project_type_data"),
            new Case("国家级非遗传承人的性别比例", "scfy_inheritor_gender_data")
    );

    @Test
    @DisplayName("真实提问全链路：匹配到预期接口，并返回非空数据")
    void realQuestionsReturnRealData() {
        List<String> failures = new ArrayList<>();
        for (Case c : CASES) {
            Map<String, Object> r = service.ask(c.question());
            String tool = String.valueOf(r.get("tool"));
            boolean ok = Boolean.TRUE.equals(r.get("ok"));
            int leaves = leaves(r.get("data"));
            System.out.println("[agent-e2e] 「" + c.question() + "」 tool=" + tool
                    + " ok=" + ok + " leaves=" + leaves
                    + " args=" + r.get("args")
                    + (ok ? "" : " errors=" + r.get("errors")));

            if (!c.expectTool().equals(tool)) {
                failures.add("「" + c.question() + "」期望 " + c.expectTool() + "，实际 " + tool);
            } else if (!ok) {
                failures.add("「" + c.question() + "」调用了 " + tool + " 但失败：" + r.get("errors"));
            } else if (leaves == 0) {
                failures.add("「" + c.question() + "」调用了 " + tool + " 却返回空数据 —— "
                        + "说明参数抽取有问题（对方对错参数不报错，只返回空）");
            }
        }
        assertTrue(failures.isEmpty(), "端到端未达预期：\n  - " + String.join("\n  - ", failures));
    }

    @Test
    @DisplayName("从用户提问到数据的完整结果里，可追溯信息齐全")
    void resultCarriesTraceabilityInfo() {
        Map<String, Object> r = service.ask("成都有哪些非遗工坊");

        assertEquals(Boolean.TRUE, r.get("ok"), "应成功：" + r);
        assertNotNull(r.get("question"), "应回显问题");
        assertNotNull(r.get("matcher"), "应说明匹配器实现");
        assertNotNull(r.get("matchedBy"), "应说明匹配方式");
        assertNotNull(r.get("score"), "应给出相关度分数");
        assertNotNull(r.get("matchReasons"), "应说明为什么命中");
        assertNotNull(r.get("endpoint"), "应给出契约接口 id");
        assertNotNull(r.get("returns"), "应给出返回结构");
        assertNotNull(r.get("args"), "应给出实际调用参数");
        assertNotNull(r.get("argEvidence"), "应给出参数抽取依据");
    }

    private static int leaves(Object o) {
        if (o == null) {
            return 0;
        }
        if (o instanceof Map<?, ?> m) {
            int s = 0;
            for (Object v : m.values()) {
                s += leaves(v);
            }
            return s;
        }
        if (o instanceof List<?> l) {
            int s = 0;
            for (Object v : l) {
                s += leaves(v);
            }
            return s;
        }
        return 1;
    }
}
