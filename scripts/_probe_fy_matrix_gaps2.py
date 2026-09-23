# -*- coding: utf-8 -*-
"""
第二轮定性（承接 _probe_fy_matrix_gaps.py，只发 GET）：
  A. getTouristCountyData 的 area 到底有没有筛选作用？
     —— 上一轮 8 个取值全部 code=0，但「都成功」不等于「都生效」。
        必须比数据量：若都州市与稻城县返回完全相同，则该参数形同 level（静默失效）。
  B. travel/getTravelRoadDataDetail 的 dataId 应是列表里的哪个字段？
  C. eco/getEcologicalAreaImageUrl 的 type 取值与 dataId 来源。
  D. getTravelImageUrl type=2/3 的语义线索（看 bizid 形状）与是否需要 travelId。
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
TRAVEL_ID = "43c4f5188de54c46b2b03094ff1e5da0"
ECO_ID = "5f199a336e2e44efab9c5541f4138fe9"


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


def sizes(d):
    """把返回里的 listData/num 等计数拎出来，用于判断参数是否真的起了作用。"""
    if not isinstance(d, dict):
        return str(d)[:80]
    parts = []
    for k, v in d.items():
        if isinstance(v, dict):
            inner = {kk: (len(vv) if isinstance(vv, list) else vv)
                     for kk, vv in v.items() if isinstance(vv, (list, int))}
            parts.append(f"{k}{inner}")
        elif isinstance(v, list):
            parts.append(f"{k}=[{len(v)}]")
        else:
            parts.append(f"{k}={v}")
    return " ".join(parts)[:300]


print("=" * 104)
print("A. getTouristCountyData：area 是否真的筛选（对比各取值的 数据量）")
print("=" * 104)
for p in ("/show/ecologicalArea/getTouristCountyData", "/show/travel/getTouristCountyData"):
    print(f"-- {p}")
    for v in ["成都市", "青羊区", "都江堰市", "汶川县", "稻城县", "康定市", "甘孜州", "凉山州", "北京市"]:
        j = get(p, {"area": v})
        code = j.get("code")
        tag = "OK  " if code == 0 else f"FAIL{code}"
        print(f"   {tag} area={v:<8} {sizes(j.get('data')) if code == 0 else str(j.get('message'))[:90]}")
    print()

print("=" * 104)
print("B. travel/getTravelRoadDataDetail：dataId 该用哪个字段")
print("=" * 104)
lst = get("/show/travel/getTravelRoadDataByType", {"type": "1", "travelId": TRAVEL_ID})
rows = ((lst.get("data") or {}).get("dataList") or [])
print(f"   type=1 列表共 {len(rows)} 条；首条字段 = {list(rows[0]) if rows else '空'}")
if rows:
    r0 = rows[0]
    cand = {k: v for k, v in r0.items() if k.endswith("id") and v}
    print(f"   候选 id 字段 = {cand}")
    for k, v in cand.items():
        for t in ["1", "2", "3", "4"]:
            j = get("/show/travel/getTravelRoadDataDetail", {"dataId": str(v), "type": t})
            code = j.get("code")
            print(f"   {k}={str(v)[:34]:<36} type={t} -> "
                  + ("OK " + str(j.get('data'))[:120] if code == 0 else f"FAIL code={code} {str(j.get('message'))[:70]}"))
print()
lst2 = get("/show/travel/getTravelRoadDataByType", {"type": "2", "travelId": TRAVEL_ID})
rows2 = ((lst2.get("data") or {}).get("dataList") or [])
if rows2:
    print(f"   type=2 首条字段 = {list(rows2[0])}; 样例={json.dumps(rows2[0], ensure_ascii=False)[:200]}")

print()
print("=" * 104)
print("C. eco/getEcologicalAreaImageUrl：type × dataId 组合")
print("=" * 104)
eco = get("/show/ecologicalArea/getEcologicalAreaRoadData",
          {"ecologicalAreaId": ECO_ID, "areaId": "510100000000"})
d = eco.get("data") or {}
proj = (((d.get("projectData") or {}).get("dataList")) or [])
aggl = (((d.get("agglomerationAreaData") or {}).get("dataList")) or [])
print(f"   projectData {len(proj)} 条 / agglomerationAreaData {len(aggl)} 条")
ids = []
if proj:
    ids.append(("project.project_base_id", proj[0].get("project_base_id")))
if aggl:
    ids.append(("agglomeration.id", aggl[0].get("id")))
for label, did in ids:
    for t in ["1", "2", "3", "4", "5"]:
        j = get("/show/ecologicalArea/getEcologicalAreaImageUrl",
                {"ecologicalAreaId": ECO_ID, "areaId": "510100000000", "type": t, "dataId": str(did)})
        code = j.get("code")
        n = len(((j.get("data") or {}).get("imageList")) or []) if code == 0 else None
        print(f"   {label:<26} type={t} -> " + (f"OK imageList={n}" if code == 0 else f"FAIL code={code} {str(j.get('message'))[:60]}"))

print()
print("=" * 104)
print("D. travel/getTravelImageUrl：type=2/3 的 bizid 形状与 travelId 必要性")
print("=" * 104)
for t in ["2", "3"]:
    j = get("/show/travel/getTravelImageUrl", {"travelId": TRAVEL_ID, "type": t})
    il = ((j.get("data") or {}).get("imageList")) or []
    print(f"   type={t}: {len(il)} 条; 前2条 bizid={[x.get('bizid') for x in il[:2]]}")
    print(f"           前1条 = {json.dumps(il[0], ensure_ascii=False)[:220] if il else ''}")
# 同一个 type 换线路，看是否真的按 travelId 过滤
OTHER = get("/show/travel/getRoutesTopFewList", {"topNum": 2})
rl = ((OTHER.get("data") or {}).get("routesTopFewList")) or []
if len(rl) > 1:
    t2 = rl[1]["travel_id"]
    for tid in (TRAVEL_ID, t2):
        j = get("/show/travel/getTravelImageUrl", {"travelId": tid, "type": "2"})
        il = ((j.get("data") or {}).get("imageList")) or []
        print(f"   travelId={tid[:12]}… type=2 -> imageList={len(il)}")
