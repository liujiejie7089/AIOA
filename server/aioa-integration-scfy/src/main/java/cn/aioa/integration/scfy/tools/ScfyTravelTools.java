package cn.aioa.integration.scfy.tools;

import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 非遗旅游线路域工具（14 个，只读，来自免登录的 {@code /show/travel/*}）。
 *
 * <p><b>本域集中暴露了接口文档的「漏标必填」缺陷</b>：文档把
 * {@code getTravelRoadTypeCount}、{@code getTravelRoadDistributeData} 的必填参数标成
 * 「—」（即无需参数），把 {@code getTravelRoadDataByType} 只标了 {@code type}。
 * 实测这三个接口<b>都必填 {@code travelId}</b>，不传直接报
 * {@code Required String parameter 'travelId' is not present}。</p>
 *
 * <p>这里没有「文档说不用传、那我也标成可选然后让后端报错」这种写法：
 * 必填性以实测为准写进契约与注解，模型在调用前就能被校验器拦住，
 * 而不是等到后端返回错误才重试一轮。</p>
 */
@Component
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyTravelTools {

    private final ScfyToolSupport support;

    public ScfyTravelTools(ScfyToolSupport support) {
        this.support = support;
    }

    @AioaTool(code = "scfy_travel_route_top_list",
            name = "非遗旅游线路-列表",
            description = "查询非遗旅游线路列表（线路名、封面图），回答「有哪些非遗旅游线路」「热门线路」。"
                    + "返回 routesTopFewList，其中的 travel_id 是后续线路类接口的入参。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> routeTopList(
            @AioaToolParam(name = "topNum", description = "返回条数；不传返回全部", required = false, type = "integer")
            Integer topNum) {
        return support.call("travel_route_top_list", ScfyArgs.of("topNum", topNum));
    }

    @AioaTool(code = "scfy_travel_city_round",
            name = "非遗旅游线路-地理边界",
            description = "查询某条旅游线路的地理边界坐标与中心点。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> cityRound(
            @AioaToolParam(name = "travelId",
                    description = "线路 id，取自 scfy_travel_route_top_list 的 routesTopFewList[].travel_id",
                    required = true) String travelId) {
        return support.call("travel_city_round", ScfyArgs.of("travelId", travelId));
    }

    @AioaTool(code = "scfy_travel_road_type_count",
            name = "非遗旅游线路-沿线资源统计",
            description = "查询某条线路沿线的资源类型数量统计（非遗项目 / 区域 / 基地）。"
                    + "注意：接口文档标注本接口「无需必填参数」，实测 travelId 必填。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadTypeCount(
            @AioaToolParam(name = "travelId", description = "线路 id（文档漏标此为必填）", required = true)
            String travelId) {
        return support.call("travel_road_type_count", ScfyArgs.of("travelId", travelId));
    }

    @AioaTool(code = "scfy_travel_road_by_type",
            name = "非遗旅游线路-按类型查资源",
            description = "查询某条线路下指定类型的资源分页列表。"
                    + "注意：文档只标了 type，实测还必须提供 travelId。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadByType(
            @AioaToolParam(name = "type", description = "资源类型编码", required = true) String type,
            @AioaToolParam(name = "travelId", description = "线路 id（文档漏标此为必填）", required = true)
            String travelId) {
        return support.call("travel_road_by_type", ScfyArgs.of("type", type, "travelId", travelId));
    }

    @AioaTool(code = "scfy_travel_road_data",
            name = "非遗旅游线路-完整资源",
            description = "查询某条线路的完整资源分页数据（非遗项目 / 集聚区 / 体验基地三组）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadData(
            @AioaToolParam(name = "travelId", description = "线路 id", required = true) String travelId,
            @AioaToolParam(name = "areaId", description = "城市编码，可选，如 510100000000", required = false)
            String areaId,
            @AioaToolParam(name = "pageNum", description = "页码，缺省 1", required = false, type = "integer")
            Integer pageNum,
            @AioaToolParam(name = "pageSize", description = "每页条数，缺省 10", required = false, type = "integer")
            Integer pageSize) {
        return support.call("travel_road_data",
                ScfyArgs.of("travelId", travelId, "areaId", areaId, "pageNum", pageNum, "pageSize", pageSize));
    }

    @AioaTool(code = "scfy_travel_road_detail",
            name = "非遗旅游线路-资源详情",
            description = "查询线路中某条资源的详情（简介、图片、路线）。"
                    + "dataId 要传 scfy_travel_road_by_type 返回的 project_base_id —— "
                    + "传不存在的 id 会返回空对象而不报错；type 实测被忽略。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadDetail(
            @AioaToolParam(name = "dataId", description = "资源 id，取自 scfy_travel_road_by_type 的 dataList[].project_base_id", required = true) String dataId,
            @AioaToolParam(name = "type", description = "资源类型编码，实测 1/2/3/4 返回同一份详情", required = true) String type) {
        return support.call("travel_road_detail", ScfyArgs.of("dataId", dataId, "type", type));
    }

    @AioaTool(code = "scfy_travel_road_distribute",
            name = "非遗旅游线路-资源分布",
            description = "查询某条线路的资源分布统计。"
                    + "注意：接口文档标注本接口「无需必填参数」，实测 travelId 必填。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> roadDistribute(
            @AioaToolParam(name = "travelId", description = "线路 id（文档漏标此为必填）", required = true)
            String travelId) {
        return support.call("travel_road_distribute", ScfyArgs.of("travelId", travelId));
    }

    @AioaTool(code = "scfy_travel_image",
            name = "非遗旅游线路-图片",
            description = "查询某条线路下某一类对象的图片（含图片名）。type 实质必填：2=项目图片、3=体验基地图片；"
                    + "不传或传其他值会返回空列表而不报错。要该线路全部图片也可用 scfy_travel_all_image。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> image(
            @AioaToolParam(name = "travelId", description = "线路 id", required = true) String travelId,
            @AioaToolParam(name = "type", description = "图片对象类型：2=项目图片、3=体验基地图片", required = true) String type) {
        return support.call("travel_image", ScfyArgs.of("travelId", travelId, "type", type));
    }

    @AioaTool(code = "scfy_travel_all_image",
            name = "非遗旅游线路-全部图片",
            description = "查询某条线路的全部图片（实测可返回非空 imageList）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> allImage(
            @AioaToolParam(name = "travelId", description = "线路 id", required = true) String travelId) {
        return support.call("travel_all_image", ScfyArgs.of("travelId", travelId));
    }

    @AioaTool(code = "scfy_travel_details",
            name = "非遗旅游线路-数据详情",
            description = "查询线路中某条数据的详情。type 实测 1 与 5 有数据、2/3/4 返回空对象。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> details(
            @AioaToolParam(name = "type", description = "对象类型编码，实测 1（或用 5）能取到数据", required = true) String type,
            @AioaToolParam(name = "dataId", description = "对象 id", required = true) String dataId) {
        return support.call("travel_details", ScfyArgs.of("type", type, "dataId", dataId));
    }

    @AioaTool(code = "scfy_travel_nmch_base",
            name = "非遗旅游线路-体验基地列表",
            description = "查询非遗体验基地列表（旅游口径，实测 21 条，比保护区口径更全）。"
                    + "返回项含 city_code，可作为 areaId 使用。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> nmchBase() {
        return support.call("travel_nmch_base", Map.of());
    }

    @AioaTool(code = "scfy_travel_nmch_popup",
            name = "非遗旅游线路-体验基地详情",
            description = "查询非遗体验基地的弹窗详情（旅游口径）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> nmchPopup(
            @AioaToolParam(name = "cityCode", description = "城市编码，如 510100000000", required = true) String cityCode) {
        return support.call("travel_nmch_popup", ScfyArgs.of("cityCode", cityCode));
    }

    @AioaTool(code = "scfy_travel_tourist_county_list",
            name = "非遗旅游线路-重点县列表",
            description = "查询非遗旅游重点县列表（旅游口径，实测 28 个县，含经纬度）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> touristCountyList() {
        return support.call("travel_tourist_county_list", Map.of());
    }

    @AioaTool(code = "scfy_travel_tourist_county_data",
            name = "非遗旅游线路-县域非遗资源",
            description = "查询某个县/市州的非遗资源汇总（旅游口径：代表性传承人、非遗项目、名录项目）。"
                    + "area 是 12 位行政区划编码（如 510105000000=青羊区），不是县名 —— 传名称会返回全零。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> touristCountyData(
            @AioaToolParam(name = "area", description = "12 位行政区划编码，如 510105000000（青羊区）；可从 scfy_travel_tourist_county_list 取得", required = false) String area) {
        return support.call("travel_tourist_county_data", ScfyArgs.of("area", area));
    }
}
