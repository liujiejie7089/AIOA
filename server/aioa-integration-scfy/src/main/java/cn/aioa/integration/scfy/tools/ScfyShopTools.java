package cn.aioa.integration.scfy.tools;

import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 非遗工坊域工具（13 个，只读，来自免登录的 {@code /show/shop/*}）。
 *
 * <p><b>本域最重要的一个坑</b>：接口文档把「工坊 id」参数写成 {@code shopId}，
 * 实测后端要求的参数名是 <b>{@code id}</b> —— 传 {@code shopId} 会得到
 * {@code Required String parameter 'id' is not present}。
 * 如果模型照文档传，每一次调用都会失败；更糟的是若有人「顺手」在适配器里
 * 把 shopId 悄悄改名成 id 兜住，这个文档缺陷就被掩盖了，下一个人还会照着文档写。
 * 所以这里的选择是：<b>契约、工具参数、校验器三处统一用 id，并在描述里写明差异</b>。</p>
 *
 * <p>另有 8 个 {@code /show/data/*} 工坊接口（shopTypeScale / shopInfos / saleStat 等）
 * 在生产环境整组 500（{@code relation "t_shop" does not exist}），已整体废弃、不注册工具，
 * 原因登记在 {@code ScfyCatalog}。</p>
 */
@Component
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyShopTools {

    private final ScfyToolSupport support;

    public ScfyShopTools(ScfyToolSupport support) {
        this.support = support;
    }

    @AioaTool(code = "scfy_shop_table",
            name = "非遗工坊-查询列表",
            description = "查询某市州的非遗工坊/店铺列表（含店铺名、销量、所属平台、关联项目），"
                    + "回答「成都有哪些非遗工坊」「工坊经营情况」。市州必须用简称。"
                    + "返回 list（含 id，可用于查工坊详情）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> shopTable(
            @AioaToolParam(name = "cityName", description = "市州简称，如 成都市 / 甘孜州", required = true)
            String cityName) {
        return support.call("shop_table", ScfyArgs.of("cityName", cityName));
    }

    @AioaTool(code = "scfy_shop_pie_and_stores",
            name = "非遗工坊-数量与门类饼图",
            description = "查询某市州工坊总数与按项目门类的分布饼图。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> pieAndStores(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName) {
        return support.call("shop_pie_and_stores", ScfyArgs.of("cityName", cityName));
    }

    @AioaTool(code = "scfy_shop_category_sum",
            name = "非遗工坊-经营类别汇总",
            description = "查询某市州工坊的经营类别汇总（线上/线下销售额、老字号数量、各档传承人数量）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> categorySum(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName) {
        return support.call("shop_category_sum", ScfyArgs.of("cityName", cityName));
    }

    @AioaTool(code = "scfy_shop_bar_chart",
            name = "非遗工坊-平台销量",
            description = "查询某市州工坊在各电商平台的销量柱状图数据。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> barChart(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName) {
        return support.call("shop_bar_chart", ScfyArgs.of("cityName", cityName));
    }

    @AioaTool(code = "scfy_shop_map_chart",
            name = "非遗工坊-地图分布",
            description = "查询某市州（可下钻到区县）工坊的地图分布数据，含经纬度。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> mapChart(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "areaName", description = "区县名，可选，如 锦江区", required = false)
            String areaName) {
        return support.call("shop_map_chart", ScfyArgs.of("cityName", cityName, "areaName", areaName));
    }

    @AioaTool(code = "scfy_shop_area_map_chart",
            name = "非遗工坊-区域分布",
            description = "查询某市州工坊在区域维度的分布（type1/type2/type3 三组）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> areaMapChart(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName) {
        return support.call("shop_area_map_chart", ScfyArgs.of("cityName", cityName));
    }

    @AioaTool(code = "scfy_shop_sales_and_amount",
            name = "非遗工坊-销售额与销售量",
            description = "查询某市州（可限定区县）工坊的总销售额与销售量。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> salesAndAmount(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "areaName", description = "区县名，可选", required = false) String areaName) {
        return support.call("shop_sales_and_amount", ScfyArgs.of("cityName", cityName, "areaName", areaName));
    }

    @AioaTool(code = "scfy_shop_detail",
            name = "非遗工坊-详情",
            description = "查询单个工坊的详情（线上店铺、简介、关联传承人）。"
                    + "id 来自 scfy_shop_table 的 list[].id。"
                    + "注意本接口的参数名是 id，不是接口文档写的 shopId。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> shopDetail(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "id", description = "工坊 id，取自 scfy_shop_table 的 list[].id（文档误写为 shopId）",
                    required = true) String id) {
        return support.call("shop_detail", ScfyArgs.of("cityName", cityName, "id", id));
    }

    @AioaTool(code = "scfy_shop_inheritor",
            name = "非遗工坊-关联传承人",
            description = "查询某个工坊关联的传承人。参数名是 id（不是文档写的 shopId）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> shopInheritor(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "id", description = "工坊 id（文档误写为 shopId）", required = true) String id) {
        return support.call("shop_inheritor", ScfyArgs.of("cityName", cityName, "id", id));
    }

    @AioaTool(code = "scfy_shop_sales",
            name = "非遗工坊-销量",
            description = "查询某个工坊的销量明细（线上线下销售额与数量）。参数名是 id（不是文档写的 shopId）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> shopSales(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "id", description = "工坊 id（文档误写为 shopId）", required = true) String id) {
        return support.call("shop_sales", ScfyArgs.of("cityName", cityName, "id", id));
    }

    @AioaTool(code = "scfy_shop_project_type_pie",
            name = "非遗工坊-项目类型饼图",
            description = "查询某工坊的项目类型分布饼图。除市州外还必须提供 id —— "
                    + "接口文档只写了 cityName，漏标了 id（实测必填）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> projectTypePie(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "id", description = "工坊 id（文档漏标此必填参数）", required = true) String id) {
        return support.call("shop_project_type_pie", ScfyArgs.of("cityName", cityName, "id", id));
    }

    @AioaTool(code = "scfy_shop_sales_num_pie",
            name = "非遗工坊-平台销售饼图",
            description = "查询某工坊按平台的销售数量与销售额饼图。除市州外还必须提供 id —— "
                    + "接口文档漏标了该必填参数。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> salesNumPie(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName,
            @AioaToolParam(name = "id", description = "工坊 id（文档漏标此必填参数）", required = true) String id) {
        return support.call("shop_sales_num_pie", ScfyArgs.of("cityName", cityName, "id", id));
    }

    @AioaTool(code = "scfy_shop_address_distribution",
            name = "非遗工坊-地址分布",
            description = "查询某市州工坊的地址分布（含经纬度、行政区划层级）与账号层级统计。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> addressDistribution(
            @AioaToolParam(name = "cityName", description = "市州简称", required = true) String cityName) {
        return support.call("shop_address_distribution", ScfyArgs.of("cityName", cityName));
    }
}
