package cn.aioa.integration.scfy.contract;

import cn.aioa.integration.scfy.core.ScfyEnums;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * scfy 接口清单的<b>唯一事实源</b>。
 *
 * <p>内容来源：接口文档（833 行）+ 2026-09-23 生产西昌环境全量实测（67 个 {@code /show/*} 接口）。
 * 合并规则见 {@link ScfyEndpoint}。探测脚本可重跑：
 * {@code scripts/_probe_fy_show.py}（全量）、{@code scripts/_probe_fy_show2.py}（真实 ID 复测）。</p>
 *
 * <h3>为什么废弃项也要登记</h3>
 * <p>「废弃」和「还没做」是两件事。把不可用接口连同<b>不可用的原因</b>一起写进清单，
 * 下一个人（或下一轮的我）才不会重新踩一遍、也不会误以为只是漏了。
 * 不登记的话，对方再发一版文档，这些坑会原样复活。</p>
 */
public final class ScfyCatalog {

    private ScfyCatalog() {
    }

    // ==================== 参数构造器 ====================
    // 复用同一份实测结论，避免每个接口各自复述一遍导致口径漂移。

    /** 市州参数：实测必须用简称。 */
    private static ScfyParam area(String desc, boolean required) {
        return new ScfyParam("area", required, "string",
                desc + "。" + ScfyEnums.CITY_NAME_WARNING,
                ScfyEnums.CITIES, "成都市",
                "文档示例为全称「甘孜藏族自治州」，实测返回 0 条（不报错）；正确值「甘孜州」返回 291 条");
    }

    /** 等级参数：整档静默失效，警示必须随身携带。 */
    private static ScfyParam level(boolean required) {
        return new ScfyParam("level", required, "string",
                "等级筛选。" + ScfyEnums.LEVEL_FILTER_WARNING,
                ScfyEnums.LEVELS, "country",
                "实测只有 country 生效；un/province/city/county 返回未过滤结果");
    }

    private static ScfyParam pageNum() {
        return new ScfyParam("pageNum", false, "integer",
                "页码，缺省 1", null, "1", null);
    }

    private static ScfyParam pageSize() {
        return new ScfyParam("pageSize", false, "integer",
                "每页条数，缺省 10，上限 100", null, "10", null);
    }

    /** 市州名（不带 area 语义、仅作筛选的接口用的别名参数）。 */
    private static ScfyParam cityName(boolean required) {
        return new ScfyParam("cityName", required, "string",
                "市州名称。" + ScfyEnums.CITY_NAME_WARNING,
                ScfyEnums.CITIES, "成都市",
                "文档未说明简称/全称；经同类接口实测，同样必须用简称");
    }

    /**
     * 行政区划编码形态的 {@code area} 参数。
     * <p>参数名一样是 {@code area}，但取值语义与市州简称完全不同：
     * 实测传简称一律返回全零（不报错），传 12 位编码才有数据。
     * 用 {@code type="areaCode"} 让校验器按格式拦截，
     * 否则「传了简称 → 返回空 → 被当成『这个地方没有非遗资源』」会伪装成结论。</p>
     */
    private static ScfyParam areaCode() {
        return new ScfyParam("area", false, "areaCode",
                "行政区划编码（12 位，如 510105000000=青羊区、510100000000=成都市）。"
                        + "不是市州简称 —— 传「青羊区」「成都市」这类简称实测返回全零且不报错；"
                        + "编码可由 tourist_county_list 接口取得（返回 id=编码、short_name=名称）",
                null, "510105000000",
                "文档只写参数名 area、未说取值形态。实测：简称全零 / 6 位编码（510100）也全零 / "
                        + "12 位编码返回真实数据；不传返回全省（省级项目 35 项）");
    }

    // ==================== 废弃原因 ====================
    // 必须声明在 ALL 之前：ALL 的条目引用了这两个常量。
    // 虽然纯字面量拼接属编译期常量、当前不会踩静态初始化顺序陷阱，
    // 但只要有人把其中之一改成方法调用或非字面量表达式，就会静默变成 null 并把原因写丢。

    private static final String DEPRECATED_SHOP_DATA =
            "生产实测 code=500：relation \"t_shop\" does not exist（Kingbase8 人大金仓）。"
                    + "已用真实工坊 id=140 复测，仍 500 —— 与参数无关，是该 Controller 查询的库表不在当前 schema。"
                    + "同栏目 /show/shop/* 同类数据正常返回（工坊数据本身存在），故本组为环境性缺陷，整组不接入。";

    private static final String DEPRECATED_SHOPS_V2 =
            "文档仅称「与 /show/shop 结构相同，作为 v2 版本」，但未说明 v1 是否下线、新接入应用哪个。"
                    + "在差异与生命周期明确之前，按「不确定即废弃」处理 —— 只接入 /show/shop 一套，避免同一数据两条工具路径。";

    // ==================== 清单 ====================

    private static final List<ScfyEndpoint> ALL = List.of(

            // ---------- 传承人（/show/inheritor）----------
            ScfyEndpoint.available("inheritor_list_by_area", "传承人", "/show/inheritor", "/getInheritorListByArea",
                    "按市州查非遗传承人列表，回答「某地有哪些传承人」。",
                    // area 实测可省：不传返回全省 1821 条（文档标为必填，实测非必填）
                    List.of(area("传承人所属市州；不传返回全省", false), level(false), pageNum(), pageSize())),
            ScfyEndpoint.available("inheritor_detail", "传承人", "/show/inheritor", "/getInheritorDetail",
                    "查单个传承人的详情（简介、级别、出生、视频等）。需先由列表接口拿到 id。",
                    List.of(new ScfyParam("id", true, "string",
                            "传承人 id，取自 inheritor_list_by_area 返回的 dataList[].id。"
                                    + "注意该 id 形如 UUID_级别后缀，不是纯数字",
                            null, "6df60302-f201-4fee-8758-e93d0e4c3112_country", null))),
            ScfyEndpoint.available("inheritor_type_data", "传承人", "/show/inheritor", "/getInheritorTypeData",
                    "查传承人按项目门类的数量分布，回答「哪些门类的传承人多」。",
                    List.of(level(true))),
            ScfyEndpoint.available("inheritor_gender_data", "传承人", "/show/inheritor", "/getGenderNumDataByLevel",
                    "查传承人男女性别数量，回答「男女比例」「女性传承人有多少」。",
                    List.of(level(true))),
            ScfyEndpoint.available("inheritor_birthday_data", "传承人", "/show/inheritor", "/getInheritorBirthday",
                    "查传承人年龄段/出生年代分布，回答「传承人年龄结构」。",
                    List.of(level(true))),
            ScfyEndpoint.available("inheritor_education_data", "传承人", "/show/inheritor", "/getInheritorWhcd",
                    "查传承人学历（文化程度）分布，按国家级/省级两组返回。",
                    List.of(level(true))),
            ScfyEndpoint.available("inheritor_count_by_area", "传承人", "/show/inheritor", "/getAreaInheritorData",
                    "查全省各市州传承人数量对比，回答「哪个市州传承人最多」。返回 21 个市州 × 五档级别计数。",
                    List.of(new ScfyParam("name", false, "string",
                            "固定传「四川省」表示全省汇总；通常无需传", null, "四川省", null))),
            ScfyEndpoint.available("inheritor_yhwd_data", "传承人", "/show/inheritor", "/getYhwdInheritorData",
                    "查「云上非遗」/非遗工坊相关的传承人分布（按市州，含联合国级到县级五档）。",
                    List.of()),
            ScfyEndpoint.available("inheritor_video", "传承人", "/show/inheritor", "/viewVideo",
                    "查传承人视频播放地址。exist=false 表示该传承人暂无视频，不是错误。",
                    List.of(new ScfyParam("inheritorId", true, "string",
                            "传承人 id，取自 inheritor_list_by_area", null, "6df60302-..._country", null))),

            // ---------- 项目（/show/project）----------
            ScfyEndpoint.available("project_list_by_area", "项目", "/show/project", "/getProjectListByArea",
                    "按条件查非遗项目列表，回答「有哪些非遗项目」。不传 area 返回全省 1411 条。",
                    // 本接口的 level 与别处不同：它是「完全被忽略」而非「只有 country 生效」——
                    // 传 country 与不传同为全省 1411 条。故不能沿用 level() 的通用文案。
                    List.of(area("项目所属市州；不传返回全省", false),
                            level(false).withDocNote("实测本接口完全忽略 level：传 country 与不传同为全省 1411 条。"
                                    + "按等级统计请改用 scfy_project_count_by_area"),
                            pageNum(), pageSize())),
            ScfyEndpoint.available("project_detail", "项目", "/show/project", "/getProjectDetail",
                    "查单个非遗项目详情（保护单位、传承人、简介）。需先由列表拿到 project_base_id。",
                    List.of(new ScfyParam("id", true, "string",
                            "项目 id（project_base_id），取自 project_list_by_area 返回的 dataList[].project_base_id，"
                                    + "形如 2-UN-1 / 2-GJ-92",
                            null, "2-UN-1", null))),
            ScfyEndpoint.available("project_type_data", "项目", "/show/project", "/getProjectTypeData",
                    "查非遗项目按十大类（传统技艺/传统戏剧/民俗…）的数量分布。level 必填。",
                    List.of(level(true))),
            ScfyEndpoint.available("project_batch_data", "项目", "/show/project", "/getProjectBatchData",
                    "查非遗项目按批次的分布，返回国家级/省级 × 折线/柱状四组数据。",
                    List.of(area("限定市州；不传为全省", false))),
            ScfyEndpoint.available("project_count_by_area", "项目", "/show/project", "/getProjectCountByArea",
                    "查指定市州各等级项目数量 —— 这是查看「联合国级」等档位数量的正确入口。",
                    List.of(area("市州", true))),
            ScfyEndpoint.available("project_area_summary", "项目", "/show/project", "/getAreaProjectData",
                    "查全省各市州项目数量汇总（含联合国级 un_project / 国家级 / 省级 / 市级 / 县级 / all 六档）。",
                    List.of(new ScfyParam("name", false, "string",
                            "固定传「四川省」表示全省汇总；通常无需传", null, "四川省", null))),
            ScfyEndpoint.available("project_yhwd_data", "项目", "/show/project", "/getYhwdProjectData",
                    "查「云上非遗」/非遗工坊相关项目分布（按市州，六档：联合国/国家/省/市/县/区）。",
                    List.of()),
            ScfyEndpoint.available("project_video", "项目", "/show/project", "/viewVideo",
                    "查非遗项目视频播放地址。exist=false 表示暂无视频。",
                    List.of(new ScfyParam("projectBaseId", true, "string",
                            "项目 id（project_base_id）", null, "2-UN-1", null))),

            // ---------- 工坊（/show/shop）----------
            ScfyEndpoint.available("shop_table", "工坊", "/show/shop", "/shopTable",
                    "查非遗工坊/店铺列表（含销量、平台、项目名），回答「成都有哪些非遗工坊」。",
                    List.of(cityName(true))),
            ScfyEndpoint.available("shop_pie_and_stores", "工坊", "/show/shop", "/pieChartAndStores",
                    "查工坊数量 + 按项目类型的饼图分布。",
                    List.of(cityName(true))),
            ScfyEndpoint.available("shop_category_sum", "工坊", "/show/shop", "/categorySum",
                    "查工坊经营类别汇总（线上线下销售额、老字号数量、各档传承人数量）。",
                    List.of(cityName(true))),
            ScfyEndpoint.available("shop_bar_chart", "工坊", "/show/shop", "/barChart",
                    "查工坊在各电商平台的销量柱状图。",
                    List.of(cityName(true))),
            ScfyEndpoint.available("shop_map_chart", "工坊", "/show/shop", "/mapChart",
                    "查工坊按市州/区县的地图分布。",
                    List.of(cityName(true), new ScfyParam("areaName", false, "string",
                            "区县名，用于下钻到区县（如 锦江区）", null, "锦江区", null))),
            ScfyEndpoint.available("shop_area_map_chart", "工坊", "/show/shop", "/areaMapChart",
                    "查工坊在区域维度（type1/2/3 三档）的地图分布。",
                    List.of(cityName(true))),
            ScfyEndpoint.available("shop_sales_and_amount", "工坊", "/show/shop", "/salesAndSalesAmount",
                    "查指定市州工坊的总销售额与销售量。",
                    List.of(cityName(true), new ScfyParam("areaName", false, "string",
                            "区县名，可选", null, "锦江区", null))),
            ScfyEndpoint.available("shop_detail", "工坊", "/show/shop", "/shopDetail",
                    "查单个工坊/店铺详情（线上店铺、简介、传承人）。",
                    List.of(cityName(true), new ScfyParam("id", true, "string",
                            "工坊 id，取自 shop_table 返回的 list[].id",
                            null, "140",
                            "文档写参数名为 shopId，实测必填参数名是 id —— 传 shopId 会报 "
                                    + "Required String parameter 'id' is not present"))),
            ScfyEndpoint.available("shop_inheritor", "工坊", "/show/shop", "/shopInheritor",
                    "查某个工坊关联的传承人。",
                    List.of(cityName(true), new ScfyParam("id", true, "string",
                            "工坊 id", null, "140",
                            "文档写 shopId，实测必填 id"))),
            ScfyEndpoint.available("shop_sales", "工坊", "/show/shop", "/shopSales",
                    "查某个工坊的销量（线上/线下销售额与数量）。",
                    List.of(cityName(true), new ScfyParam("id", true, "string",
                            "工坊 id", null, "140",
                            "文档写 shopId，实测必填 id"))),
            ScfyEndpoint.available("shop_project_type_pie", "工坊", "/show/shop", "/shopProjectTypePieChart",
                    "查某工坊的项目类型饼图。",
                    List.of(cityName(true), new ScfyParam("id", true, "string",
                            "工坊 id", null, "140",
                            "文档只说必填 cityName，实测还必填 id（漏标）"))),
            ScfyEndpoint.available("shop_sales_num_pie", "工坊", "/show/shop", "/shopSalesAndNumPieChart",
                    "查某工坊按平台的销售数量与销售额饼图。",
                    List.of(cityName(true), new ScfyParam("id", true, "string",
                            "工坊 id", null, "140",
                            "文档只说必填 cityName，实测还必填 id（漏标）"))),
            ScfyEndpoint.available("shop_address_distribution", "工坊", "/show/shop", "/addrDistribution",
                    "查工坊地址分布（含经纬度、行政区划层级）与账号层级统计。",
                    List.of(cityName(true))),

            // ---------- 文化生态保护区（/show/ecologicalArea）----------
            ScfyEndpoint.available("eco_area_count", "保护区", "/show/ecologicalArea", "/getAreasNum",
                    "查文化生态保护区数量（按国家级/省级返回）。",
                    List.of()),
            ScfyEndpoint.available("eco_area_top_list", "保护区", "/show/ecologicalArea", "/getAreasTopFewList",
                    "查文化生态保护区列表（含名称、级别、经纬度、简介），回答「有哪些保护区」。",
                    List.of(new ScfyParam("topNum", false, "integer",
                            "返回条数，缺省返回全部", null, "10", null))),
            ScfyEndpoint.available("eco_city_round", "保护区", "/show/ecologicalArea", "/getCityRoundByAreaId",
                    "查某个保护区的地理边界坐标（用于地图描边）。",
                    List.of(new ScfyParam("ecologicalAreaId", true, "string",
                            "保护区 id，取自 eco_area_top_list 的 areasTopFewList[].ecologicalarea_id",
                            null, "5f199a336e2e44efab9c5541f4138fe9", null))),
            ScfyEndpoint.available("eco_road_data", "保护区", "/show/ecologicalArea", "/getEcologicalAreaRoadData",
                    "查保护区内项目/集聚区/体验基地的分页数据。",
                    List.of(new ScfyParam("ecologicalAreaId", true, "string", "保护区 id", null, null, null),
                            new ScfyParam("areaId", true, "string",
                                    "区域编码（city_code，形如 510100000000）", null, "510100000000", null),
                            pageNum(), pageSize())),
            ScfyEndpoint.available("eco_road_distribute", "保护区", "/show/ecologicalArea", "/getRoadDistributeData",
                    "查保护区内资源的分布统计（项目/集聚区/体验基地三组）。",
                    List.of(new ScfyParam("ecologicalAreaId", true, "string", "保护区 id", null, null, null),
                            new ScfyParam("areaId", true, "string", "区域编码 city_code", null, "510100000000", null))),
            ScfyEndpoint.available("eco_all_image", "保护区", "/show/ecologicalArea", "/getAllTravelImageUrl",
                    "查保护区的全部图片（实测用真实 id 可返回非空 imageList）。",
                    List.of(new ScfyParam("ecologicalAreaId", true, "string", "保护区 id", null, null, null))),
            ScfyEndpoint.available("eco_details", "保护区", "/show/ecologicalArea", "/getDetailsData",
                    "查保护区某条数据的详情（名称、类型、地址、简介、图片）。",
                    List.of(new ScfyParam("type", true, "string", "对象类型编码", null, "1",
                                    "实测 type=1 与 5 返回同一条真实数据（青城山--都江堰旅游景区，area_type=5A），"
                                            + "type=2/3/4 返回空对象 {} 且 code=0。文档未说明取值含义，"
                                            + "故不臆造枚举，只把实测可用值写入说明"),
                            new ScfyParam("dataId", true, "string", "对象 id", null, "1",
                                    "实测传不存在的 id 同样返回空对象 {} 且 code=0"))),
            ScfyEndpoint.available("eco_nmch_base", "保护区", "/show/ecologicalArea", "/getNmchBaseData",
                    "查非遗体验基地列表（保护区口径）。"
                            + "实测本前缀下恒为空列表（调用成功、code=0、无数据），"
                            + "体验基地数据请改用 travel_nmch_base（实测 21 个城市、约 405 个字段值）。",
                    List.of()),
            ScfyEndpoint.available("eco_nmch_popup", "保护区", "/show/ecologicalArea", "/getNmchBasePopupData",
                    "查非遗体验基地弹窗详情（简介、产品）。",
                    List.of(new ScfyParam("cityCode", true, "string",
                            "城市编码（city_code，形如 510100000000）", null, "510100000000", null))),
            ScfyEndpoint.available("eco_tourist_county_list", "保护区", "/show/ecologicalArea", "/getTouristCountyList",
                    "查非遗旅游重点县列表（含名称、经纬度），这是获取合法 areaId 的入口。",
                    List.of()),
            ScfyEndpoint.available("eco_tourist_county_data", "保护区", "/show/ecologicalArea", "/getTouristCountyData",
                    "查某个县/市州的非遗资源汇总（代表性传承人、非遗项目、名录项目）。"
                            + "area 收行政区划编码，编码可由 eco_tourist_county_list 取得。",
                    List.of(areaCode())),

            // ---------- 旅游线路（/show/travel）----------
            ScfyEndpoint.available("travel_route_top_list", "旅游", "/show/travel", "/getRoutesTopFewList",
                    "查非遗旅游线路列表（含名称、封面图），回答「有哪些非遗旅游线路」。",
                    List.of(new ScfyParam("topNum", false, "integer",
                            "返回条数，缺省返回全部", null, "10", null))),
            ScfyEndpoint.available("travel_city_round", "旅游", "/show/travel", "/getCityRoundByTravelId",
                    "查某条旅游线路的地理边界坐标与中心点。",
                    List.of(new ScfyParam("travelId", true, "string",
                            "线路 id，取自 travel_route_top_list 的 routesTopFewList[].travel_id",
                            null, "43c4f5188de54c46b2b03094ff1e5da0", null))),
            ScfyEndpoint.available("travel_road_type_count", "旅游", "/show/travel", "/getTravelRoadTypeCount",
                    "查旅游线路沿线的资源类型数量统计（项目/区域/基地）。",
                    List.of(new ScfyParam("travelId", true, "string",
                            "线路 id", null, null,
                            "文档标注「必填参数：—」，实测必填 travelId（漏标）"))),
            ScfyEndpoint.available("travel_road_by_type", "旅游", "/show/travel", "/getTravelRoadDataByType",
                    "查某条线路下指定类型的资源分页列表。",
                    List.of(new ScfyParam("type", true, "string", "资源类型编码", null, "1", null),
                            new ScfyParam("travelId", true, "string",
                                    "线路 id", null, null,
                                    "文档只标了 type，实测还必填 travelId（漏标）"))),
            ScfyEndpoint.available("travel_road_data", "旅游", "/show/travel", "/getTravelRoadData",
                    "查某条线路的完整资源分页数据（项目/集聚区/体验基地三组）。",
                    List.of(new ScfyParam("travelId", true, "string", "线路 id", null, null, null),
                            new ScfyParam("areaId", false, "string", "区域编码，可选", null, "510100000000", null),
                            pageNum(), pageSize())),
            ScfyEndpoint.available("travel_road_detail", "旅游", "/show/travel", "/getTravelRoadDataDetail",
                    "查线路中某条资源的详情（简介、图片、路线）。",
                    List.of(new ScfyParam("dataId", true, "string",
                            "资源 id，取自 travel_road_by_type 返回的 dataList[].project_base_id"
                                    + "（形如 05760cdf947f4f32968cf79d3c695b2b）",
                            null, "05760cdf947f4f32968cf79d3c695b2b",
                            "实测传不存在的 id（如 1）返回空对象 {} 且 code=0 —— 空结果不等于「资源没有详情」"),
                            new ScfyParam("type", true, "string", "资源类型编码", null, "1",
                                    "实测 type 被忽略：1/2/3/4 返回同一份详情"))),
            ScfyEndpoint.available("travel_road_distribute", "旅游", "/show/travel", "/getTravelRoadDistributeData",
                    "查某条线路的资源分布统计。",
                    List.of(new ScfyParam("travelId", true, "string",
                            "线路 id", null, null,
                            "文档标注「必填参数：—」，实测必填 travelId（漏标）"))),
            ScfyEndpoint.available("travel_image", "旅游", "/show/travel", "/getTravelImageUrl",
                    "查某条线路下某一类对象的图片地址（含图片名）。",
                    List.of(new ScfyParam("travelId", true, "string", "线路 id", null, null, null),
                            new ScfyParam("type", true, "string",
                                    "图片对象类型：2=项目图片、3=体验基地图片",
                                    List.of("2", "3"), "2",
                                    "文档未给取值。实测 type 实质必填：不传、或传 1/4/5 都返回空 imageList "
                                            + "（不报错）；type=2 返回该线路的项目图片（实测 155 条）、"
                                            + "type=3 返回体验基地图片（实测 9 条），且不同 travelId 返回不同结果"))),
            ScfyEndpoint.available("travel_all_image", "旅游", "/show/travel", "/getAllTravelImageUrl",
                    "查某条线路的全部图片（实测可返回非空 imageList）。",
                    List.of(new ScfyParam("travelId", true, "string", "线路 id", null, null, null))),
            ScfyEndpoint.available("travel_details", "旅游", "/show/travel", "/getDetailsData",
                    "查线路中某条数据的详情。",
                    List.of(new ScfyParam("type", true, "string", "对象类型编码", null, "1",
                                    "与保护区同名的 getDetailsData 返回结构完全一致；实测 type=1/5 有数据、"
                                            + "2/3/4 返回空对象 {} 且 code=0，取值含义文档未说明"),
                            new ScfyParam("dataId", true, "string", "对象 id", null, "1", null))),
            ScfyEndpoint.available("travel_nmch_base", "旅游", "/show/travel", "/getNmchBaseData",
                    "查非遗体验基地列表（旅游口径，实测 21 条，比保护区口径更全）。",
                    List.of()),
            ScfyEndpoint.available("travel_nmch_popup", "旅游", "/show/travel", "/getNmchBasePopupData",
                    "查非遗体验基地弹窗详情（旅游口径）。",
                    List.of(new ScfyParam("cityCode", true, "string",
                            "城市编码 city_code", null, "510100000000", null))),
            ScfyEndpoint.available("travel_tourist_county_list", "旅游", "/show/travel", "/getTouristCountyList",
                    "查非遗旅游重点县列表（旅游口径）。",
                    List.of()),
            ScfyEndpoint.available("travel_tourist_county_data", "旅游", "/show/travel", "/getTouristCountyData",
                    "查某个县/市州的非遗资源汇总（旅游口径）。"
                            + "area 收行政区划编码，编码可由 travel_tourist_county_list 取得。",
                    List.of(areaCode())),

            // ==================== 废弃项（登记原因，不注册为工具）====================

            ScfyEndpoint.deprecated("deprecated_shop_data_type_scale", "工坊(废弃)", "/show/data", "/shopTypeScale",
                    "工坊类型规模统计", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_left_rect", "工坊(废弃)", "/show/data", "/leftRectScale",
                    "工坊左区矩形统计", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_left_bar", "工坊(废弃)", "/show/data", "/leftBarScale",
                    "工坊左区柱状统计", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_right_map", "工坊(废弃)", "/show/data", "/rightMapDistribution",
                    "工坊地图分布", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_detail", "工坊(废弃)", "/show/data", "/shopDetail/{id}",
                    "工坊详情（路径参数版）", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_infos", "工坊(废弃)", "/show/data", "/shopInfos",
                    "工坊列表（data 口径）", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_sale_stat", "工坊(废弃)", "/show/data", "/saleStat",
                    "工坊销售统计", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shop_data_plat_sale", "工坊(废弃)", "/show/data", "/platSaleStat",
                    "工坊平台销售统计", DEPRECATED_SHOP_DATA),
            ScfyEndpoint.deprecated("deprecated_shopv2_table", "工坊v2(废弃)", "/show/shopv2", "/shopTable",
                    "工坊列表 v2", DEPRECATED_SHOPS_V2),
            ScfyEndpoint.deprecated("deprecated_shopv2_pie", "工坊v2(废弃)", "/show/shopv2", "/pieChartAndStores",
                    "工坊饼图 v2", DEPRECATED_SHOPS_V2),
            ScfyEndpoint.deprecated("deprecated_eco_area_image", "保护区(废弃)", "/show/ecologicalArea",
                    "/getEcologicalAreaImageUrl",
                    "保护区指定对象图片",
                    "type 取值语义未明确，且错配即报错：实测同一保护区下，项目类对象只有 type=2 不报错、"
                            + "集聚区类对象只有 type=1/4/5 不报错，其余取值一律 code=500 "
                            + "「Incorrect result size: expected 1, actual 0」。"
                            + "既然无法告诉模型该传什么 type，按「不确定即废弃」处理 —— "
                            + "图片需求改用 eco_all_image（实测 123 个字段值）与 eco_details（返回 image_url）。"),
            ScfyEndpoint.deprecated("deprecated_eco_pager_image", "保护区(废弃)", "/show/ecologicalArea", "/getPagerTravelImageUrl",
                    "保护区分页图片", "实测只返回 {pager:{...}} 分页器，**没有任何数据列表字段**，"
                    + "调用方拿不到图片；改用 eco_all_image / eco_area_image。")
    );

    private static final Map<String, ScfyEndpoint> BY_ID =
            ALL.stream().collect(Collectors.toUnmodifiableMap(ScfyEndpoint::id, Function.identity()));

    /** 全部契约（含废弃）。 */
    public static List<ScfyEndpoint> all() {
        return ALL;
    }

    /** 可用接口 —— 工具注册与测试矩阵都以此为准。 */
    public static List<ScfyEndpoint> available() {
        return ALL.stream().filter(ScfyEndpoint::available).toList();
    }

    /** 废弃接口（含原因），用于生成「为什么没接入」清单。 */
    public static List<ScfyEndpoint> deprecated() {
        return ALL.stream().filter(e -> !e.available()).toList();
    }

    public static ScfyEndpoint byId(String id) {
        return BY_ID.get(id);
    }

    public static long availableCount() {
        return available().size();
    }
}
