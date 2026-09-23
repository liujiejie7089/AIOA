package cn.aioa.integration.scfy.tools;

import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 文化生态保护区域工具（12 个，只读，来自免登录的 {@code /show/ecologicalArea/*}）。
 *
 * <p>本域的调用链是「先拿 id、再查详情」：{@code eco_area_top_list} 给出
 * {@code ecologicalarea_id}，{@code eco_tourist_county_list} 给出合法的 {@code areaId}
 * （形如 510100000000）。工具描述里写清这两条依赖，模型才不会臆造 id。</p>
 *
 * <p>另有 {@code /getPagerTravelImageUrl} 已废弃：实测只返回分页器对象、
 * 没有任何数据列表字段，调用方拿不到图片。原因登记在 {@code ScfyCatalog}。</p>
 */
@Component
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyEcologyTools {

    private final ScfyToolSupport support;

    public ScfyEcologyTools(ScfyToolSupport support) {
        this.support = support;
    }

    @AioaTool(code = "scfy_eco_area_count",
            name = "生态保护区-数量",
            description = "查询四川省文化生态保护区数量，按国家级与省级分别返回，回答「四川有几个文化生态保护区」。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> areaCount() {
        return support.call("eco_area_count", Map.of());
    }

    @AioaTool(code = "scfy_eco_area_top_list",
            name = "生态保护区-列表",
            description = "查询文化生态保护区列表（名称、级别、经纬度、简介），回答「有哪些保护区」「最大的保护区」。"
                    + "返回 areasTopFewList，其中的 ecologicalarea_id 是后续所有保护区接口的入参。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> areaTopList(
            @AioaToolParam(name = "topNum", description = "返回条数；不传返回全部", required = false, type = "integer")
            Integer topNum) {
        return support.call("eco_area_top_list", ScfyArgs.of("topNum", topNum));
    }

    @AioaTool(code = "scfy_eco_city_round",
            name = "生态保护区-地理边界",
            description = "查询某个保护区的地理边界坐标（用于地图描边）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> cityRound(
            @AioaToolParam(name = "ecologicalAreaId",
                    description = "保护区 id，取自 scfy_eco_area_top_list 的 areasTopFewList[].ecologicalarea_id",
                    required = true) String ecologicalAreaId) {
        return support.call("eco_city_round", ScfyArgs.of("ecologicalAreaId", ecologicalAreaId));
    }

    @AioaTool(code = "scfy_eco_road_data",
            name = "生态保护区-资源分页数据",
            description = "查询保护区内项目 / 集聚区 / 体验基地的分页数据。areaId 是城市编码（形如 510100000000），"
                    + "可从 scfy_eco_tourist_county_list 或 scfy_travel_nmch_base 获得，不要臆造。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadData(
            @AioaToolParam(name = "ecologicalAreaId", description = "保护区 id", required = true) String ecologicalAreaId,
            @AioaToolParam(name = "areaId", description = "城市编码，如 510100000000", required = true) String areaId,
            @AioaToolParam(name = "pageNum", description = "页码，缺省 1", required = false, type = "integer")
            Integer pageNum,
            @AioaToolParam(name = "pageSize", description = "每页条数，缺省 10", required = false, type = "integer")
            Integer pageSize) {
        return support.call("eco_road_data",
                ScfyArgs.of("ecologicalAreaId", ecologicalAreaId, "areaId", areaId,
                        "pageNum", pageNum, "pageSize", pageSize));
    }

    @AioaTool(code = "scfy_eco_road_distribute",
            name = "生态保护区-资源分布统计",
            description = "查询保护区内资源的分布统计（项目 / 集聚区 / 体验基地三组）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadDistribute(
            @AioaToolParam(name = "ecologicalAreaId", description = "保护区 id", required = true) String ecologicalAreaId,
            @AioaToolParam(name = "areaId", description = "城市编码，如 510100000000", required = true) String areaId) {
        return support.call("eco_road_distribute", ScfyArgs.of("ecologicalAreaId", ecologicalAreaId, "areaId", areaId));
    }

    // 原 scfy_eco_area_image（/getEcologicalAreaImageUrl）已废弃：
    // type 取值语义未明确且错配即 500，无法给模型可靠的取值指引。
    // 图片需求由 scfy_eco_all_image 与 scfy_eco_details 覆盖。废弃原因见 ScfyCatalog。

    @AioaTool(code = "scfy_eco_all_image",
            name = "生态保护区-全部图片",
            description = "查询某个保护区的全部图片（实测用真实 id 可返回非空 imageList）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> allImage(
            @AioaToolParam(name = "ecologicalAreaId", description = "保护区 id", required = true) String ecologicalAreaId) {
        return support.call("eco_all_image", ScfyArgs.of("ecologicalAreaId", ecologicalAreaId));
    }

    @AioaTool(code = "scfy_eco_details",
            name = "生态保护区-数据详情",
            description = "查询保护区内某条数据的详情（名称、类型、地址、简介、图片）。"
                    + "type 实测只有 1 与 5 返回数据、2/3/4 返回空对象；dataId 传不存在的值同样返回空对象。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> details(
            @AioaToolParam(name = "type", description = "对象类型编码，实测 1（或用 5）能取到数据", required = true) String type,
            @AioaToolParam(name = "dataId", description = "对象 id", required = true) String dataId) {
        return support.call("eco_details", ScfyArgs.of("type", type, "dataId", dataId));
    }

    @AioaTool(code = "scfy_eco_nmch_base",
            name = "生态保护区-体验基地列表",
            description = "查询非遗体验基地列表（保护区口径）。注意实测该口径常为空，"
                    + "要更全的体验基地列表请用 scfy_travel_nmch_base（实测返回 21 条）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> nmchBase() {
        return support.call("eco_nmch_base", Map.of());
    }

    @AioaTool(code = "scfy_eco_nmch_popup",
            name = "生态保护区-体验基地详情",
            description = "查询非遗体验基地的弹窗详情（简介、产品）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> nmchPopup(
            @AioaToolParam(name = "cityCode", description = "城市编码，如 510100000000", required = true) String cityCode) {
        return support.call("eco_nmch_popup", ScfyArgs.of("cityCode", cityCode));
    }

    @AioaTool(code = "scfy_eco_tourist_county_list",
            name = "生态保护区-旅游重点县列表",
            description = "查询非遗旅游重点县列表（含名称与经纬度）。这是获取合法城市编码 areaId 的入口之一。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> touristCountyList() {
        return support.call("eco_tourist_county_list", Map.of());
    }

    @AioaTool(code = "scfy_eco_tourist_county_data",
            name = "生态保护区-县域非遗资源",
            description = "查询某个县/市州的非遗资源汇总（代表性传承人、非遗项目、名录项目）。"
                    + "area 是 12 位行政区划编码（如 510105000000=青羊区），不是县名 —— 传名称会返回全零。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> touristCountyData(
            @AioaToolParam(name = "area", description = "12 位行政区划编码，如 510105000000（青羊区）；可从 scfy_eco_tourist_county_list 取得", required = false) String area) {
        return support.call("eco_tourist_county_data", ScfyArgs.of("area", area));
    }
}
