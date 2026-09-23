# -*- coding: utf-8 -*-
"""
第二轮探测：用真实 ID + 修正参数名重测，区分「探测方参数错误」与「系统真实缺陷」。
第一阶段：从列表接口抽取真实 ID
第二阶段：带真实 ID 调详情接口；对首轮 500 接口按修正后的参数名重试
"""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://szbhpt.tsichuan.com/scfy"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get(path, params=None, timeout=12):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, encoding="utf-8")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aioa-probe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return json.loads(r.read(400000).decode("utf-8", "replace"))
    except Exception as e:
        return {"_err": repr(e)[:160]}


def show(tag, j):
    if "_err" in j:
        print(f"  {tag:<40} ERR  {j['_err']}")
        return None
    code = j.get("code")
    if code == 0:
        d = j.get("data")
        if isinstance(d, dict):
            keys = list(d.keys())[:6]
            brief = ", ".join(f"{k}={str(d[k])[:34]}" for k in keys)
        elif isinstance(d, list):
            brief = f"[{len(d)}项] " + str(d[0])[:70] if d else "[]"
        else:
            brief = str(d)[:80]
        print(f"  {tag:<40} OK   code=0 {brief}")
        return d
    else:
        print(f"  {tag:<40} FAIL code={code} {str(j.get('message') or j.get('msg'))[:100]}")
        return None


print("=" * 100)
print("阶段一：抽取真实 ID")
print("=" * 100)

inh = get("/show/inheritor/getInheritorListByArea", {"area": "成都市", "pageSize": 3})
d = show("传承人列表", inh)
INH_ID = None
if d and d.get("dataList"):
    INH_ID = d["dataList"][0].get("id") or d["dataList"][0].get("inheritor_base_id")
    print(f"    -> 真实传承人ID = {INH_ID}  name={d['dataList'][0].get('name')}")

proj = get("/show/project/getProjectListByArea", {"pageSize": 3})
d = show("项目列表", proj)
PROJ_ID = None
if d and d.get("dataList"):
    PROJ_ID = d["dataList"][0].get("project_base_id") or d["dataList"][0].get("id")
    print(f"    -> 真实项目ID = {PROJ_ID}  name={d['dataList'][0].get('project_name')}")

shop = get("/show/shop/shopTable", {"cityName": "成都市"})
d = show("工坊列表", shop)
SHOP_ID = None
if d and d.get("list"):
    SHOP_ID = d["list"][0].get("id")
    print(f"    -> 真实工坊ID = {SHOP_ID}  name={d['list'][0].get('subject_name')}")

travel = get("/show/travel/getRoutesTopFewList", {"topNum": 10})
d = show("旅游线路列表", travel)
TRAVEL_ID = None
if d and d.get("routesTopFewList"):
    TRAVEL_ID = d["routesTopFewList"][0].get("travel_id")
    print(f"    -> 真实线路ID = {TRAVEL_ID}  name={d['routesTopFewList'][0].get('line_name')}")

eco = get("/show/ecologicalArea/getAreasTopFewList", {"topNum": 10})
d = show("保护区列表", eco)
ECO_ID = None
if d and d.get("areasTopFewList"):
    ECO_ID = d["areasTopFewList"][0].get("ecologicalarea_id")
    print(f"    -> 真实保护区ID = {ECO_ID}  name={d['areasTopFewList'][0].get('area_name')}")

nmch = get("/show/travel/getNmchBaseData")
d = show("体验基地列表", nmch)
CITY_CODE = None
if d and d.get("nmchBaseDataList"):
    CITY_CODE = d["nmchBaseDataList"][0].get("city_code")
    print(f"    -> 真实cityCode = {CITY_CODE}")

print()
print("=" * 100)
print("阶段二：真实 ID 调详情接口")
print("=" * 100)
if INH_ID:
    show(f"传承人详情 id={INH_ID}", get("/show/inheritor/getInheritorDetail", {"id": INH_ID}))
    show(f"传承人视频 inheritorId={INH_ID}", get("/show/inheritor/viewVideo", {"inheritorId": INH_ID}))
if PROJ_ID:
    show(f"项目详情 id={PROJ_ID}", get("/show/project/getProjectDetail", {"id": PROJ_ID}))
    show(f"项目视频 projectBaseId={PROJ_ID}", get("/show/project/viewVideo", {"projectBaseId": PROJ_ID}))

print()
print("=" * 100)
print("阶段三：修正参数名重测首轮 500 接口（验证文档参数名是否写错）")
print("=" * 100)

# 文档写 shopId，报错说要 id —— 用 id 重试
if SHOP_ID:
    show("shop/shopDetail 用 id=", get("/show/shop/shopDetail", {"cityName": "成都市", "id": SHOP_ID}))
    show("shop/shopInheritor 用 id=", get("/show/shop/shopInheritor", {"cityName": "成都市", "id": SHOP_ID}))
    show("shop/shopSales 用 id=", get("/show/shop/shopSales", {"cityName": "成都市", "id": SHOP_ID}))
    show("shop/shopProjectTypePieChart 用 id=", get("/show/shop/shopProjectTypePieChart", {"cityName": "成都市", "id": SHOP_ID}))
    show("shop/shopSalesAndNumPieChart 用 id=", get("/show/shop/shopSalesAndNumPieChart", {"cityName": "成都市", "id": SHOP_ID}))
    show("data/shopDetail/{id} 真实id", get(f"/show/data/shopDetail/{SHOP_ID}", {"num": 5}))
    show("data/saleStat shopId真实", get("/show/data/saleStat", {"shopId": SHOP_ID, "cityName": "成都市"}))
    show("data/platSaleStat shopId真实", get("/show/data/platSaleStat", {"shopId": SHOP_ID}))

# 文档说无需参数，报错说要 travelId —— 补 travelId 重试
if TRAVEL_ID:
    show("travel/getTravelRoadTypeCount +travelId", get("/show/travel/getTravelRoadTypeCount", {"travelId": TRAVEL_ID}))
    show("travel/getTravelRoadDistributeData +travelId", get("/show/travel/getTravelRoadDistributeData", {"travelId": TRAVEL_ID}))
    show("travel/getTravelRoadDataByType +travelId", get("/show/travel/getTravelRoadDataByType", {"type": "1", "travelId": TRAVEL_ID}))
    show("travel/getCityRoundByTravelId 真实", get("/show/travel/getCityRoundByTravelId", {"travelId": TRAVEL_ID}))
    show("travel/getTravelRoadData 真实", get("/show/travel/getTravelRoadData", {"travelId": TRAVEL_ID}))
    show("travel/getTravelImageUrl 真实", get("/show/travel/getTravelImageUrl", {"travelId": TRAVEL_ID}))
    show("travel/getAllTravelImageUrl 真实", get("/show/travel/getAllTravelImageUrl", {"travelId": TRAVEL_ID}))

if ECO_ID:
    show("eco/getCityRoundByAreaId 真实", get("/show/ecologicalArea/getCityRoundByAreaId", {"ecologicalAreaId": ECO_ID}))
    show("eco/getAllTravelImageUrl 真实", get("/show/ecologicalArea/getAllTravelImageUrl", {"ecologicalAreaId": ECO_ID}))
    show("eco/getEcologicalAreaRoadData 真实", get("/show/ecologicalArea/getEcologicalAreaRoadData", {"ecologicalAreaId": ECO_ID, "areaId": CITY_CODE or "510100"}))
    show("eco/getRoadDistributeData 真实", get("/show/ecologicalArea/getRoadDistributeData", {"ecologicalAreaId": ECO_ID, "areaId": CITY_CODE or "510100"}))
    show("eco/getNmchBasePopupData 真实", get("/show/ecologicalArea/getNmchBasePopupData", {"cityCode": CITY_CODE or "510100"}))

if CITY_CODE:
    show("travel/getNmchBasePopupData 真实", get("/show/travel/getNmchBasePopupData", {"cityCode": CITY_CODE}))
    show("travel/getTouristCountyData 真实", get("/show/travel/getTouristCountyData", {"area": "成都市"}))

print()
print("=" * 100)
print("阶段四：/show/data/* 复测（首轮报 relation \"t_shop\" does not exist）")
print("=" * 100)
for p, prm in [("/show/data/shopTypeScale", {"cityName": "成都市"}),
               ("/show/data/rightMapDistribution", {}),
               ("/show/data/shopInfos", {"cityName": "成都市"}),
               ("/show/data/leftRectScale", {"cityName": "成都市"})]:
    show(f"{p} {prm}", get(p, prm))
