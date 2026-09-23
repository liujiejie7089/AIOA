# 非遗四川 2023（scfy）接口映射表 —— 文档声称 vs 生产实测

> 生成方式：`scripts/_gen_fy_map.py` 合并「接口文档表格」与「生产西昌环境实测结果」自动产出，不手抄。
> 实测环境：`https://szbhpt.tsichuan.com/scfy`（唯一可达环境）。探测器：`scripts/_probe_fy_show.py`、`_probe_fy_show2.py`。
> 实测时间：2026-09-23

**状态图例**：`OK` 实测 code=0 且有数据 ｜ `空` code=0 但 data 为空 ｜ `❌缺陷` 生产库报错 ｜ `⚠️文档错` 文档参数/结构与实测不符


## 6.3工坊　`/show/data`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/leftBarScale` | cityName | cityName | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/leftRectScale` | cityName | cityName | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/platSaleStat` | shopId | shopId | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/rightMapDistribution` | — | — | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/saleStat` | shopId | shopId | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/shopDetail/35412` | id(路径) | id(路径) | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/shopInfos` | cityName | cityName | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |
| `/shopTypeScale` | — | — | 200/500 | `后端 SQL 异常：`relation "t_shop" does not exist`（Kingbase8）` | ❌缺陷 |

## 6.4保护区　`/show/ecologicalArea`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/getAllTravelImageUrl` | ecologicalAreaId | ecologicalAreaId | 200/0 | `{imageList:[]}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{images:{}}`，实测 `{imageList:[]}`** | |
| `/getAreasNum` | — | — | 200/0 | `{country:str, province:str}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{total:18}`，实测 `{country:"1", province:"6"}`（字符串值）** | |
| `/getAreasTopFewList` | — | — | 200/0 | `{areasTopFewList:[{ecologicalarea_id:..., area_name:..., area_level:..., la…` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `[{id,name,areaCount}]`，实测多一层 `{areasTopFewList:[{ecologicalarea_id, area_name, area_level,...}]}`** | |
| `/getCityRoundByAreaId` | ecologicalAreaId | ecologicalAreaId | 200/0 | `{cityPointData:[]}` | OK |
| `/getDetailsData` | type,dataId | type,dataId | 200/0 | `{id:str, area_name:str, area_type:str, address:str, introduction:str, image…` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{name,intro,images}`，实测 `{id, area_name, area_type, address, introduction, image_url}`** | |
| `/getEcologicalAreaImageUrl` | ecologicalAreaId,areaId,type,dataId | ecologicalAreaId,areaId,type,dataId | 200/0 | `{imageList:[]}` | OK |
| `/getEcologicalAreaRoadData` | ecologicalAreaId,areaId | ecologicalAreaId,areaId | 200/0 | `{projectData:{pageCount:int, pageNumber:int, dataList:[], pageSize:int, tot…` | OK |
| `/getNmchBaseData` | — | — | 200/0 | `{nmchBaseDataList:[]}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{list:[...]}`，实测 `{nmchBaseDataList:[]}`（该前缀下为空；/show/travel 下 21 条）** | |
| `/getNmchBasePopupData` | cityCode | cityCode | 200/0 | `{popupDataList:[]}` | OK |
| `/getPagerTravelImageUrl` | ecologicalAreaId | ecologicalAreaId | 200/0 | `{pager:{pageNumber:int, pageSize:int, totalCount:int, pageCount:int, proper…` | OK |
| ↳ 返回差异 | | | | **⚠️ 实测只返回 `{pager:{...}}`，**无数据列表字段** —— 疑似缺陷** | |
| `/getRoadDistributeData` | ecologicalAreaId,areaId | ecologicalAreaId,areaId | 200/0 | `{projectData:[], agglomerationAreaData:[], nmchBaseData:[]}` | OK |
| `/getTouristCountyData` | area | area | 200/0 | `{typicalInheritors:{listData:[], provinceNum:int, countryNum:int}, touristU…` | OK |
| `/getTouristCountyList` | — | — | 200/0 | `{touristCounty:[{id:..., short_name:..., longitude:..., latitude:...}] x28}` | OK |

## 6.1传承人　`/show/inheritor`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/getAreaInheritorData` | name | name | 200/0 | `[{id:str, short_name:str, country_inheritor:str, province_inheritor:str, ci…` | OK |
| ↳ 返回差异 | | | | **文档过简：实测 22 个市州 × {country_inheritor, province_inheritor, city_inheritor, county_inheritor, all}** | |
| `/getGenderNumDataByLevel` | level | level | 200/0 | `{manCount:int, womanCount:int, totalCount:int}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{male,female}`，实测 `{manCount, womanCount, totalCount}`** | |
| `/getInheritorBirthday` | level | level | 200/0 | `{total:int, data:[{name:..., value:...}] x6}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `[{decade,count}]`，实测 `{total, data:[{name,value}]}`** | |
| `/getInheritorDetail` | id | id | 200/0 | `{}` | 空（需真实ID） |
| `/getInheritorListByArea` | area | area | 200/0 | `{pageCount:int, pageNumber:int, dataList:[{id:..., inheritor_base_id:..., n…` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{list,total}`，实测 `{pageCount, pageNumber, dataList, pageSize, totalCount}`** | |
| `/getInheritorTypeData` | level | level | 200/0 | `{total:int, data:[{name:..., value:...}] x10, projectTypeMap:{folkLiteratur…` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说返回传承人等级分布，实测返回**项目类别**分布（民间文学/传统音乐/传统技艺…），且与 /show/project/getProjectTypeData 结构完全相同** | |
| `/getInheritorWhcd` | level | level | 200/0 | `{country:[{name:..., value:...}] x5, province:[{name:..., value:...}] x5}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `[{name,value}]`，实测 `{country:[...], province:[...]}` 两组** | |
| `/getYhwdInheritorData` | — | — | 200/0 | `[{id:str, area:str, country_inheritor:str, province_inheritor:str, name:str…` | OK |
| `/viewVideo` | inheritorId | inheritorId | 200/0 | `{exist:bool, viewUrl:str}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{videoUrl,coverUrl}`，实测 `{exist:bool, viewUrl:str}`** | |

## 6.2项目　`/show/project`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/getAreaProjectData` | name | name | 200/0 | `[{id:str, short_name:str, un_project:str, country_project:str, province_pro…` | OK |
| `/getProjectBatchData` | area | area | 200/0 | `{line_province:[{name:..., value:...}] x8, bar_country:[{name:..., value:..…` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `[{batch,count}]`，实测 `{line_province, bar_country, bar_province, line_country}` 四数组** | |
| `/getProjectCountByArea` | area | area | 200/0 | `[{level_name:str, num:int}] x3` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{count}`，实测 `[{level_name, num}] x3`** | |
| `/getProjectDetail` | id | id | 200/0 | `{}` | 空（需真实ID） |
| `/getProjectListByArea` | area | area（实测可省，默认全省） | 200/0 | `{pageCount:int, pageNumber:int, dataList:[{project_base_id:..., project_nam…` | OK |
| ↳ 校正 | | | | **文档标 area 必填，实测不传 area 返回全省 1411 条（code=0）** | |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{list,total}`，实测 `{pageCount, pageNumber, dataList, pageSize, totalCount}`** | |
| `/getProjectTypeData` | level | level | 200/0 | `{total:int, data:[{name:..., value:...}] x10, projectTypeMap:{folkLiteratur…` | OK |
| `/getYhwdProjectData` | — | — | 200/0 | `[{id:str, area:str, un_project:str, country_project:str, province_project:s…` | OK |
| `/viewVideo` | projectBaseId | projectBaseId | 200/0 | `{exist:bool, viewUrl:str}` | OK |

## 6.3工坊　`/show/shop`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/addrDistribution` | cityName | cityName | 200/0 | `{total:{accountLevel1:int, accountLevel2:int, accountLevel3:int, accountLev…` | OK |
| `/areaMapChart` | cityName | cityName | 200/0 | `{type3:[{area:..., level:..., account:...}] x28, type2:[{area:..., yhwd:...…` | OK |
| `/barChart` | cityName | cityName | 200/0 | `{list:[{num:..., platform_name:...}] x8}` | OK |
| `/categorySum` | cityName | cityName | 200/0 | `{offlineSales:float, onlineSales:float, laozihaoZh:int, projectLevelCity:in…` | OK |
| `/mapChart` | cityName,areaName | cityName,areaName | 200/0 | `{type3:[{city:..., level:..., account:...}] x4, type2:[{city:..., yhwd:...}…` | OK |
| `/pieChartAndStores` | cityName | cityName | 200/0 | `{stores:int, pieChartList:[{num:..., project_type:...}] x4}` | OK |
| `/salesAndSalesAmount` | cityName,areaName | cityName,areaName | 200/0 | `{salesNum:int, sales:int}` | OK |
| `/shopDetail` | cityName,shopId | cityName, **id** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档写 `shopId`，实际必填 `id`（传 shopId 报 Required String parameter 'id' is not present）** | |
| `/shopInheritor` | cityName,shopId | cityName, **id** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档写 `shopId`，实际必填 `id`** | |
| `/shopProjectTypePieChart` | cityName | cityName, **id** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档漏标：除 cityName 外实际还必填 `id`** | |
| `/shopSales` | cityName,shopId | cityName, **id** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档写 `shopId`，实际必填 `id`** | |
| `/shopSalesAndNumPieChart` | cityName | cityName, **id** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档漏标：除 cityName 外实际还必填 `id`** | |
| `/shopTable` | cityName | cityName | 200/0 | `{list:[{id:..., subject_name:..., num:..., platform_name:..., project_name:…` | OK |

## 6.3工坊v2　`/show/shopv2`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/pieChartAndStores` | cityName | cityName | 200/0 | `{stores:int, pieChartList:[{num:..., project_type:...}] x4}` | OK |
| `/shopTable` | cityName | cityName | 200/0 | `{list:[{id:..., subject_name:..., num:..., platform_name:..., project_name:…` | OK |

## 6.5旅游　`/show/travel`

| 路径 | 文档必填 | 实测必填 | 实测 HTTP/code | 实测返回结构 | 状态 |
|---|---|---|---|---|---|
| `/getAllTravelImageUrl` | travelId | travelId | 200/0 | `{imageList:[]}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{images:{}}`，实测 `{imageList:[]}`** | |
| `/getCityRoundByTravelId` | travelId | travelId | 200/500 | `str` | ⚠️文档错 |
| `/getDetailsData` | type,dataId | type,dataId | 200/0 | `{id:str, area_name:str, area_type:str, address:str, introduction:str, image…` | OK |
| `/getNmchBaseData` | — | — | 200/0 | `{nmchBaseDataList:[{city_code:..., city_name:..., base_num:..., info_list:.…` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `{list}`，实测 `{nmchBaseDataList:[{city_code, city_name, base_num, info_list}]}`** | |
| `/getNmchBasePopupData` | cityCode | cityCode | 200/0 | `{popupDataList:[]}` | OK |
| `/getRoutesTopFewList` | — | — | 200/0 | `{routesTopFewList:[{travel_id:..., line_name:..., coverPictureUrl:...}] x10}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `[{id,name,type}]`，实测多一层 `{routesTopFewList:[{travel_id, line_name, coverPictureUrl}]}`** | |
| `/getTouristCountyData` | area | area | 200/0 | `{typicalInheritors:{listData:[], provinceNum:int, countryNum:int}, touristU…` | OK |
| `/getTouristCountyList` | — | — | 200/0 | `{touristCounty:[{id:..., short_name:..., longitude:..., latitude:...}] x28}` | OK |
| ↳ 返回差异 | | | | **⚠️ 文档说 `[{id,name}]`，实测多一层 `{touristCounty:[{id, short_name, longitude, latitude}]}`** | |
| `/getTravelImageUrl` | travelId | travelId | 200/0 | `{imageList:[]}` | OK |
| `/getTravelRoadData` | travelId | travelId | 200/0 | `{projectData:{pageCount:int, pageNumber:int, dataList:[], pageSize:int, tot…` | OK |
| `/getTravelRoadDataByType` | type | type, **travelId** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档只标 `type`，实际还必填 `travelId`** | |
| `/getTravelRoadDataDetail` | dataId,type | dataId,type | 200/0 | `{}` | 空（需真实ID） |
| `/getTravelRoadDistributeData` | — | **travelId** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档标「必填：—」，实际必填 `travelId`** | |
| `/getTravelRoadTypeCount` | — | **travelId** | 200/500 | `str` | ⚠️文档错 |
| ↳ 校正 | | | | **文档标「必填：—」，实际必填 `travelId`** | |


## 缺陷汇总

### D1（被接入系统生产缺陷，非文档问题）

`/show/data/*` 全系 8 个接口在生产西昌返回 `code=500`：

```
ERROR: relation "t_shop" does not exist
  Position: 58  (Kingbase8 / 人大金仓)
```

涉及：`shopTypeScale` `leftRectScale` `leftBarScale` `rightMapDistribution` `shopDetail/{id}` `shopInfos` `saleStat` `platSaleStat`

已用真实工坊 ID（140 成都宋西平漆艺）复测，仍 500 ⇒ 与参数无关，是**生产库缺表/schema 不一致**。
对照：同栏目 `/show/shop/*` 用 `id` 可正常返回工坊数据 ⇒ 工坊数据存在，是 `/show/data/*` 这套 Controller 查的老表不在当前 schema。

### D2（接口文档参数错误/漏标，共 8 处）

| 接口 | 文档写 | 实际 | 证据 |
|---|---|---|---|
| `/show/shop/shopDetail` | cityName,shopId | cityName, **id** | 文档写 `shopId`，实际必填 `id`（传 shopId 报 Required String parameter 'id' is not present） |
| `/show/shop/shopInheritor` | cityName,shopId | cityName, **id** | 文档写 `shopId`，实际必填 `id` |
| `/show/shop/shopSales` | cityName,shopId | cityName, **id** | 文档写 `shopId`，实际必填 `id` |
| `/show/shop/shopProjectTypePieChart` | cityName | cityName, **id** | 文档漏标：除 cityName 外实际还必填 `id` |
| `/show/shop/shopSalesAndNumPieChart` | cityName | cityName, **id** | 文档漏标：除 cityName 外实际还必填 `id` |
| `/show/travel/getTravelRoadTypeCount` | — | **travelId** | 文档标「必填：—」，实际必填 `travelId` |
| `/show/travel/getTravelRoadDistributeData` | — | **travelId** | 文档标「必填：—」，实际必填 `travelId` |
| `/show/travel/getTravelRoadDataByType` | type | type, **travelId** | 文档只标 `type`，实际还必填 `travelId` |
| `/show/project/getProjectListByArea` | area | area（实测可省，默认全省） | 文档标 area 必填，实测不传 area 返回全省 1411 条（code=0） |

### D3（文档返回结构与实测不符，共 20 处）

- `/show/inheritor/getInheritorTypeData`：⚠️ 文档说返回传承人等级分布，实测返回**项目类别**分布（民间文学/传统音乐/传统技艺…），且与 /show/project/getProjectTypeData 结构完全相同
- `/show/ecologicalArea/getAreasNum`：⚠️ 文档说 `{total:18}`，实测 `{country:"1", province:"6"}`（字符串值）
- `/show/inheritor/getGenderNumDataByLevel`：⚠️ 文档说 `{male,female}`，实测 `{manCount, womanCount, totalCount}`
- `/show/inheritor/getInheritorBirthday`：⚠️ 文档说 `[{decade,count}]`，实测 `{total, data:[{name,value}]}`
- `/show/inheritor/getInheritorWhcd`：⚠️ 文档说 `[{name,value}]`，实测 `{country:[...], province:[...]}` 两组
- `/show/inheritor/getAreaInheritorData`：文档过简：实测 22 个市州 × {country_inheritor, province_inheritor, city_inheritor, county_inheritor, all}
- `/show/inheritor/viewVideo`：⚠️ 文档说 `{videoUrl,coverUrl}`，实测 `{exist:bool, viewUrl:str}`
- `/show/project/getProjectCountByArea`：⚠️ 文档说 `{count}`，实测 `[{level_name, num}] x3`
- `/show/project/getProjectBatchData`：⚠️ 文档说 `[{batch,count}]`，实测 `{line_province, bar_country, bar_province, line_country}` 四数组
- `/show/ecologicalArea/getAreasTopFewList`：⚠️ 文档说 `[{id,name,areaCount}]`，实测多一层 `{areasTopFewList:[{ecologicalarea_id, area_name, area_level,...}]}`
- `/show/ecologicalArea/getNmchBaseData`：⚠️ 文档说 `{list:[...]}`，实测 `{nmchBaseDataList:[]}`（该前缀下为空；/show/travel 下 21 条）
- `/show/ecologicalArea/getAllTravelImageUrl`：⚠️ 文档说 `{images:{}}`，实测 `{imageList:[]}`
- `/show/ecologicalArea/getDetailsData`：⚠️ 文档说 `{name,intro,images}`，实测 `{id, area_name, area_type, address, introduction, image_url}`
- `/show/ecologicalArea/getPagerTravelImageUrl`：⚠️ 实测只返回 `{pager:{...}}`，**无数据列表字段** —— 疑似缺陷
- `/show/travel/getRoutesTopFewList`：⚠️ 文档说 `[{id,name,type}]`，实测多一层 `{routesTopFewList:[{travel_id, line_name, coverPictureUrl}]}`
- `/show/travel/getAllTravelImageUrl`：⚠️ 文档说 `{images:{}}`，实测 `{imageList:[]}`
- `/show/travel/getNmchBaseData`：⚠️ 文档说 `{list}`，实测 `{nmchBaseDataList:[{city_code, city_name, base_num, info_list}]}`
- `/show/travel/getTouristCountyList`：⚠️ 文档说 `[{id,name}]`，实测多一层 `{touristCounty:[{id, short_name, longitude, latitude}]}`
- `/show/inheritor/getInheritorListByArea`：⚠️ 文档说 `{list,total}`，实测 `{pageCount, pageNumber, dataList, pageSize, totalCount}`
- `/show/project/getProjectListByArea`：⚠️ 文档说 `{list,total}`，实测 `{pageCount, pageNumber, dataList, pageSize, totalCount}`