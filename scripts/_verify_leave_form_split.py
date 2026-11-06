# -*- coding: utf-8 -*-
"""「审批先调后台自定义表单，后续业务再动态生成」端到端验收（九期，2026-11-06）

用户诉求（原话）：
  「审批时，要先调用后台对应 oa 模块的自定义表单，然后再根据后面还有什么业务，
    比如选择负责人（提供下拉选择让用户选择）动态生成，
    不要所有的请求都挤在一张表单里面」

改动前的问题（截图实证）：
  请假走的是 agent 自造的 ask_user 字段卡 —— 假种/日期/事由/**审批负责人文本框**全挤一张卡；
  且字段与 form_template 漂移（漏 `days`/`proof`），负责人被造成自由文本输入。

判据（三方对照：页面渲染 / 接口回读 / DB 定义，互不同源）：
  V1  对话里说「帮我请假，审批人王启铭」⇒ 出的是**后端定义的业务表单**（.leave-form[data-code]），
      不是 .clar-fields 自造卡
  V2  卡片字段集合 == GET /v1/forms/{code} 的 fields 集合（逐 label 比对）
  V3  上述字段集合 == DB form_template.schema_json 的 title 集合
  V4  表单里**没有**「审批负责人 / 交给谁处理」这类字段（负责人不属于业务表单）
  V5  假种是 <select> 下拉且选项 > 1（不是文本框，也不是空下拉）
  V6  提交后负责人环节**单独出现**（#hdMask 弹层，两个选项），不挤在同一张表里
  V7  取消负责人环节 ⇒ **零提交请求**（不落库，验收不留脏数据）

前置：后端 :8080（H5 在 /aios/h5/）+ agent :8000（真实链路，不能用桩）。
用法：python scripts/_verify_leave_form_split.py
"""

try:  # 控制台编码：GBK 下打印 ✅ 会 UnicodeEncodeError（本块必须在 import sys 之后才有效）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pathlib
import subprocess
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
API = BASE + "/api/v1"
H5 = BASE + "/aios/h5/"
USER, PWD = "test", "test"
MYSQL = r"D:\dev\mysql\mysql-8.4.10-winx64\bin\mysql.exe"
OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "regression-2026-11-06"
OUT.mkdir(parents=True, exist_ok=True)

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def sql(q):
    return subprocess.run([MYSQL, "-uroot", "aios", "-e", q],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def login():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"], {"Authorization": "Bearer " + d["data"]["accessToken"]}


def main():
    _token, _user, h = login()

    # ---------------------------------------------------------------- 定位请假表单码（DB 是真源）
    r = sql("select code from form_template where tenant_id=0 and biz_type='LEAVE' and deleted_at is null limit 1;")
    code = ""
    for line in (r.stdout or "").splitlines():
        if line.strip() and line.strip() != "code":
            code = line.strip()
            break
    rec("V0 DB 里存在 biz_type=LEAVE 的表单定义", bool(code), "非空 code", code)
    if not code:
        return

    # ---------------------------------------------------------------- V3 DB 定义（第一方）
    r = sql(f"select schema_json from form_template where tenant_id=0 and code='{code}' limit 1;")
    raw = "\n".join((r.stdout or "").splitlines()[1:]).strip()
    db_titles = []
    req_names = []
    req_labels = []
    schema = {}
    try:
        # mysql CLI 会把 JSON 原样输出（可能含反斜杠转义），这里只取 title 字段名做集合比对
        schema = json.loads(raw)
        props = schema.get("properties") or {}
        db_titles = sorted(v.get("title") for k, v in props.items())
        req_names = [str(x) for x in (schema.get("required") or [])]
        # required 顺序 → label（跳过 properties 里不存在的脏键）
        req_labels = [str((props.get(k) or {}).get("title")) for k in req_names if k in props]
    except Exception as e:
        rec("V3 DB schema 可解析", False, "合法 JSON", str(e)[:120])
    if db_titles:
        rec("V3 DB 定义里没有「审批负责人」类字段（负责人不属于业务表单）",
            not any(("负责人" in t) or ("审批人" in t) for t in db_titles if t),
            "无负责人字段", db_titles)

    # ---------------------------------------------------------------- V2 接口（第二方）
    d = httpx.get(f"{API}/forms/{code}", headers=h, timeout=30, trust_env=False).json()
    api_fields = (d.get("data") or {}).get("fields") or []
    api_labels = [str(f.get("label")) for f in api_fields if f]
    rec("V2 接口 /forms/{code} 返回字段（供页面渲染的同一份定义）",
        len(api_labels) > 0, ">0 个字段", api_labels)
    if db_titles:
        rec("V2b 接口字段 == DB 定义字段（同源校验，不是页面自证）",
            sorted(t for t in api_labels if t) == sorted(t for t in db_titles if t),
            db_titles, api_labels)
    # ★ 顺序契约：required 数组顺序在前，非必填在后。
    #   MySQL 的 JSON 列会重排对象键（按 key 长度升序），落库后 properties 顺序已不可信；
    #   required 是数组不受影响，且种子里它就是业务顺序。
    #   判据必须拿 DB 的 required 顺序去比接口输出顺序 —— 不能拿接口自己的顺序反过来筛自己（那是自证）。
    if req_labels:
        head = api_labels[:len(req_labels)]
        rec("V2d 接口字段顺序 = required 业务顺序（不是 MySQL 的键重排顺序）",
            head == req_labels, req_labels, head,
            f"required 之外的字段应排在后面：{api_labels[len(req_labels):]}")

    # ---------------------------------------------------------------- V1/V4/V5 页面（第三方）
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 420, "height": 900}, locale="zh-CN")
        # 登录态走 localStorage（与 _verify_handler_confirm.py U 段同一口径）。
        # 本脚本**不打 SSE 桩**：要验的就是「说一句请假 ⇒ 后端表单」这条真实链路。
        ctx.add_init_script(
            "localStorage.setItem('aios_session', %s);localStorage.setItem('aios_mode','oa');"
            % json.dumps(json.dumps({"token": _token, "user": _user}, ensure_ascii=False)))
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        posts = []

        def on_req(req):
            if req.method == "POST" and "/forms/" in req.url and req.url.endswith("/submit"):
                posts.append(req.url)
        pg.on("request", on_req)

        pg.goto(H5, wait_until="domcontentloaded")
        pg.wait_for_selector("#oaRoot", timeout=30000)
        pg.wait_for_timeout(2500)

        pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
        pg.wait_for_timeout(500)
        pg.evaluate("() => { const b2 = document.getElementById('odNewChat'); if(b2) b2.click(); }")
        pg.wait_for_timeout(600)
        pg.fill("#oaInput", "帮我请假，审批人王启铭")
        pg.wait_for_timeout(200)
        pg.click("#oaSendBtn", force=True)

        # V1 出的是业务表单卡片
        sel = f'.leave-form[data-code="{code}"]'
        try:
            pg.wait_for_selector(sel, timeout=40000)
            got = True
        except Exception:
            got = False
        clar = pg.locator(".clar-fields").count()
        rec("V1 对话里的请假 ⇒ 渲染**后端定义的表单**（.leave-form[data-code]）", got, sel, got,
            f"同时存在的自造字段卡 .clar-fields={clar}")
        pg.screenshot(path=str(OUT / "40-leave-form-from-db.png"), full_page=True)
        if not got:
            rec("V4 表单不含负责人字段", False, "前置 V1 失败", "跳过")
            b.close()
            return

        page_fields = pg.evaluate("""(code) => {
            const card = document.querySelector('.leave-form[data-code="'+code+'"]');
            if(!card) return null;
            return Array.from(card.querySelectorAll('[data-field]')).map(c => ({
              name: c.getAttribute('data-field'),
              type: c.getAttribute('data-type'),
              label: (c.closest('.lf-row')||{}).innerText ? c.closest('.lf-row').innerText.split('\\n')[0].trim() : ''
            }));
        }""", code)
        page_fields = page_fields or []
        page_labels = [(f.get("label") or "").replace("*", "").strip() for f in page_fields]
        # ★ 有序比较（不能 sorted）：MySQL 的 JSON 列会重排对象键，字段顺序曾是乱序的
        # ★2026-11-06 判据升级：按**字段名 + 顺序**比，不再比 label。
        #   这一轮用户要求「内部字段不能展示给用户」，label 已被有意改成人话
        #   （假种→请假类型），拿 label 比会把「对的展示」判成红；而比字段名其实更硬 ——
        #   label 可能碰巧相同，name 相同才真正证明「页面用的是接口这份定义」。
        api_names = [f.get("name") for f in (api_fields or [])]
        page_names = [f.get("name") for f in page_fields]
        rec("V2c 页面渲染字段名 == 接口字段名（顺序也一致）",
            page_names == api_names, api_names, page_names)

        # 展示层：内部叫法必须换成用户语言（与上一条互补：结构一致 + 文案人话）
        alias_bad = [l for l in page_labels if l in ("假种", "假别")]
        rec("V2c' 内部叫法已换人话（页面不再出现「假种」）",
            not alias_bad and "请假类型" in page_labels, "出现「请假类型」且无「假种」",
            {"labels": page_labels, "bad": alias_bad})

        card_text = pg.evaluate("""(code) => {
            const card = document.querySelector('.leave-form[data-code="'+code+'"]');
            return card ? (card.innerText || '') : '';
        }""", code)
        rec("V4 表单里没有「审批负责人 / 交给谁处理」字段（负责人留到下一步）",
            ("审批负责人" not in card_text) and ("交给谁处理" not in card_text),
            "不含负责人字段", [ln for ln in card_text.splitlines() if "负责" in ln or "交给" in ln])

        # V5 假种是下拉且非空
        st = pg.evaluate("""(code) => {
            const card = document.querySelector('.leave-form[data-code="'+code+'"]');
            if(!card) return null;
            const s = card.querySelector('select[data-type="select"]');
            return s ? {name: s.getAttribute('data-field'), n: s.options.length} : null;
        }""", code)
        rec("V5 假种是下拉选择且候选 > 1（不是文本框）",
            bool(st) and st.get("n", 0) > 1, "select 且 options>1", st)

        # V6 负责人环节单独出现
        pg.evaluate("""(code) => {
            const card = document.querySelector('.leave-form[data-code="'+code+'"]');
            if(!card) return;
            card.querySelectorAll('[data-field]').forEach(c => {
              const type = c.getAttribute('data-type');
              const req = c.getAttribute('data-required') === '1';
              if(!req) return;
              if(type === 'select'){ if(c.options.length > 1) c.selectedIndex = 1; }
              else if(type === 'multiselect'){ if(c.options.length) c.options[0].selected = true; }
              else if(type === 'boolean'){ c.checked = true; }
              else if(type === 'number'){ c.value = '1'; }
              else if(type === 'date'){ c.value = '2026-11-10'; }
              else if(type === 'datetime'){ c.value = '2026-11-10T09:00'; }
              else { c.value = '验收：请假表单分步'; }
              c.dispatchEvent(new Event('input', {bubbles:true}));
              c.dispatchEvent(new Event('change', {bubbles:true}));
            });
        }""", code)
        pg.click(sel + " [data-form-submit]")
        pg.wait_for_timeout(500)
        has_confirm = pg.locator(sel + " [data-form-confirm]").count() > 0
        if has_confirm:
            pg.click(sel + " [data-form-confirm]")
        try:
            pg.wait_for_selector("#hdMask.on", timeout=8000)
            pg.wait_for_timeout(500)
            opened = True
        except Exception:
            opened = False
        opts = pg.evaluate("() => Array.from(document.querySelectorAll('#hdMask .hd-opt'))"
                           ".map(e => (e.textContent||'').replace(/\\s+/g,' ').trim())")
        rec("V6 提交后负责人环节**单独出现**（弹层两选项），未挤在业务表单里",
            opened and len(opts) == 2, "两选项弹层", {"opened": opened, "opts": opts})
        # 指定位打开候选列表（下拉选择器，而不是输入框）
        pg.evaluate("() => { const o = document.querySelector('#hdMask [data-hd=\"SPECIFIED\"]'); if(o) o.click(); }")
        pg.wait_for_timeout(1200)
        picker = pg.evaluate("""() => {
            const body = document.getElementById('hdBody');
            const items = document.querySelectorAll('#hdList [data-uid]').length;
            const hasSearch = !!document.getElementById('hdSearch');
            const input = document.querySelector('#hdMask input[type="text"]:not(#hdSearch)');
            return {visible: !!(body && !body.hidden), items, hasSearch, freeTextInput: !!input};
        }""")
        rec("V6b 指定负责人是**选择器**（候选列表 + 搜索），不是自由文本框",
            picker.get("visible") and picker.get("items", 0) > 0 and picker.get("hasSearch"),
            "候选>0 且有搜索框", picker)
        pg.screenshot(path=str(OUT / "41-handler-step2.png"))

        # V7 取消 ⇒ 零提交
        pg.click("#hdMask [data-hd-cancel]")
        pg.wait_for_timeout(900)
        rec("V7 取消负责人环节 ⇒ 不发提交请求（验收不留脏数据）",
            len(posts) == 0, "0 个 /forms/*/submit", posts)

        rec("V8 全程无 JS 异常", not errors, "无 pageerror", errors[:3])
        b.close()

    print("\n" + "=" * 60)
    ok = sum(1 for _n, v in results if v)
    print(f"合计 {len(results)} 项，通过 {ok}，失败 {len(results) - ok}")
    print(f"截图目录： {OUT}")


if __name__ == "__main__":
    main()
