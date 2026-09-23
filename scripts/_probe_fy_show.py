# -*- coding: utf-8 -*-
"""
非遗四川 2023 (scfy) /show/* 接口全量探测器
以接口文档为清单来源，对生产西昌环境实测，记录真实 HTTP 状态与返回结构。
用途：建立「文档声称 vs 实测」的差异基线，为映射表与校验器提供事实依据。
只读探测，不做任何写操作。
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://szbhpt.tsichuan.com/scfy"
TIMEOUT = 12

# (分组, 前缀, 路径, 参数dict, 是否路径参数型)
CASES = [
    # ---- 6.1 传承人 ----
    ("6.1传承人", "/show/inheritor", "/getInheritorListByArea", {"area": "成都市", "pageSize": 5}, False),
    ("6.1传承人", "/show/inheritor", "/getInheritorDetail", {"id": "35412"}, False),
    ("6.1传承人", "/show/inheritor", "/getInheritorTypeData", {"level": "country"}, False),
    ("6.1传承人", "/show/inheritor", "/getGenderNumDataByLevel", {"level": "country"}, False),
    ("6.1传承人", "/show/inheritor", "/getInheritorBirthday", {"level": "country"}, False),
    ("6.1传承人", "/show/inheritor", "/getInheritorWhcd", {"level": "country"}, False),
    ("6.1传承人", "/show/inheritor", "/getAreaInheritorData", {"name": "成都市"}, False),
    ("6.1传承人", "/show/inheritor", "/getYhwdInheritorData", {}, False),
    ("6.1传承人", "/show/inheritor", "/viewVideo", {"inheritorId": "35412"}, False),

    # ---- 6.2 项目 ----
    ("6.2项目", "/show/project", "/getProjectListByArea", {"pageSize": 5}, False),
    ("6.2项目", "/show/project", "/getProjectDetail", {"id": "35412"}, False),
    ("6.2项目", "/show/project", "/getProjectTypeData", {"level": "country"}, False),
    ("6.2项目", "/show/project", "/getProjectBatchData", {"area": "成都市"}, False),
    ("6.2项目", "/show/project", "/getProjectCountByArea", {"area": "成都市"}, False),
    ("6.2项目", "/show/project", "/getAreaProjectData", {"name": "成都市"}, False),
    ("6.2项目", "/show/project", "/getYhwdProjectData", {}, False),
    ("6.2项目", "/show/project", "/viewVideo", {"projectBaseId": "35412"}, False),

    # ---- 6.3 data ----
    ("6.3工坊", "/show/data", "/shopTypeScale", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/data", "/leftRectScale", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/data", "/leftBarScale", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/data", "/rightMapDistribution", {}, False),
    ("6.3工坊", "/show/data", "/shopDetail/35412", {"num": 5}, True),
    ("6.3工坊", "/show/data", "/shopInfos", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/data", "/saleStat", {"shopId": "35412", "cityName": "成都市"}, False),
    ("6.3工坊", "/show/data", "/platSaleStat", {"shopId": "35412"}, False),

    # ---- 6.3 shop ----
    ("6.3工坊", "/show/shop", "/salesAndSalesAmount", {"cityName": "成都市", "areaName": "锦江区"}, False),
    ("6.3工坊", "/show/shop", "/pieChartAndStores", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/categorySum", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/barChart", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/mapChart", {"cityName": "成都市", "areaName": "锦江区"}, False),
    ("6.3工坊", "/show/shop", "/areaMapChart", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/shopTable", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/shopDetail", {"cityName": "成都市", "shopId": "35412"}, False),
    ("6.3工坊", "/show/shop", "/shopInheritor", {"cityName": "成都市", "shopId": "35412"}, False),
    ("6.3工坊", "/show/shop", "/shopSales", {"cityName": "成都市", "shopId": "35412"}, False),
    ("6.3工坊", "/show/shop", "/shopProjectTypePieChart", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/shopSalesAndNumPieChart", {"cityName": "成都市"}, False),
    ("6.3工坊", "/show/shop", "/addrDistribution", {"cityName": "成都市"}, False),

    # ---- 6.3 shopv2 ----
    ("6.3工坊v2", "/show/shopv2", "/shopTable", {"cityName": "成都市"}, False),
    ("6.3工坊v2", "/show/shopv2", "/pieChartAndStores", {"cityName": "成都市"}, False),

    # ---- 6.4 生态保护区 ----
    ("6.4保护区", "/show/ecologicalArea", "/getAreasNum", {}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getAreasTopFewList", {"topNum": 10}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getCityRoundByAreaId", {"ecologicalAreaId": "1"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getEcologicalAreaRoadData", {"ecologicalAreaId": "1", "areaId": "510100"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getRoadDistributeData", {"ecologicalAreaId": "1", "areaId": "510100"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getEcologicalAreaImageUrl", {"ecologicalAreaId": "1", "areaId": "510100", "type": "1", "dataId": "1"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getAllTravelImageUrl", {"ecologicalAreaId": "1"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getPagerTravelImageUrl", {"ecologicalAreaId": "1"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getDetailsData", {"type": "1", "dataId": "1"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getNmchBaseData", {}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getNmchBasePopupData", {"cityCode": "510100"}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getTouristCountyList", {}, False),
    ("6.4保护区", "/show/ecologicalArea", "/getTouristCountyData", {"area": "成都市"}, False),

    # ---- 6.5 旅游线路 ----
    ("6.5旅游", "/show/travel", "/getRoutesTopFewList", {"topNum": 10}, False),
    ("6.5旅游", "/show/travel", "/getCityRoundByTravelId", {"travelId": "1"}, False),
    ("6.5旅游", "/show/travel", "/getTravelRoadTypeCount", {}, False),
    ("6.5旅游", "/show/travel", "/getTravelRoadDataByType", {"type": "1"}, False),
    ("6.5旅游", "/show/travel", "/getTravelRoadData", {"travelId": "1"}, False),
    ("6.5旅游", "/show/travel", "/getTravelRoadDataDetail", {"dataId": "1", "type": "1"}, False),
    ("6.5旅游", "/show/travel", "/getTravelRoadDistributeData", {}, False),
    ("6.5旅游", "/show/travel", "/getTravelImageUrl", {"travelId": "1"}, False),
    ("6.5旅游", "/show/travel", "/getAllTravelImageUrl", {"travelId": "1"}, False),
    ("6.5旅游", "/show/travel", "/getDetailsData", {"type": "1", "dataId": "1"}, False),
    ("6.5旅游", "/show/travel", "/getNmchBaseData", {}, False),
    ("6.5旅游", "/show/travel", "/getNmchBasePopupData", {"cityCode": "510100"}, False),
    ("6.5旅游", "/show/travel", "/getTouristCountyList", {}, False),
    ("6.5旅游", "/show/travel", "/getTouristCountyData", {"area": "成都市"}, False),
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def probe(item):
    group, prefix, path, params, is_path = item
    url = BASE + prefix + path
    if params and not is_path:
        url = url + "?" + urllib.parse.urlencode(params, encoding="utf-8")
    t0 = time.time()
    rec = {"group": group, "prefix": prefix, "path": path, "params": params, "url": url}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aioa-probe/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
            raw = r.read(400000).decode("utf-8", "replace")
            rec["http"] = r.status
            rec["ctype"] = r.headers.get("Content-Type", "")
            rec["ms"] = int((time.time() - t0) * 1000)
            rec["body"] = raw[:2000]
            try:
                j = json.loads(raw)
                rec["json"] = True
                rec["code"] = j.get("code")
                rec["shape"] = describe(j.get("data"))
            except Exception as ex:
                rec["json"] = False
                rec["shape"] = f"非JSON({type(ex).__name__})"
    except urllib.error.HTTPError as e:
        rec["http"] = e.code
        rec["ms"] = int((time.time() - t0) * 1000)
        rec["body"] = e.read(300).decode("utf-8", "replace")
        rec["json"] = False
    except Exception as e:
        rec["http"] = -1
        rec["ms"] = int((time.time() - t0) * 1000)
        rec["err"] = repr(e)[:200]
    return rec


def describe(d, depth=0):
    if depth > 2:
        return "..."
    if isinstance(d, dict):
        return "{" + ", ".join(f"{k}:{describe(v, depth+1)}" for k, v in list(d.items())[:8]) + "}"
    if isinstance(d, list):
        if not d:
            return "[]"
        return f"[{describe(d[0], depth+1)}] x{len(d)}"
    return type(d).__name__


def main():
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(probe, CASES))
    results.sort(key=lambda r: (r["group"], r["path"]))
    with open("docs/_incoming/probe_show_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok = [r for r in results if r.get("http") == 200]
    print(f"总计 {len(results)} 个接口 | HTTP200={len(ok)} | 非200={len(results)-len(ok)}\n")
    print(f"{'分组':<10} {'状态':<5} {'code':<6} {'路径':<34} {'返回结构'}")
    print("-" * 118)
    for r in results:
        h = r.get("http")
        code = r.get("code", "")
        shape = r.get("shape") or (r.get("body", "")[:46].replace("\n", " "))
        print(f"{r['group']:<10} {h:<5} {str(code):<6} {r['path']:<34} {shape}")
    print()
    print("=== 非 200 / 异常明细 ===")
    for r in results:
        if r.get("http") != 200:
            print(f"[{r['http']}] {r['path']} params={r['params']}")
            print(f"     {r.get('body') or r.get('err','')[:150]}")
    print(f"\n明细已写入 docs/_incoming/probe_show_result.json")


if __name__ == "__main__":
    main()
