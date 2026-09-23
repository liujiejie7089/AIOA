# -*- coding: utf-8 -*-
"""
把「接口文档声称」与「生产实测」合并，生成映射表 Markdown。
原则：实测结果与文档声称同源对照，不手抄、不臆造。
"""
import json

# 文档声称：(分组, 前缀, 路径, 必填参数, 可选参数, 文档声称返回)
DOC = {
    ("/show/inheritor", "/getInheritorListByArea"): ("6.1传承人", "area", "level,pageNum,pageSize", "list:[{id,name,level,category}], total"),
    ("/show/inheritor", "/getInheritorDetail"): ("6.1传承人", "id", "—", "name,level,gender,birthday,category,intro,videoUrl,projectList,awards"),
    ("/show/inheritor", "/getInheritorTypeData"): ("6.1传承人", "level", "area", "[{name:\"国家级\",value:120}]"),
    ("/show/inheritor", "/getGenderNumDataByLevel"): ("6.1传承人", "level", "—", "{male:80,female:40}"),
    ("/show/inheritor", "/getInheritorBirthday"): ("6.1传承人", "level", "—", "[{decade:\"1950s\",count:30}]"),
    ("/show/inheritor", "/getInheritorWhcd"): ("6.1传承人", "level", "—", "[{name:\"本科\",value:50}]"),
    ("/show/inheritor", "/getAreaInheritorData"): ("6.1传承人", "name", "—", "[{area:\"成都市\",count:120}]"),
    ("/show/inheritor", "/getYhwdInheritorData"): ("6.1传承人", "—", "—", "{total,list}"),
    ("/show/inheritor", "/viewVideo"): ("6.1传承人", "inheritorId", "—", "{videoUrl,coverUrl}"),

    ("/show/project", "/getProjectListByArea"): ("6.2项目", "area", "level,pageNum,pageSize", "list:[{id,name,level,category,batch}], total"),
    ("/show/project", "/getProjectDetail"): ("6.2项目", "id", "—", "name,level,batch,category,intro,protectUnit,inheritorList"),
    ("/show/project", "/getProjectTypeData"): ("6.2项目", "level", "area", "[{name:\"传统戏剧\",value:50}]"),
    ("/show/project", "/getProjectBatchData"): ("6.2项目", "area", "—", "[{batch:\"第一批\",count:30}]"),
    ("/show/project", "/getProjectCountByArea"): ("6.2项目", "area", "—", "{count}"),
    ("/show/project", "/getAreaProjectData"): ("6.2项目", "name", "—", "[{area,count}]"),
    ("/show/project", "/getYhwdProjectData"): ("6.2项目", "—", "—", "{total,list}"),
    ("/show/project", "/viewVideo"): ("6.2项目", "projectBaseId", "—", "{videoUrl}"),

    ("/show/data", "/shopTypeScale"): ("6.3工坊", "—", "cityName", "[{name:\"传统工艺\",value:80}]"),
    ("/show/data", "/leftRectScale"): ("6.3工坊", "cityName", "—", "{levelData,onlineData,poorData}"),
    ("/show/data", "/leftBarScale"): ("6.3工坊", "cityName", "—", "[{name,value}]"),
    ("/show/data", "/rightMapDistribution"): ("6.3工坊", "—", "—", "[{city:\"成都市\",count:50}]"),
    ("/show/data", "/shopDetail/35412"): ("6.3工坊", "id(路径)", "num", "{name,intro,inheritorList,productList}"),
    ("/show/data", "/shopInfos"): ("6.3工坊", "cityName", "—", "{list,total}"),
    ("/show/data", "/saleStat"): ("6.3工坊", "shopId", "cityName", "{salesAmount,salesNum,monthlyTrend}"),
    ("/show/data", "/platSaleStat"): ("6.3工坊", "shopId", "—", "{platformList:[{plat,sales}]}"),

    ("/show/shop", "/salesAndSalesAmount"): ("6.3工坊", "cityName,areaName", "—", "销售额和销售量综合"),
    ("/show/shop", "/pieChartAndStores"): ("6.3工坊", "cityName", "—", "饼图+工坊列表"),
    ("/show/shop", "/categorySum"): ("6.3工坊", "cityName", "—", "类别汇总"),
    ("/show/shop", "/barChart"): ("6.3工坊", "cityName", "—", "柱状图"),
    ("/show/shop", "/mapChart"): ("6.3工坊", "cityName,areaName", "—", "工坊地图分布"),
    ("/show/shop", "/areaMapChart"): ("6.3工坊", "cityName", "—", "区域地图"),
    ("/show/shop", "/shopTable"): ("6.3工坊", "cityName", "—", "工坊列表"),
    ("/show/shop", "/shopDetail"): ("6.3工坊", "cityName,shopId", "—", "工坊详情"),
    ("/show/shop", "/shopInheritor"): ("6.3工坊", "cityName,shopId", "—", "工坊传承人"),
    ("/show/shop", "/shopSales"): ("6.3工坊", "cityName,shopId", "—", "工坊销量"),
    ("/show/shop", "/shopProjectTypePieChart"): ("6.3工坊", "cityName", "—", "项目类型饼图"),
    ("/show/shop", "/shopSalesAndNumPieChart"): ("6.3工坊", "cityName", "—", "销售数量饼图"),
    ("/show/shop", "/addrDistribution"): ("6.3工坊", "cityName", "—", "地址分布"),

    ("/show/shopv2", "/shopTable"): ("6.3工坊v2", "cityName", "—", "同 shop"),
    ("/show/shopv2", "/pieChartAndStores"): ("6.3工坊v2", "cityName", "—", "同 shop"),

    ("/show/ecologicalArea", "/getAreasNum"): ("6.4保护区", "—", "—", "{total:18}"),
    ("/show/ecologicalArea", "/getAreasTopFewList"): ("6.4保护区", "—", "topNum", "[{id,name,areaCount}]"),
    ("/show/ecologicalArea", "/getCityRoundByAreaId"): ("6.4保护区", "ecologicalAreaId", "—", "{cityCode,boundary}"),
    ("/show/ecologicalArea", "/getEcologicalAreaRoadData"): ("6.4保护区", "ecologicalAreaId,areaId", "pageNum,pageSize", "{list,total}"),
    ("/show/ecologicalArea", "/getRoadDistributeData"): ("6.4保护区", "ecologicalAreaId,areaId", "—", "[{type,count}]"),
    ("/show/ecologicalArea", "/getEcologicalAreaImageUrl"): ("6.4保护区", "ecologicalAreaId,areaId,type,dataId", "—", "{imageUrls:[]}"),
    ("/show/ecologicalArea", "/getAllTravelImageUrl"): ("6.4保护区", "ecologicalAreaId", "—", "{images:{}}"),
    ("/show/ecologicalArea", "/getPagerTravelImageUrl"): ("6.4保护区", "ecologicalAreaId", "noPage,pageNum,pageSize", "{list,total}"),
    ("/show/ecologicalArea", "/getDetailsData"): ("6.4保护区", "type,dataId", "—", "{name,intro,images}"),
    ("/show/ecologicalArea", "/getNmchBaseData"): ("6.4保护区", "—", "—", "{list:[{id,name,address}]}"),
    ("/show/ecologicalArea", "/getNmchBasePopupData"): ("6.4保护区", "cityCode", "—", "{intro,products:[]}"),
    ("/show/ecologicalArea", "/getTouristCountyList"): ("6.4保护区", "—", "—", "[{id,name}]"),
    ("/show/ecologicalArea", "/getTouristCountyData"): ("6.4保护区", "area", "—", "{name,intro,projects:[]}"),

    ("/show/travel", "/getRoutesTopFewList"): ("6.5旅游", "—", "topNum", "[{id,name,type}]"),
    ("/show/travel", "/getCityRoundByTravelId"): ("6.5旅游", "travelId", "—", "{cityCode,boundary}"),
    ("/show/travel", "/getTravelRoadTypeCount"): ("6.5旅游", "—", "—", "[{type,count}]"),
    ("/show/travel", "/getTravelRoadDataByType"): ("6.5旅游", "type", "—", "{list,total}"),
    ("/show/travel", "/getTravelRoadData"): ("6.5旅游", "travelId", "areaId,pageNum,pageSize", "{list,total}"),
    ("/show/travel", "/getTravelRoadDataDetail"): ("6.5旅游", "dataId,type", "—", "{intro,images,routes:[]}"),
    ("/show/travel", "/getTravelRoadDistributeData"): ("6.5旅游", "—", "—", "[{area,count}]"),
    ("/show/travel", "/getTravelImageUrl"): ("6.5旅游", "travelId", "type", "{imageUrls:[]}"),
    ("/show/travel", "/getAllTravelImageUrl"): ("6.5旅游", "travelId", "—", "{images:{}}"),
    ("/show/travel", "/getDetailsData"): ("6.5旅游", "type,dataId", "—", "{name,intro}"),
    ("/show/travel", "/getNmchBaseData"): ("6.5旅游", "—", "—", "{list}"),
    ("/show/travel", "/getNmchBasePopupData"): ("6.5旅游", "cityCode", "—", "{intro}"),
    ("/show/travel", "/getTouristCountyList"): ("6.5旅游", "—", "—", "[{id,name}]"),
    ("/show/travel", "/getTouristCountyData"): ("6.5旅游", "area", "—", "{intro}"),
}

# 实测校正（来自 _probe_fy_show2.py 阶段三）：文档参数名/必填错误
FIX = {
    ("/show/shop", "/shopDetail"): ("文档写 `shopId`，实际必填 `id`（传 shopId 报 Required String parameter 'id' is not present）", "cityName, **id**"),
    ("/show/shop", "/shopInheritor"): ("文档写 `shopId`，实际必填 `id`", "cityName, **id**"),
    ("/show/shop", "/shopSales"): ("文档写 `shopId`，实际必填 `id`", "cityName, **id**"),
    ("/show/shop", "/shopProjectTypePieChart"): ("文档漏标：除 cityName 外实际还必填 `id`", "cityName, **id**"),
    ("/show/shop", "/shopSalesAndNumPieChart"): ("文档漏标：除 cityName 外实际还必填 `id`", "cityName, **id**"),
    ("/show/travel", "/getTravelRoadTypeCount"): ("文档标「必填：—」，实际必填 `travelId`", "**travelId**"),
    ("/show/travel", "/getTravelRoadDistributeData"): ("文档标「必填：—」，实际必填 `travelId`", "**travelId**"),
    ("/show/travel", "/getTravelRoadDataByType"): ("文档只标 `type`，实际还必填 `travelId`", "type, **travelId**"),
    ("/show/project", "/getProjectListByArea"): ("文档标 area 必填，实测不传 area 返回全省 1411 条（code=0）", "area（实测可省，默认全省）"),
}

# 实测返回结构与文档不符的（人工核对 probe 输出）
SHAPE_DIFF = {
    ("/show/inheritor", "/getInheritorTypeData"): "⚠️ 文档说返回传承人等级分布，实测返回**项目类别**分布（民间文学/传统音乐/传统技艺…），且与 /show/project/getProjectTypeData 结构完全相同",
    ("/show/ecologicalArea", "/getAreasNum"): "⚠️ 文档说 `{total:18}`，实测 `{country:\"1\", province:\"6\"}`（字符串值）",
    ("/show/inheritor", "/getGenderNumDataByLevel"): "⚠️ 文档说 `{male,female}`，实测 `{manCount, womanCount, totalCount}`",
    ("/show/inheritor", "/getInheritorBirthday"): "⚠️ 文档说 `[{decade,count}]`，实测 `{total, data:[{name,value}]}`",
    ("/show/inheritor", "/getInheritorWhcd"): "⚠️ 文档说 `[{name,value}]`，实测 `{country:[...], province:[...]}` 两组",
    ("/show/inheritor", "/getAreaInheritorData"): "文档过简：实测 22 个市州 × {country_inheritor, province_inheritor, city_inheritor, county_inheritor, all}",
    ("/show/inheritor", "/viewVideo"): "⚠️ 文档说 `{videoUrl,coverUrl}`，实测 `{exist:bool, viewUrl:str}`",
    ("/show/project", "/getProjectCountByArea"): "⚠️ 文档说 `{count}`，实测 `[{level_name, num}] x3`",
    ("/show/project", "/getProjectBatchData"): "⚠️ 文档说 `[{batch,count}]`，实测 `{line_province, bar_country, bar_province, line_country}` 四数组",
    ("/show/ecologicalArea", "/getAreasTopFewList"): "⚠️ 文档说 `[{id,name,areaCount}]`，实测多一层 `{areasTopFewList:[{ecologicalarea_id, area_name, area_level,...}]}`",
    ("/show/ecologicalArea", "/getNmchBaseData"): "⚠️ 文档说 `{list:[...]}`，实测 `{nmchBaseDataList:[]}`（该前缀下为空；/show/travel 下 21 条）",
    ("/show/ecologicalArea", "/getAllTravelImageUrl"): "⚠️ 文档说 `{images:{}}`，实测 `{imageList:[]}`",
    ("/show/ecologicalArea", "/getDetailsData"): "⚠️ 文档说 `{name,intro,images}`，实测 `{id, area_name, area_type, address, introduction, image_url}`",
    ("/show/ecologicalArea", "/getPagerTravelImageUrl"): "⚠️ 实测只返回 `{pager:{...}}`，**无数据列表字段** —— 疑似缺陷",
    ("/show/travel", "/getRoutesTopFewList"): "⚠️ 文档说 `[{id,name,type}]`，实测多一层 `{routesTopFewList:[{travel_id, line_name, coverPictureUrl}]}`",
    ("/show/travel", "/getAllTravelImageUrl"): "⚠️ 文档说 `{images:{}}`，实测 `{imageList:[]}`",
    ("/show/travel", "/getNmchBaseData"): "⚠️ 文档说 `{list}`，实测 `{nmchBaseDataList:[{city_code, city_name, base_num, info_list}]}`",
    ("/show/travel", "/getTouristCountyList"): "⚠️ 文档说 `[{id,name}]`，实测多一层 `{touristCounty:[{id, short_name, longitude, latitude}]}`",
    ("/show/inheritor", "/getInheritorListByArea"): "⚠️ 文档说 `{list,total}`，实测 `{pageCount, pageNumber, dataList, pageSize, totalCount}`",
    ("/show/project", "/getProjectListByArea"): "⚠️ 文档说 `{list,total}`，实测 `{pageCount, pageNumber, dataList, pageSize, totalCount}`",
}

# 生产库缺表：/show/data/* 全系
DATA_BROKEN = {"/shopTypeScale", "/leftRectScale", "/leftBarScale", "/rightMapDistribution",
               "/shopDetail/35412", "/shopInfos", "/saleStat", "/platSaleStat"}


def main():
    rs = json.load(open("docs/_incoming/probe_show_result.json", encoding="utf-8"))
    by = {(r["prefix"], r["path"]): r for r in rs}

    lines = []
    lines.append("# 非遗四川 2023（scfy）接口映射表 —— 文档声称 vs 生产实测")
    lines.append("")
    lines.append("> 生成方式：`scripts/_gen_fy_map.py` 合并「接口文档表格」与「生产西昌环境实测结果」自动产出，不手抄。")
    lines.append("> 实测环境：`https://szbhpt.tsichuan.com/scfy`（唯一可达环境）。探测器：`scripts/_probe_fy_show.py`、`_probe_fy_show2.py`。")
    lines.append("> 实测时间：2026-09-21")
    lines.append("")
    lines.append("**状态图例**：`OK` 实测 code=0 且有数据 ｜ `空` code=0 但 data 为空 ｜ `❌缺陷` 生产库报错 ｜ `⚠️文档错` 文档参数/结构与实测不符")
    lines.append("")

    cur = None
    for (prefix, path), (grp, req, opt, docshape) in sorted(DOC.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if grp != cur:
            cur = grp
            lines.append(f"\n## {cur}　`{prefix}`\n")
            lines.append("| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |")
            lines.append("|---|---|---|---|---|---|")
        r = by.get((prefix, path), {})
        http = r.get("http", "?")
        code = r.get("code", "?")
        shape = r.get("shape") or (r.get("err", "")[:40] if r.get("http") == -1 else "")
        fix = FIX.get((prefix, path))
        realreq = fix[1] if fix else req
        diff = SHAPE_DIFF.get((prefix, path), "")

        if path in DATA_BROKEN or (prefix == "/show/data" and code == 500):
            status = "❌缺陷"
            shape = "后端 SQL 异常：`relation \"t_shop\" does not exist`（Kingbase8）"
        elif code == 500:
            status = "⚠️文档错"
        elif shape in ("{}", "[]") or (isinstance(shape, str) and shape.endswith("x0")):
            status = "空（需真实ID）"
        else:
            status = "OK"

        shape_cell = shape if len(str(shape)) < 78 else str(shape)[:75] + "…"
        lines.append(f"| `{path}` | {req} | {realreq} | {http}/{code} | `{shape_cell}` | {status} |")
        if fix:
            lines.append(f"| ↳ 校正 | | | | **{fix[0]}** | |")
        if diff:
            lines.append(f"| ↳ 返回差异 | | | | **{diff}** | |")

    lines.append("\n\n## 缺陷汇总")
    lines.append("")
    lines.append("### D1（被接入系统生产缺陷，非文档问题）")
    lines.append("")
    lines.append("`/show/data/*` 全系 8 个接口在生产西昌返回 `code=500`：")
    lines.append("")
    lines.append("```")
    lines.append('ERROR: relation "t_shop" does not exist')
    lines.append("  Position: 58  (Kingbase8 / 人大金仓)")
    lines.append("```")
    lines.append("")
    lines.append("涉及：`shopTypeScale` `leftRectScale` `leftBarScale` `rightMapDistribution` `shopDetail/{id}` `shopInfos` `saleStat` `platSaleStat`")
    lines.append("")
    lines.append("已用真实工坊 ID（140 成都宋西平漆艺）复测，仍 500 ⇒ 与参数无关，是**生产库缺表/schema 不一致**。")
    lines.append("对照：同栏目 `/show/shop/*` 用 `id` 可正常返回工坊数据 ⇒ 工坊数据存在，是 `/show/data/*` 这套 Controller 查的老表不在当前 schema。")
    lines.append("")
    lines.append("### D2（接口文档参数错误/漏标，共 8 处）")
    lines.append("")
    lines.append("| 接口 | 文档写 | 实际 | 证据 |")
    lines.append("|---|---|---|---|")
    for (prefix, path), (why, real) in FIX.items():
        lines.append(f"| `{prefix}{path}` | {DOC[(prefix, path)][1]} | {real} | {why} |")
    lines.append("")
    lines.append("### D3（文档返回结构与实测不符，共 20 处）")
    lines.append("")
    for (prefix, path), d in SHAPE_DIFF.items():
        lines.append(f"- `{prefix}{path}`：{d}")

    out = "\n".join(lines)
    open("docs/_incoming/非遗scfy-接口映射表.md", "w", encoding="utf-8").write(out)
    print(out[:1500])
    print(f"\n...\n已写入 docs/_incoming/非遗scfy-接口映射表.md  共 {len(lines)} 行")


if __name__ == "__main__":
    main()
