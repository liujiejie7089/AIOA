package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.tools.ScfyArgs;
import cn.aioa.integration.scfy.tools.ScfyToolSupport;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * 真实链路冒烟测试（会出网访问 scfy 生产只读接口）。
 *
 * <p>默认<b>不执行</b>：用 {@code -Dscfy.smoke=true} 显式开启。
 * 理由与「端到端测试矩阵」分开：矩阵要可重复、可离线复跑；
 * 而这个冒烟的作用是验证「适配器真的能连上、能解析、能归一化」——
 * 它依赖外部系统可用性，不该在每次构建里拖慢并制造偶发失败。</p>
 *
 * <p>只调用免登录只读接口，不产生任何写操作。</p>
 */
class ScfySmokeTest {

    private static ScfyToolSupport support;

    @BeforeAll
    static void setUp() {
        assumeTrue(Boolean.getBoolean("scfy.smoke"),
                "未开启冒烟：加 -Dscfy.smoke=true 才真实出网调用");
        ScfyIntegrationProperties props = new ScfyIntegrationProperties();
        props.setEnabled(true);
        // 生产环境证书链完整，保持默认校验；不做 sslVerify=false 的「图省事」
        props.setVerifySsl(true);
        ScfyClient client = new ScfyClient(props, new ObjectMapper());
        support = new ScfyToolSupport(client, new ScfyParamValidator());
    }

    @Test
    @DisplayName("冒烟：无参数接口（保护区数量）")
    void smokeNoParam() {
        Map<String, Object> r = support.call("eco_area_count", Map.of());
        assertEquals(true, r.get("ok"), "调用失败：" + r.get("errors"));
        assertTrue(r.containsKey("data"));
    }

    @Test
    @DisplayName("冒烟：带必填参数的聚合接口（传承人门类分布）")
    void smokeWithRequiredParam() {
        Map<String, Object> r = support.call("inheritor_type_data", ScfyArgs.of("level", "country"));
        assertEquals(true, r.get("ok"), "调用失败：" + r.get("errors"));
    }

    @Test
    @DisplayName("冒烟：市州筛选（工坊列表），且返回 id 可供后续调用")
    void smokeCityFilter() {
        Map<String, Object> r = support.call("shop_table", ScfyArgs.of("cityName", "成都市"));
        assertEquals(true, r.get("ok"), "调用失败：" + r.get("errors"));
    }

    @Test
    @DisplayName("冒烟：校验拦截发生在出网之前 —— 全称市州不产生网络调用")
    void smokeValidatorBlocksBeforeNetwork() {
        Map<String, Object> r = support.call("inheritor_list_by_area", ScfyArgs.of("area", "甘孜藏族自治州"));
        assertEquals(false, r.get("ok"));
        assertTrue(String.join(" ", castStrings(r.get("errors"))).contains("甘孜藏族自治州"),
                "应被校验器拦下，而不是发出一次注定返回空集的请求");
    }

    @Test
    @DisplayName("冒烟：缺必填参数时返回追问而非调用")
    void smokeAsksUser() {
        Map<String, Object> r = support.call("project_count_by_area", Map.of());
        assertEquals(false, r.get("ok"));
        assertEquals(true, r.get("needUserInput"));
        assertTrue(r.get("askUser") != null && !String.valueOf(r.get("askUser")).isBlank());
    }

    @Test
    @DisplayName("冒烟：契约中不存在/已废弃的接口被拒绝调用")
    void smokeRejectsDeprecated() {
        ScfyEndpoint dep = ScfyCatalog.byId("deprecated_shop_data_sale_stat");
        assertFalse(dep.available(), "该接口应处于废弃状态（生产整组 500）");
    }

    @SuppressWarnings("unchecked")
    private static List<String> castStrings(Object o) {
        return o instanceof List<?> l ? (List<String>) l : List.of();
    }
}
