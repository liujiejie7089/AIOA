package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.integration.scfy.tools.ScfyArgs;
import cn.aioa.integration.scfy.tools.ScfyToolSupport;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * 端到端只读矩阵 —— 对契约中<b>全部</b>可用接口逐个发出真实请求并落一份报告。
 *
 * <p><b>为什么必须有这个测试</b>：契约级单测只能证明「每个工具都指向了一个契约条目」，
 * 证明不了「这些接口在生产上真的能返回数据」。此前只对少数几个点做过真实调用，
 * 其余是否可用从来没有证据 —— 而工具清单对外宣称的是「全部可用」。不写死数字：
 * 接口数会随废弃/新增变动，断言只认「矩阵行数 == 契约可用接口数」这个关系式。
 * 只要其中一个在生产上 500，这份清单就是虚报。所以覆盖数本身要成为断言：
 * {@code 探到的接口数 == 契约可用接口数}。</p>
 *
 * <p><b>为什么它默认不跑</b>：它会出网、依赖外部系统可用性，不该拖进每次构建。
 * 用 {@code -Dscfy.matrix=true} 显式开启（与 {@code ScfySmokeTest} 同一口径）。</p>
 *
 * <p><b>为什么它不断言「全绿」</b>：被接入系统的生产缺陷（如 {@code relation "t_shop" does not exist}）
 * 不是本模块能修的。矩阵的职责是<b>把真相取回来并落成报告</b>，
 * 让「哪些可用 / 哪些不可用 / 是谁的问题」有据可查；
 * 断言只落在确定性事实（覆盖完整、参数名与契约一致）上 —— 不为转绿而放宽。</p>
 *
 * <p>全程只发 GET，不产生任何写操作。</p>
 */
class ScfyMatrixTest {

    /** 报告落点：优先取 -Dscfy.report=<绝对路径>，否则落到仓库 docs/_incoming/。 */
    private static final String REPORT_PROP = "scfy.report";

    private static ScfyToolSupport support;
    /** 本次矩阵实际打的目标环境，会写进报告头部。 */
    private static String targetBaseUrl;

    @BeforeAll
    static void setUp() {
        assumeTrue(Boolean.getBoolean("scfy.matrix"),
                "未开启矩阵：加 -Dscfy.matrix=true 才真实出网调用");
        ScfyIntegrationProperties props = new ScfyIntegrationProperties();
        props.setEnabled(true);
        props.setVerifySsl(true);
        // 默认打生产（唯一长期可用的环境）；要打本地后台测试服务就加
        // -Dscfy.baseUrl=http://127.0.0.1:16060/scfy
        String override = System.getProperty("scfy.baseUrl");
        if (override != null && !override.isBlank()) {
            props.setBaseUrl(override);
        }
        targetBaseUrl = props.getBaseUrl();
        ScfyClient client = new ScfyClient(props, new ObjectMapper());
        support = new ScfyToolSupport(client, new ScfyParamValidator());
    }

    // ==================== 主流程 ====================

    @Test
    @DisplayName("矩阵：全部可用接口真实调用 + 覆盖完整断言 + 落报告")
    void runMatrix() throws IOException {
        Map<String, String> ids = discover();

        List<Row> rows = new ArrayList<>();
        for (ScfyEndpoint ep : ScfyCatalog.available()) {
            rows.add(probe(ep, ids));
        }

        assertSelfCheck(rows, ids);
        writeReport(rows, ids);
        printMachine(rows);

        assertEquals(ScfyCatalog.availableCount(), rows.size(),
                "矩阵行数必须等于契约可用接口数 —— 少一个就是有一个接口从未被验证过");

        long fail = rows.stream().filter(r -> r.status().startsWith("FAIL")).count();
        System.out.println("[scfy-matrix] 覆盖=" + rows.size()
                + " 有数据=" + rows.stream().filter(r -> r.status().equals("OK_DATA")).count()
                + " 空集=" + rows.stream().filter(r -> r.status().equals("OK_EMPTY")).count()
                + " 失败=" + fail);
    }

    // ==================== 依赖 id 的发现阶段 ====================

    /**
     * 发现阶段：详情类接口需要「真实 id」，而契约里不能写死生产 id（会过期）。
     * 因此先从列表接口取一条真实数据，再用它的 id 去调详情 ——
     * 这正是编排层将来要做的事，先在这里跑通。
     */
    private Map<String, String> discover() {
        Map<String, String> ids = new LinkedHashMap<>();
        ids.put("INH_ID", dig(call("inheritor_list_by_area", ScfyArgs.of("area", "成都市", "pageSize", 5)),
                "dataList", "id"));
        ids.put("PROJ_ID", dig(call("project_list_by_area", ScfyArgs.of("pageSize", 5)),
                "dataList", "project_base_id"));
        ids.put("SHOP_ID", dig(call("shop_table", ScfyArgs.of("cityName", "成都市")), "list", "id"));
        ids.put("TRAVEL_ID", dig(call("travel_route_top_list", ScfyArgs.of("topNum", 10)),
                "routesTopFewList", "travel_id"));
        ids.put("ECO_ID", dig(call("eco_area_top_list", ScfyArgs.of("topNum", 10)),
                "areasTopFewList", "ecologicalarea_id"));
        ids.put("CITY_CODE", dig(call("travel_nmch_base", Map.of()), "nmchBaseDataList", "city_code"));
        ids.put("COUNTY_CODE", dig(call("eco_tourist_county_list", Map.of()), "touristCounty", "id"));
        // 线路资源详情的 dataId 必须取自列表：实测传 1（不存在的 id）返回空对象、不报错，
        // 那种「空」很容易被误读成「这条线路没有资源」。
        ids.put("ROAD_DATA_ID", dig(call("travel_road_by_type",
                ScfyArgs.of("type", "1", "travelId", ids.get("TRAVEL_ID"))), "dataList", "project_base_id"));
        System.out.println("[scfy-matrix] 发现到的依赖 id = " + ids);
        return ids;
    }

    /** 从 {@code data.<listField>[0].<idField>} 取一个真实 id。 */
    @SuppressWarnings("unchecked")
    private static String dig(Map<String, Object> result, String listField, String idField) {
        if (result == null || !Boolean.TRUE.equals(result.get("ok"))) {
            return null;
        }
        Object data = result.get("data");
        if (!(data instanceof Map<?, ?> m)) {
            return null;
        }
        Object list = ((Map<String, Object>) m).get(listField);
        if (!(list instanceof List<?> l) || l.isEmpty()) {
            return null;
        }
        Object first = l.get(0);
        if (!(first instanceof Map<?, ?> fm)) {
            return null;
        }
        Object v = ((Map<String, Object>) fm).get(idField);
        return v == null ? null : String.valueOf(v);
    }

    // ==================== 参数装配 ====================

    /**
     * 每个接口的调用参数。<b>显式列举</b>，不用「按参数名猜值」的兜底：
     * 同一个参数名 {@code id} 在传承人/项目/工坊三处指的是三种不同的 id，
     * 按名猜值必然串味，而串味后的 500 会被误判成「对方系统有缺陷」。
     */
    private Map<String, Object> paramsFor(String endpointId, Map<String, String> ids) {
        return switch (endpointId) {
            // ---- 传承人 ----
            case "inheritor_list_by_area" -> ScfyArgs.of("area", "成都市", "pageSize", 5);
            case "inheritor_detail" -> ScfyArgs.of("id", ids.get("INH_ID"));
            case "inheritor_type_data", "inheritor_gender_data", "inheritor_birthday_data",
                 "inheritor_education_data" -> ScfyArgs.of("level", "country");
            case "inheritor_count_by_area" -> Map.of();
            case "inheritor_yhwd_data" -> Map.of();
            case "inheritor_video" -> ScfyArgs.of("inheritorId", ids.get("INH_ID"));

            // ---- 项目 ----
            case "project_list_by_area" -> ScfyArgs.of("pageSize", 5);
            case "project_detail" -> ScfyArgs.of("id", ids.get("PROJ_ID"));
            case "project_type_data" -> ScfyArgs.of("level", "country");
            case "project_batch_data" -> ScfyArgs.of("area", "成都市");
            case "project_count_by_area" -> ScfyArgs.of("area", "成都市");
            case "project_area_summary" -> Map.of();
            case "project_yhwd_data" -> Map.of();
            case "project_video" -> ScfyArgs.of("projectBaseId", ids.get("PROJ_ID"));

            // ---- 工坊 ----
            case "shop_table", "shop_pie_and_stores", "shop_category_sum", "shop_bar_chart",
                 "shop_area_map_chart", "shop_address_distribution" -> ScfyArgs.of("cityName", "成都市");
            case "shop_map_chart", "shop_sales_and_amount" ->
                    ScfyArgs.of("cityName", "成都市", "areaName", "锦江区");
            case "shop_detail", "shop_inheritor", "shop_sales", "shop_project_type_pie",
                 "shop_sales_num_pie" -> ScfyArgs.of("cityName", "成都市", "id", ids.get("SHOP_ID"));

            // ---- 保护区 ----
            case "eco_area_count" -> Map.of();
            case "eco_area_top_list" -> ScfyArgs.of("topNum", 10);
            case "eco_city_round" -> ScfyArgs.of("ecologicalAreaId", ids.get("ECO_ID"));
            case "eco_road_data" ->
                    ScfyArgs.of("ecologicalAreaId", ids.get("ECO_ID"), "areaId", ids.get("CITY_CODE"));
            case "eco_road_distribute" ->
                    ScfyArgs.of("ecologicalAreaId", ids.get("ECO_ID"), "areaId", ids.get("CITY_CODE"));
            case "eco_area_image" -> ScfyArgs.of("ecologicalAreaId", ids.get("ECO_ID"),
                    "areaId", ids.get("CITY_CODE"), "type", "1", "dataId", "1");
            case "eco_all_image" -> ScfyArgs.of("ecologicalAreaId", ids.get("ECO_ID"));
            case "eco_details" -> ScfyArgs.of("type", "1", "dataId", "1");
            case "eco_nmch_base" -> Map.of();
            case "eco_nmch_popup" -> ScfyArgs.of("cityCode", ids.get("CITY_CODE"));
            case "eco_tourist_county_list" -> Map.of();
            case "eco_tourist_county_data" -> ScfyArgs.of("area", ids.get("COUNTY_CODE"));

            // ---- 旅游 ----
            case "travel_route_top_list" -> ScfyArgs.of("topNum", 10);
            case "travel_city_round" -> ScfyArgs.of("travelId", ids.get("TRAVEL_ID"));
            case "travel_road_type_count" -> ScfyArgs.of("travelId", ids.get("TRAVEL_ID"));
            case "travel_road_by_type" -> ScfyArgs.of("type", "1", "travelId", ids.get("TRAVEL_ID"));
            case "travel_road_data" -> ScfyArgs.of("travelId", ids.get("TRAVEL_ID"));
            case "travel_road_detail" -> ScfyArgs.of("dataId", ids.get("ROAD_DATA_ID"), "type", "1");
            case "travel_road_distribute" -> ScfyArgs.of("travelId", ids.get("TRAVEL_ID"));
            case "travel_image" -> ScfyArgs.of("travelId", ids.get("TRAVEL_ID"), "type", "2");
            case "travel_all_image" -> ScfyArgs.of("travelId", ids.get("TRAVEL_ID"));
            case "travel_details" -> ScfyArgs.of("type", "1", "dataId", "1");
            case "travel_nmch_base" -> Map.of();
            case "travel_nmch_popup" -> ScfyArgs.of("cityCode", ids.get("CITY_CODE"));
            case "travel_tourist_county_list" -> Map.of();
            case "travel_tourist_county_data" -> ScfyArgs.of("area", ids.get("COUNTY_CODE"));

            default -> throw new IllegalStateException(
                    "接口「" + endpointId + "」没有矩阵参数 —— 新增契约条目必须同时补上矩阵用例，"
                            + "否则它就是一个「从未被验证过却已对外可用」的接口");
        };
    }

    // ==================== 自检 ====================

    /**
     * 确定性自检（不出网）。两件事：
     * <ol>
     *   <li><b>参数名与契约一致</b>：矩阵里写了契约中不存在的参数名，
     *       请求会被后端当未知参数忽略 —— 那是「静默失效」，比 500 更难发现；</li>
     *   <li><b>必填参数齐备</b>：漏了必填会拿到 {@code needUserInput}，
     *       那是矩阵自身没测到位，不是接口有问题。</li>
     * </ol>
     */
    private void assertSelfCheck(List<Row> rows, Map<String, String> ids) {
        for (Row r : rows) {
            ScfyEndpoint ep = ScfyCatalog.byId(r.endpointId());
            Set<String> declared = new LinkedHashSet<>();
            for (ScfyParam p : ep.params()) {
                declared.add(p.name());
            }
            for (String used : r.params().keySet()) {
                assertTrue(declared.contains(used),
                        "矩阵给 " + r.endpointId() + " 传了契约里没有的参数「" + used + "」");
            }
            if (Boolean.TRUE.equals(r.needUserInput())) {
                throw new AssertionError("矩阵未给 " + r.endpointId() + " 备齐必填参数，"
                        + "其必填项为 " + ep.requiredParamNames() + "，契约提示：" + r.askUser());
            }
            if (r.status().equals("SKIP_NO_ID")) {
                // 依赖 id 没发现出来 —— 必须暴露：这类跳过会让覆盖数「看起来是齐的」
                throw new AssertionError("矩阵因缺少依赖 id 跳过了 " + r.endpointId()
                        + "，本次发现的 id 为 " + ids);
            }
        }
        assertNotNull(ids.get("ECO_ID"), "应能从 eco_area_top_list 发现保护区 id");
        assertNotNull(ids.get("TRAVEL_ID"), "应能从 travel_route_top_list 发现线路 id");
        assertNotNull(ids.get("SHOP_ID"), "应能从 shop_table 发现工坊 id");
    }

    // ==================== 探测 ====================

    private Map<String, Object> call(String endpointId, Map<String, Object> params) {
        try {
            return support.call(endpointId, params);
        } catch (Exception e) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("ok", false);
            m.put("errors", List.of("异常：" + e));
            return m;
        }
    }

    private Row probe(ScfyEndpoint ep, Map<String, String> ids) {
        Map<String, Object> params = paramsFor(ep.id(), ids);
        Map<String, Object> res = call(ep.id(), params);

        boolean ok = Boolean.TRUE.equals(res.get("ok"));
        boolean needUser = Boolean.TRUE.equals(res.get("needUserInput"));
        Integer code = res.get("code") instanceof Number n ? n.intValue() : null;
        String err = res.get("errors") == null ? null : String.join("；", asStrings(res.get("errors")));

        String status;
        int leaves = 0;
        if (needUser) {
            status = "MISSING_REQUIRED";
        } else if (!ok) {
            status = "FAIL";
        } else {
            leaves = leaves(res.get("data"));
            status = leaves > 0 ? "OK_DATA" : "OK_EMPTY";
        }
        System.out.println("[scfy-matrix] " + status + "\t" + ep.id() + "\t" + ep.fullPath()
                + "\tcode=" + code + "\tleaves=" + leaves
                + (err == null ? "" : "\terr=" + err));

        return new Row(ep.id(), ep.group(), ep.fullPath(), new LinkedHashMap<>(params),
                status, code, leaves, err, needUser, String.valueOf(res.get("askUser")));
    }

    private static List<String> asStrings(Object o) {
        if (o instanceof List<?> l) {
            List<String> s = new ArrayList<>();
            for (Object x : l) {
                s.add(String.valueOf(x));
            }
            return s;
        }
        return o == null ? List.of() : List.of(String.valueOf(o));
    }

    /** 叶子值计数：{@code {list:[]}} → 0（空集但调用成功），{@code {country:"1",province:"6"}} → 2。 */
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

    // ==================== 报告 ====================

    private void printMachine(List<Row> rows) {
        for (Row r : rows) {
            System.out.println("MATRIX|" + r.endpointId() + "|" + r.status() + "|"
                    + r.code() + "|" + r.leaves() + "|" + (r.error() == null ? "" : r.error()));
        }
    }

    private void writeReport(List<Row> rows, Map<String, String> ids) throws IOException {
        Map<String, List<Row>> byGroup = new TreeMap<>();
        for (Row r : rows) {
            byGroup.computeIfAbsent(r.group(), k -> new ArrayList<>()).add(r);
        }
        StringBuilder sb = new StringBuilder();
        sb.append("# scfy 端到端只读矩阵报告（全 56 接口真实调用）\n\n");
        sb.append("> 生成方式：`server/aioa-integration-scfy` 的 `ScfyMatrixTest`，")
                .append("`mvn -pl aioa-integration-scfy test -Dtest=ScfyMatrixTest -Dscfy.matrix=true`。\n");
        sb.append("> 环境：`").append(targetBaseUrl)
                .append("`。只发 GET，无写操作。\n\n");
        sb.append("状态口径：`OK_DATA` 调用成功且返回非空 ｜ `OK_EMPTY` 调用成功但该筛选条件下无数据 ")
                .append("｜ `FAIL` 调用失败（含对方系统缺陷） ｜ `MISSING_REQUIRED` 矩阵参数没备齐（矩阵自身问题）\n\n");
        sb.append("发现的依赖 id：").append(ids).append("\n\n");

        sb.append("## 汇总\n\n");
        sb.append("| 分组 | 接口数 | 有数据 | 空集 | 失败 |\n|---|---|---|---|---|\n");
        for (Map.Entry<String, List<Row>> e : byGroup.entrySet()) {
            List<Row> g = e.getValue();
            sb.append("| ").append(e.getKey()).append(" | ").append(g.size())
                    .append(" | ").append(count(g, "OK_DATA"))
                    .append(" | ").append(count(g, "OK_EMPTY"))
                    .append(" | ").append(g.size() - count(g, "OK_DATA") - count(g, "OK_EMPTY"))
                    .append(" |\n");
        }
        sb.append("| **合计** | **").append(rows.size()).append("** | ")
                .append(count(rows, "OK_DATA")).append(" | ")
                .append(count(rows, "OK_EMPTY")).append(" | ")
                .append(rows.size() - count(rows, "OK_DATA") - count(rows, "OK_EMPTY"))
                .append(" |\n\n");

        for (Map.Entry<String, List<Row>> e : byGroup.entrySet()) {
            sb.append("## ").append(e.getKey()).append("\n\n");
            sb.append("| 契约 id | 路径 | 调用参数 | 结果 | code | 叶子值 | 说明 |\n|---|---|---|---|---|---|---|\n");
            for (Row r : e.getValue()) {
                sb.append("| `").append(r.endpointId()).append("` | `").append(r.path()).append("` | `")
                        .append(r.params()).append("` | ").append(r.status()).append(" | ")
                        .append(r.code() == null ? "" : r.code()).append(" | ")
                        .append(r.leaves()).append(" | ")
                        .append(oneLine(r.error())).append(" |\n");
            }
            sb.append('\n');
        }

        List<Row> fails = rows.stream().filter(r -> !r.status().startsWith("OK")).toList();
        sb.append("## 需要处理的失败项\n\n");
        if (fails.isEmpty()) {
            sb.append("无 —— 全部可用接口均调用成功。\n");
        } else {
            sb.append("| 契约 id | 路径 | 结果 | 原因 |\n|---|---|---|---|\n");
            for (Row r : fails) {
                sb.append("| `").append(r.endpointId()).append("` | `").append(r.path()).append("` | ")
                        .append(r.status()).append(" | ").append(oneLine(r.error())).append(" |\n");
            }
        }

        Path out = reportPath();
        Files.createDirectories(out.getParent());
        Files.writeString(out, sb.toString(), StandardCharsets.UTF_8);
        System.out.println("[scfy-matrix] 报告已写入 " + out.toAbsolutePath());
    }

    private static Path reportPath() {
        String explicit = System.getProperty(REPORT_PROP);
        if (explicit != null && !explicit.isBlank()) {
            return Path.of(explicit);
        }
        // 从模块目录向上找到含 docs/_incoming 的仓库根
        Path p = Path.of("").toAbsolutePath();
        for (int i = 0; i < 4 && p != null; i++, p = p.getParent()) {
            if (Files.isDirectory(p.resolve("docs/_incoming"))) {
                return p.resolve("docs/_incoming/非遗scfy-端到端矩阵报告.md");
            }
        }
        return Path.of("").toAbsolutePath().resolve("非遗scfy-端到端矩阵报告.md");
    }

    private static long count(List<Row> rows, String status) {
        return rows.stream().filter(r -> r.status().equals(status)).count();
    }

    private static String oneLine(String s) {
        if (s == null) {
            return "";
        }
        String t = s.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
        return t.length() > 220 ? t.substring(0, 220) + "…" : t;
    }

    /** 一行结果。 */
    private record Row(String endpointId, String group, String path, Map<String, Object> params,
                       String status, Integer code, int leaves, String error,
                       Boolean needUserInput, String askUser) {
    }
}
