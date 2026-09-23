# -*- coding: utf-8 -*-
"""
第三轮定性（只发 GET）—— 证伪自己，避免把「我们参数错了」误判成「对方有缺陷」。

E. getTouristCountyData 是否可能只是参数形式不对？（若换成区县编码仍全零，才能定性为恒空接口）
F. getDetailsData（保护区/旅游两前缀）的 type 语义：是 1 能出数据、还是各 type 都可？
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


def sig(d):
    """把返回压成一个可比较的签名，用来判断不同参数是否返回了完全相同的东西。"""
    return json.dumps(d, ensure_ascii=False, sort_keys=True)[:400]


print("=" * 104)
print("E. getTouristCountyData 换参数形式是否仍全零（证伪「只是我们参数不对」）")
print("=" * 104)
variants = [
    ("区县名", {"area": "青羊区"}),
    ("区县编码", {"area": "510105000000"}),
    ("市州编码", {"area": "510100"}),
    ("市州编码12位", {"area": "510100000000"}),
    ("空值", {"area": ""}),
    ("缺省(不传)", {}),
    ("错参名 county", {"county": "青羊区"}),
    ("错参名 name", {"name": "青羊区"}),
]
for p in ("/show/ecologicalArea/getTouristCountyData", "/show/travel/getTouristCountyData"):
    print(f"-- {p}")
    sigs = {}
    for label, prm in variants:
        j = get(p, prm)
        code = j.get("code")
        if code == 0:
            s = sig(j.get("data"))
            sigs.setdefault(s, []).append(label)
            print(f"   OK   {label:<16} {s[:150]}")
        else:
            print(f"   FAIL {label:<16} code={code} {str(j.get('message') or j.get('msg'))[:90]}")
    print(f"   >>> 不同返回签名的种类数 = {len(sigs)}（1 表示所有参数形式返回完全相同的数据）")
    print()

print("=" * 104)
print("F. getDetailsData 的 type 语义（dataId=1）")
print("=" * 104)
for p in ("/show/ecologicalArea/getDetailsData", "/show/travel/getDetailsData"):
    print(f"-- {p}")
    for t in ["1", "2", "3", "4", "5"]:
        j = get(p, {"type": t, "dataId": "1"})
        code = j.get("code")
        if code == 0:
            d = j.get("data")
            nonempty = bool(d) and len(json.dumps(d, ensure_ascii=False)) > 4
            print(f"   type={t} -> OK 非空={nonempty} {json.dumps(d, ensure_ascii=False)[:180]}")
        else:
            print(f"   type={t} -> FAIL code={code} {str(j.get('message') or j.get('msg'))[:80]}")
    print()
