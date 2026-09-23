# -*- coding: utf-8 -*-
"""
矩阵跑完后暴露的三个待判问题，逐个用真实请求定性（只发 GET）：
  Q1 getTouristCountyData 的 area 到底收「市州简称」还是「区县名」？
     —— 契约里 area 的枚举是 21 个市州简称，若真实系统收区县，则校验器在拦合法调用。
  Q2 travel/getTravelImageUrl 返回空，而同前缀 getAllTravelImageUrl 返回 24 条 ——
     单图接口是否还需要 type？type 取什么值？
  Q3 getTravelRoadDataDetail / getEcologicalAreaImageUrl 用 dataId=1 为空 ——
     真实 dataId 应从列表接口取；确认列表里能取到 id 的结构。
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://szbhpt.tsichuan.com/scfy"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get(path, params=None, timeout=15):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, encoding="utf-8")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aioa-probe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return json.loads(r.read(400000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read(200000).decode("utf-8", "replace"))
        except Exception:
            return {"_err": f"HTTP {e.code}"}
    except Exception as e:
        return {"_err": repr(e)[:160]}


def brief(d):
    if isinstance(d, dict):
        out = {}
        for k, v in list(d.items())[:8]:
            if isinstance(v, list):
                out[k] = f"[{len(v)}项]" + (json.dumps(v[0], ensure_ascii=False)[:90] if v else "")
            elif isinstance(v, dict):
                out[k] = f"{{{','.join(list(v)[:6])}}}"
            else:
                out[k] = v
        return json.dumps(out, ensure_ascii=False)[:420]
    if isinstance(d, list):
        return f"[{len(d)}项] " + (json.dumps(d[0], ensure_ascii=False)[:180] if d else "")
    return str(d)[:200]


def show(tag, j):
    if "_err" in j:
        print(f"  {tag:<52} ERR {j['_err']}")
        return None
    code = j.get("code")
    if code == 0:
        print(f"  {tag:<52} OK  {brief(j.get('data'))}")
        return j.get("data")
    print(f"  {tag:<52} FAIL code={code} {str(j.get('message') or j.get('msg'))[:110]}")
    return None


print("=" * 104)
print("Q1  getTouristCountyData 的 area 语义（契约枚举=21 个市州简称）")
print("=" * 104)
for v in ["成都市", "青羊区", "锦江区", "武侯区", "都江堰市", "汶川县", "康定市", "稻城县"]:
    for p in ("/show/ecologicalArea/getTouristCountyData", "/show/travel/getTouristCountyData"):
        show(f"{p.split('/')[2]}?area={v}", get(p, {"area": v}))

print()
print("=" * 104)
print("Q2  travel/getTravelImageUrl 的 type 取值（单图接口现在返回空）")
print("=" * 104)
TRAVEL_ID = "43c4f5188de54c46b2b03094ff1e5da0"
for t in [None, "1", "2", "3", "4", "5"]:
    prm = {"travelId": TRAVEL_ID}
    if t:
        prm["type"] = t
    show(f"/show/travel/getTravelImageUrl type={t}", get("/show/travel/getTravelImageUrl", prm))

print()
print("=" * 104)
print("Q3  真实 dataId / type 从列表接口取")
print("=" * 104)
by_type = show("travel/getTravelRoadDataByType type=1", get("/show/travel/getTravelRoadDataByType",
                                                            {"type": "1", "travelId": TRAVEL_ID}))
data_ids = []
if isinstance(by_type, dict):
    for key in ("projectData", "agglomerationAreaData", "nmchBaseData"):
        blk = by_type.get(key)
        if isinstance(blk, dict) and blk.get("dataList"):
            first = blk["dataList"][0]
            print(f"    {key}.dataList[0] = {json.dumps(first, ensure_ascii=False)[:220]}")
            data_ids.append((key, first))
    if not data_ids and by_type.get("dataList"):
        print(f"    dataList[0] = {json.dumps(by_type['dataList'][0], ensure_ascii=False)[:220]}")

for i, (key, first) in enumerate(data_ids[:3]):
    did = first.get("id") or first.get("base_id") or first.get("project_id")
    for p in ("/show/travel/getTravelRoadDataDetail", "/show/travel/getDetailsData"):
        show(f"{p.split('/')[-1]} dataId={did} type=1 ({key})", get(p, {"dataId": did, "type": "1"}))

print()
print("=" * 104)
print("Q4  ecologicalArea/getEcologicalAreaImageUrl 与 eco_road_data 的 dataList 结构")
print("=" * 104)
ECO_ID = "5f199a336e2e44efab9c5541f4138fe9"
eco = show("eco/getEcologicalAreaRoadData", get("/show/ecologicalArea/getEcologicalAreaRoadData",
                                                {"ecologicalAreaId": ECO_ID, "areaId": "510100000000"}))
if isinstance(eco, dict):
    for key in ("projectData", "agglomerationAreaData", "nmchBaseData"):
        blk = eco.get(key)
        if isinstance(blk, dict) and blk.get("dataList"):
            print(f"    {key}.dataList[0] = {json.dumps(blk['dataList'][0], ensure_ascii=False)[:260]}")
            did = blk["dataList"][0].get("id") or blk["dataList"][0].get("data_id")
            show(f"eco/getEcologicalAreaImageUrl dataId={did} type=1",
                 get("/show/ecologicalArea/getEcologicalAreaImageUrl",
                     {"ecologicalAreaId": ECO_ID, "areaId": "510100000000", "type": "1", "dataId": did}))
        else:
            print(f"    {key}.dataList = 空")
