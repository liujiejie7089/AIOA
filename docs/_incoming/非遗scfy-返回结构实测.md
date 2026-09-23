# scfy 接口返回结构实测表

> 由 `ScfyMatrixTest` 在**真实调用**时采集：环境 `https://szbhpt.tsichuan.com/scfy`，覆盖 55 个接口，只发 GET。
> 机器可读版：`server/aioa-integration-scfy/src/main/resources/scfy/return-shape.json`（`ScfyAgentCatalog` 直接消费它作为「返回结构」）。

口径：`observed` 为本次实测结果。**只有 `OK_DATA` 的行才是真实的返回结构**；`OK_EMPTY` 表示本次调用成功但该条件下无数据，结构无从观测，不得当成「该接口返回空」的结论。

字段表示法：`名:类型`；数组写成 `名[n]:{元素字段}`；`?` 表示实测为空、类型未能观测。

发现的依赖 id：{INH_ID=6df60302-f201-4fee-8758-e93d0e4c3112_country, PROJ_ID=2-UN-1, SHOP_ID=140, TRAVEL_ID=43c4f5188de54c46b2b03094ff1e5da0, ECO_ID=5f199a336e2e44efab9c5541f4138fe9, CITY_CODE=510100000000, COUNTY_CODE=510105000000, ROAD_DATA_ID=05760cdf947f4f32968cf79d3c695b2b}

| 契约 id | 分组 | observed | data | 返回字段 |
|---|---|---|---|---|
| `inheritor_list_by_area` | 传承人 | OK_DATA | object | pageCount:number, pageNumber:number, dataList[n]:{id:string, inheritor_base_id:string, name:string, resume:string, inheritor_level:string, level_name:string}, pageSize:number, totalCount:number |
| `inheritor_detail` | 传承人 | OK_DATA | object | id:string, name:string, inheritor_level:string, unit:string, resume:string, image_url:string |
| `inheritor_type_data` | 传承人 | OK_DATA | object | total:number, data[n]:{name:string, value:number}, projectTypeMap:{folkLiterature:number, traditionalArt:number, quyi:number, sports:number, traditionalDancing:number, folk:number, traditionalOpera:number, medicine:number, traditionalSkills:number, classicalMusic:number}, name:string |
| `inheritor_gender_data` | 传承人 | OK_DATA | object | manCount:number, womanCount:number, totalCount:number |
| `inheritor_birthday_data` | 传承人 | OK_DATA | object | total:number, data[n]:{name:string, value:number} |
| `inheritor_education_data` | 传承人 | OK_DATA | object | country[n]:{name:string, value:number}, province[n]:{name:string, value:number} |
| `inheritor_count_by_area` | 传承人 | OK_DATA | array<object> | id:string, short_name:string, country_inheritor:string, province_inheritor:string, city_inheritor:string, county_inheritor:string, all:string |
| `inheritor_yhwd_data` | 传承人 | OK_DATA | array<object> | id:string, area:string, country_inheritor:string, province_inheritor:string, name:string, all:number |
| `inheritor_video` | 传承人 | OK_DATA | object | exist:boolean, viewUrl:string |
| `project_list_by_area` | 项目 | OK_DATA | object | pageCount:number, pageNumber:number, dataList[n]:{project_base_id:string, project_name:string, project_level:string, level_name:string}, pageSize:number, totalCount:number |
| `project_detail` | 项目 | OK_DATA | object | project_base_id:string, project_name:string, protection_unit:string, project_level:string, pedigree:string, description:string, image_url:string |
| `project_type_data` | 项目 | OK_DATA | object | total:number, data[n]:{name:string, value:number}, projectTypeMap:{folkLiterature:number, traditionalArt:number, quyi:number, sports:number, traditionalDancing:number, folk:number, traditionalOpera:number, medicine:number, traditionalSkills:number, classicalMusic:number}, name:string |
| `project_batch_data` | 项目 | OK_DATA | object | line_province[n]:{name:string, value:number}, bar_country[n]:{name:string, value:number}, bar_province[n]:{name:string, value:number}, line_country[n]:{name:string, value:number} |
| `project_count_by_area` | 项目 | OK_DATA | array<object> | level_name:string, num:number |
| `project_area_summary` | 项目 | OK_DATA | array<object> | id:string, short_name:string, un_project:string, country_project:string, province_project:string, city_project:string, county_project:string, all:string |
| `project_yhwd_data` | 项目 | OK_DATA | array<object> | id:string, area:string, un_project:string, country_project:string, province_project:string, city_project:string, district_project:string, name:string, all:number |
| `project_video` | 项目 | OK_DATA | object | exist:boolean, viewUrl:string |
| `shop_table` | 工坊 | OK_DATA | object | list[n]:{id:string, subject_name:string, num:number, platform_name:string, project_name:string, sales_form:string, sales:number, sales_num:number} |
| `shop_pie_and_stores` | 工坊 | OK_DATA | object | stores:number, pieChartList[n]:{num:number, project_type:string} |
| `shop_category_sum` | 工坊 | OK_DATA | object | offlineSales:number, onlineSales:number, laozihaoZh:number, projectLevelCity:number, onlineEntrust:number, laozihaoSc:number, inheritorLevelCountry:number, inheritorLevelArea:number, inheritorLevelCity:number, projectLevelCountry:number, projectLevelArea:number, onlineJoin:number, inheritorLevelNonRepresentativeness:number, provertyCountyLevelNo:number, offlineSalesNum:number, onlineIndependent:number, onlineOther:number, provertyCountyLevelProvince:number, provertyCountyLevelCounty:number, projectLevelProvince:number, inheritorLevelExpert:number, inheritorLevelProvince:number, onlineSalesNum:number |
| `shop_bar_chart` | 工坊 | OK_DATA | object | list[n]:{num:number, platform_name:string} |
| `shop_map_chart` | 工坊 | OK_DATA | object | type3[n]:{city:string, level:string, account:number}, type2[n]:{city:string, yhwd:string}, type1[n]:{city:string, level:string, account:number} |
| `shop_area_map_chart` | 工坊 | OK_DATA | object | type3[n]:{area:string, level:string, account:number}, type2[n]:{area:string, yhwd:string}, type1[n]:{area:string, level:string, account:number} |
| `shop_sales_and_amount` | 工坊 | OK_DATA | object | salesNum:number, sales:number |
| `shop_detail` | 工坊 | OK_DATA | object | online[n]:{platform_name:string, store_name:string, online_website:string}, introduction:{introduction:string, subject_name:string, sales_form:string, city:string, poverty_county_level:string, project_num:number, user_num:number} |
| `shop_inheritor` | 工坊 | OK_DATA | object | list[n]:{inheritor_img:array, inheritor_img_inch:string, inheritor_name:string, inheritor_sex:string, inheritor_tel:string, inheritor_nation:string, inheritor_level:string, project_type:string, project_name:string, project_level:string} |
| `shop_sales` | 工坊 | OK_DATA | object | online_sales_num:number, sales_num:number, offline_sales:number, offline_sales_num:number, online_sales:number, sales:number |
| `shop_project_type_pie` | 工坊 | OK_DATA | object | list[n]:{num:number, project_type:string} |
| `shop_sales_num_pie` | 工坊 | OK_DATA | object | salesNum[n]:{num:number, platform_name:string}, sales[n]:{num:number, platform_name:string} |
| `shop_address_distribution` | 工坊 | OK_DATA | object | total:{accountLevel1:number, accountLevel2:number, accountLevel3:number, accountLevel4:number, accountType2:number}, type2[n]:{addr_id:string, name:string, level:string, addr:string, type:string, city:string, lng:string, lat:string, texts:array<object>}, type1[n]:{account:number, city:string, level:string} |
| `eco_area_count` | 保护区 | OK_DATA | object | country:string, province:string |
| `eco_area_top_list` | 保护区 | OK_DATA | object | areasTopFewList[n]:{area_name:string, latitude:string, ecologicalarea_id:string, show_index:number, area_level:string, introduction:string, longitude:string} |
| `eco_city_round` | 保护区 | OK_DATA | object | cityPointData[n]:{city_name:string, code:string, latitude:string, city_id:string, longitude:string} |
| `eco_road_data` | 保护区 | OK_DATA | object | projectData:{pageCount:number, pageNumber:number, dataList[n]:{project_base_id:string, latitude:string, imageUrl:string, project_code:string, area_short_name:string, project_level:string, project_name:string, area_id:string, longitude:string}, pageSize:number, totalCount:number}, agglomerationAreaData:{pageCount:number, pageNumber:number, dataList[n]:{area_name:string, latitude:string, area_short_name:string, id:string, introduction:string, longitude:string}, pageSize:number, totalCount:number}, projectLevelData:{country:number, province:number, un:number}, nmchBaseData:{pageCount:number, pageNumber:number, dataList[n]:{?}, pageSize:number, totalCount:number} |
| `eco_road_distribute` | 保护区 | OK_DATA | object | projectData[n]:{?}, agglomerationAreaData[n]:{area_name:string, latitude:string, area_short_name:string, id:string, introduction:string, longitude:string}, nmchBaseData[n]:{?} |
| `eco_all_image` | 保护区 | OK_DATA | object | imageList[n]:{image_data:array<object>, area_short_name:string} |
| `eco_details` | 保护区 | OK_DATA | object | id:string, area_name:string, area_type:string, address:string, introduction:string, image_url:string |
| `eco_nmch_base` | 保护区 | OK_EMPTY | object | nmchBaseDataList[n]:{?} |
| `eco_nmch_popup` | 保护区 | OK_DATA | object | popupDataList[n]:{id:string, base_code:string, base_name:string, longitude:string, latitude:string} |
| `eco_tourist_county_list` | 保护区 | OK_DATA | object | touristCounty[n]:{id:string, short_name:string, longitude:string, latitude:string} |
| `eco_tourist_county_data` | 保护区 | OK_DATA | object | typicalInheritors:{listData[n]:{id:string, inheritor_name:string, inheritor_level:string, area_short_name:string}, provinceNum:number, countryNum:number}, touristUnProject:{listData[n]:{project_base_id:string, project_name:string, project_level:string, area_short_name:string}, num:number}, touristDirectoryProject:{listData[n]:{project_base_id:string, project_name:string, project_level:string, area_short_name:string}, provinceNum:number, countryNum:number} |
| `travel_route_top_list` | 旅游 | OK_DATA | object | routesTopFewList[n]:{travel_id:string, coverPictureUrl:string, line_name:string} |
| `travel_city_round` | 旅游 | OK_DATA | object | cityPointData[n]:{city_name:string, code:string, latitude:string, city_id:string, longitude:string}, centerLatitude:string, coordinateSet:string, centerLongitude:string |
| `travel_road_type_count` | 旅游 | OK_DATA | object | project:string, travelArea:string, base:string |
| `travel_road_by_type` | 旅游 | OK_DATA | object | pageCount:number, pageNumber:number, dataList[n]:{project_base_id:string, latitude:string, project_code:string, area_short_name:string, project_name:string, area_id:string, longitude:string}, pageSize:number, totalCount:number |
| `travel_road_data` | 旅游 | OK_DATA | object | projectData:{pageCount:number, pageNumber:number, dataList[n]:{project_base_id:string, latitude:string, project_code:string, area_short_name:string, project_name:string, area_id:string, longitude:string}, pageSize:number, totalCount:number}, agglomerationAreaData:{pageCount:number, pageNumber:number, dataList[n]:{area_name:string, latitude:string, area_short_name:string, id:string, introduction:string, longitude:string}, pageSize:number, totalCount:number}, nmchBaseData:{pageCount:number, pageNumber:number, dataList[n]:{base_name:string, latitude:string, base_code:string, area_short_name:string, id:string, area_id:string, longitude:string}, pageSize:number, totalCount:number} |
| `travel_road_detail` | 旅游 | OK_DATA | object | protection_unit:string, pedigree:string, project_base_id:string, image_url:string, description:string, project_level:string, project_name:string |
| `travel_road_distribute` | 旅游 | OK_DATA | object | projectData[n]:{project_base_id:string, project_code:string, project_name:string, longitude:string, latitude:string, area_id:string, area_short_name:string}, agglomerationAreaData[n]:{id:string, area_name:string, introduction:string, longitude:string, latitude:string, area_short_name:string}, nmchBaseData[n]:{id:string, base_code:string, base_name:string, longitude:string, latitude:string, area_id:string, area_short_name:string} |
| `travel_image` | 旅游 | OK_DATA | object | imageList[n]:{image_url:string, bizid:string, name:string} |
| `travel_all_image` | 旅游 | OK_DATA | object | imageList[n]:{image_data:array, area_short_name:string, show_index:string, city_id:string} |
| `travel_details` | 旅游 | OK_DATA | object | id:string, area_name:string, area_type:string, address:string, introduction:string, image_url:string |
| `travel_nmch_base` | 旅游 | OK_DATA | object | nmchBaseDataList[n]:{city_code:string, city_name:string, base_num:number, info_list:array<object>} |
| `travel_nmch_popup` | 旅游 | OK_DATA | object | popupDataList[n]:{id:string, base_code:string, base_name:string, longitude:string, latitude:string} |
| `travel_tourist_county_list` | 旅游 | OK_DATA | object | touristCounty[n]:{id:string, short_name:string, longitude:string, latitude:string} |
| `travel_tourist_county_data` | 旅游 | OK_DATA | object | typicalInheritors:{listData[n]:{id:string, inheritor_name:string, inheritor_level:string, area_short_name:string}, provinceNum:number, countryNum:number}, touristUnProject:{listData[n]:{project_base_id:string, project_name:string, project_level:string, area_short_name:string}, num:number}, touristDirectoryProject:{listData[n]:{project_base_id:string, project_name:string, project_level:string, area_short_name:string}, provinceNum:number, countryNum:number} |
