# scfy 端到端只读矩阵报告（契约全部可用接口逐个真实调用）

> 生成方式：`server/aioa-integration-scfy` 的 `ScfyMatrixTest`，`mvn -pl aioa-integration-scfy test -Dtest=ScfyMatrixTest -Dscfy.matrix=true`。
> 环境：`https://szbhpt.tsichuan.com/scfy`。只发 GET，无写操作。

状态口径：`OK_DATA` 调用成功且返回非空 ｜ `OK_EMPTY` 调用成功但该筛选条件下无数据 ｜ `FAIL` 调用失败（含对方系统缺陷） ｜ `MISSING_REQUIRED` 矩阵参数没备齐（矩阵自身问题）

发现的依赖 id：{INH_ID=6df60302-f201-4fee-8758-e93d0e4c3112_country, PROJ_ID=2-UN-1, SHOP_ID=140, TRAVEL_ID=43c4f5188de54c46b2b03094ff1e5da0, ECO_ID=5f199a336e2e44efab9c5541f4138fe9, CITY_CODE=510100000000, COUNTY_CODE=510105000000, ROAD_DATA_ID=05760cdf947f4f32968cf79d3c695b2b}

## 汇总

| 分组 | 接口数 | 有数据 | 空集 | 失败 |
|---|---|---|---|---|
| 传承人 | 9 | 9 | 0 | 0 |
| 保护区 | 11 | 10 | 1 | 0 |
| 工坊 | 13 | 13 | 0 | 0 |
| 旅游 | 14 | 14 | 0 | 0 |
| 项目 | 8 | 8 | 0 | 0 |
| **合计** | **55** | 54 | 1 | 0 |

## 传承人

| 契约 id | 路径 | 调用参数 | 结果 | code | 叶子值 | 说明 |
|---|---|---|---|---|---|---|
| `inheritor_list_by_area` | `/show/inheritor/getInheritorListByArea` | `{area=成都市, pageSize=5}` | OK_DATA |  | 34 |  |
| `inheritor_detail` | `/show/inheritor/getInheritorDetail` | `{id=6df60302-f201-4fee-8758-e93d0e4c3112_country}` | OK_DATA |  | 6 |  |
| `inheritor_type_data` | `/show/inheritor/getInheritorTypeData` | `{level=country}` | OK_DATA |  | 32 |  |
| `inheritor_gender_data` | `/show/inheritor/getGenderNumDataByLevel` | `{level=country}` | OK_DATA |  | 3 |  |
| `inheritor_birthday_data` | `/show/inheritor/getInheritorBirthday` | `{level=country}` | OK_DATA |  | 13 |  |
| `inheritor_education_data` | `/show/inheritor/getInheritorWhcd` | `{level=country}` | OK_DATA |  | 20 |  |
| `inheritor_count_by_area` | `/show/inheritor/getAreaInheritorData` | `{}` | OK_DATA |  | 161 |  |
| `inheritor_yhwd_data` | `/show/inheritor/getYhwdInheritorData` | `{}` | OK_DATA |  | 36 |  |
| `inheritor_video` | `/show/inheritor/viewVideo` | `{inheritorId=6df60302-f201-4fee-8758-e93d0e4c3112_country}` | OK_DATA |  | 2 |  |

## 保护区

| 契约 id | 路径 | 调用参数 | 结果 | code | 叶子值 | 说明 |
|---|---|---|---|---|---|---|
| `eco_area_count` | `/show/ecologicalArea/getAreasNum` | `{}` | OK_DATA |  | 2 |  |
| `eco_area_top_list` | `/show/ecologicalArea/getAreasTopFewList` | `{topNum=10}` | OK_DATA |  | 49 |  |
| `eco_city_round` | `/show/ecologicalArea/getCityRoundByAreaId` | `{ecologicalAreaId=5f199a336e2e44efab9c5541f4138fe9}` | OK_DATA |  | 35 |  |
| `eco_road_data` | `/show/ecologicalArea/getEcologicalAreaRoadData` | `{ecologicalAreaId=5f199a336e2e44efab9c5541f4138fe9, areaId=510100000000}` | OK_DATA |  | 111 |  |
| `eco_road_distribute` | `/show/ecologicalArea/getRoadDistributeData` | `{ecologicalAreaId=5f199a336e2e44efab9c5541f4138fe9, areaId=510100000000}` | OK_DATA |  | 6 |  |
| `eco_all_image` | `/show/ecologicalArea/getAllTravelImageUrl` | `{ecologicalAreaId=5f199a336e2e44efab9c5541f4138fe9}` | OK_DATA |  | 123 |  |
| `eco_details` | `/show/ecologicalArea/getDetailsData` | `{type=1, dataId=1}` | OK_DATA |  | 6 |  |
| `eco_nmch_base` | `/show/ecologicalArea/getNmchBaseData` | `{}` | OK_EMPTY |  | 0 |  |
| `eco_nmch_popup` | `/show/ecologicalArea/getNmchBasePopupData` | `{cityCode=510100000000}` | OK_DATA |  | 150 |  |
| `eco_tourist_county_list` | `/show/ecologicalArea/getTouristCountyList` | `{}` | OK_DATA |  | 112 |  |
| `eco_tourist_county_data` | `/show/ecologicalArea/getTouristCountyData` | `{area=510105000000}` | OK_DATA |  | 357 |  |

## 工坊

| 契约 id | 路径 | 调用参数 | 结果 | code | 叶子值 | 说明 |
|---|---|---|---|---|---|---|
| `shop_table` | `/show/shop/shopTable` | `{cityName=成都市}` | OK_DATA |  | 400 |  |
| `shop_pie_and_stores` | `/show/shop/pieChartAndStores` | `{cityName=成都市}` | OK_DATA |  | 9 |  |
| `shop_category_sum` | `/show/shop/categorySum` | `{cityName=成都市}` | OK_DATA |  | 23 |  |
| `shop_bar_chart` | `/show/shop/barChart` | `{cityName=成都市}` | OK_DATA |  | 16 |  |
| `shop_map_chart` | `/show/shop/mapChart` | `{cityName=成都市, areaName=锦江区}` | OK_DATA |  | 26 |  |
| `shop_area_map_chart` | `/show/shop/areaMapChart` | `{cityName=成都市}` | OK_DATA |  | 191 |  |
| `shop_sales_and_amount` | `/show/shop/salesAndSalesAmount` | `{cityName=成都市, areaName=锦江区}` | OK_DATA |  | 2 |  |
| `shop_detail` | `/show/shop/shopDetail` | `{cityName=成都市, id=140}` | OK_DATA |  | 10 |  |
| `shop_inheritor` | `/show/shop/shopInheritor` | `{cityName=成都市, id=140}` | OK_DATA |  | 18 |  |
| `shop_sales` | `/show/shop/shopSales` | `{cityName=成都市, id=140}` | OK_DATA |  | 6 |  |
| `shop_project_type_pie` | `/show/shop/shopProjectTypePieChart` | `{cityName=成都市, id=140}` | OK_DATA |  | 2 |  |
| `shop_sales_num_pie` | `/show/shop/shopSalesAndNumPieChart` | `{cityName=成都市, id=140}` | OK_DATA |  | 4 |  |
| `shop_address_distribution` | `/show/shop/addrDistribution` | `{cityName=成都市}` | OK_DATA |  | 325 |  |

## 旅游

| 契约 id | 路径 | 调用参数 | 结果 | code | 叶子值 | 说明 |
|---|---|---|---|---|---|---|
| `travel_route_top_list` | `/show/travel/getRoutesTopFewList` | `{topNum=10}` | OK_DATA |  | 30 |  |
| `travel_city_round` | `/show/travel/getCityRoundByTravelId` | `{travelId=43c4f5188de54c46b2b03094ff1e5da0}` | OK_DATA |  | 43 |  |
| `travel_road_type_count` | `/show/travel/getTravelRoadTypeCount` | `{travelId=43c4f5188de54c46b2b03094ff1e5da0}` | OK_DATA |  | 3 |  |
| `travel_road_by_type` | `/show/travel/getTravelRoadDataByType` | `{type=1, travelId=43c4f5188de54c46b2b03094ff1e5da0}` | OK_DATA |  | 74 |  |
| `travel_road_data` | `/show/travel/getTravelRoadData` | `{travelId=43c4f5188de54c46b2b03094ff1e5da0}` | OK_DATA |  | 212 |  |
| `travel_road_detail` | `/show/travel/getTravelRoadDataDetail` | `{dataId=05760cdf947f4f32968cf79d3c695b2b, type=1}` | OK_DATA |  | 7 |  |
| `travel_road_distribute` | `/show/travel/getTravelRoadDistributeData` | `{travelId=43c4f5188de54c46b2b03094ff1e5da0}` | OK_DATA |  | 709 |  |
| `travel_image` | `/show/travel/getTravelImageUrl` | `{travelId=43c4f5188de54c46b2b03094ff1e5da0, type=2}` | OK_DATA |  | 150 |  |
| `travel_all_image` | `/show/travel/getAllTravelImageUrl` | `{travelId=43c4f5188de54c46b2b03094ff1e5da0}` | OK_DATA |  | 24 |  |
| `travel_details` | `/show/travel/getDetailsData` | `{type=1, dataId=1}` | OK_DATA |  | 6 |  |
| `travel_nmch_base` | `/show/travel/getNmchBaseData` | `{}` | OK_DATA |  | 405 |  |
| `travel_nmch_popup` | `/show/travel/getNmchBasePopupData` | `{cityCode=510100000000}` | OK_DATA |  | 150 |  |
| `travel_tourist_county_list` | `/show/travel/getTouristCountyList` | `{}` | OK_DATA |  | 112 |  |
| `travel_tourist_county_data` | `/show/travel/getTouristCountyData` | `{area=510105000000}` | OK_DATA |  | 249 |  |

## 项目

| 契约 id | 路径 | 调用参数 | 结果 | code | 叶子值 | 说明 |
|---|---|---|---|---|---|---|
| `project_list_by_area` | `/show/project/getProjectListByArea` | `{pageSize=5}` | OK_DATA |  | 24 |  |
| `project_detail` | `/show/project/getProjectDetail` | `{id=2-UN-1}` | OK_DATA |  | 7 |  |
| `project_type_data` | `/show/project/getProjectTypeData` | `{level=country}` | OK_DATA |  | 32 |  |
| `project_batch_data` | `/show/project/getProjectBatchData` | `{area=成都市}` | OK_DATA |  | 64 |  |
| `project_count_by_area` | `/show/project/getProjectCountByArea` | `{area=成都市}` | OK_DATA |  | 6 |  |
| `project_area_summary` | `/show/project/getAreaProjectData` | `{}` | OK_DATA |  | 184 |  |
| `project_yhwd_data` | `/show/project/getYhwdProjectData` | `{}` | OK_DATA |  | 54 |  |
| `project_video` | `/show/project/viewVideo` | `{projectBaseId=2-UN-1}` | OK_DATA |  | 2 |  |

## 需要处理的失败项

无 —— 全部可用接口均调用成功。
