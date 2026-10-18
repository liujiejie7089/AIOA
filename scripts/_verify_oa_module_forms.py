# -*- coding: utf-8 -*-
"""
_verify_oa_module_forms.py — docs/52 P5 首批 43 模块表单定义哨兵
================================================================================

打后端 API（不碰 UI 渲染），验证 V86 铺开的 43 个模块表单定义与能力声明。

运行（后端重启并应用 V85/V86 后）
--------------------------------
    python scripts/_verify_oa_module_forms.py
    python scripts/_verify_oa_module_forms.py --host http://127.0.0.1:8080
    python scripts/_verify_oa_module_forms.py --no-proxy   # 等价 trust_env=False

安全注意
--------
- 本机有 http_proxy 时 requests 易返回 502，故默认 requests.Session(trust_env=False)
  （或等价加 --noproxy '*'）。
- 绝不真提交表单污染数据：断言 E 只用 GET 返回的 schema_json 做**结构断言**，
  不调 submit 端点（后端若无独立校验端点，口径见下）。

断言
----
A · 43 个 GET /api/v1/forms/{code} 全部 200，且 fields 非空、字段类型都在白名单内；
B · 43 个 code 互不相同（集合大小 == 43）；
C · 每个模块的 worker_capability 至少 1 条且 form_code 能取到定义
    （口径：直接查库 worker_capability JOIN form_template，二选一之一，避免依赖管理端接口）；
D · 负向对照：随机不存在的 code（not_exist_form_zzz）必须 404/失败，不能返回 200 空定义
    （证明 A 不是恒真）；
E · 43 个 schema_json 结构合法（x-type 白名单 + required ⊆ properties + 每个属性有 title）
    （口径：后端无独立校验端点，用与 GET 同源的 schema_json 在本地按同规则断言）。

退出码 = 失败条数（0 表示全绿）。
"""
import argparse
import json
import sys

import pymysql
import requests

HOST = "http://127.0.0.1:8080"
TYPE_WHITELIST = {
    "text", "textarea", "number", "amount", "date", "datetime",
    "select", "multiselect", "file", "boolean",
}

# 43 个 (code, module_code, 中文名) —— 必须与 V86 生成器、V86 SQL 完全一致
MODULES = [
    ("doc_draft", "doc", "公文助手"), ("archive_borrow", "archive", "档案助手"),
    ("meeting_book", "meeting", "会议助手"), ("contact_add", "contact", "通讯录"),
    ("worklog_submit", "worklog", "工作日志"), ("workplan_submit", "workplan", "工作计划"),
    ("weekly_submit", "weekly", "工作周报"), ("expense_form", "expense", "费用报销"),
    ("travel_form", "travel", "出差助手"), ("seal_apply", "seal", "印章助手"),
    ("project_create", "project", "项目助手"), ("favorite_add", "favorite", "收藏夹"),
    ("milestone_add", "milestone", "大事记"), ("calendar_event", "calendar", "工作日历"),
    ("notice_publish", "notice", "通知公告"), ("publish_article", "publish", "信息发布"),
    ("assign_task", "assign", "工作安排"), ("remind_rule", "remind", "重要提醒"),
    ("vehicle_apply", "vehicle", "用车助手"), ("leave_request", "leave", "请假助手"),
    ("attendance_appeal", "attendance", "考勤管理"), ("doc_upload", "docmgr", "文档管理"),
    ("party_apply", "party", "党务助手"), ("union_apply", "union", "工会工作"),
    ("todo_add", "todo", "待办助手"), ("delegate_rule", "delegate", "委托管理"),
    ("portal_layout", "portal", "门户首页"), ("approval_launch", "approval", "审批中心"),
    ("hr_register", "hr", "人事管理"), ("recruit_req", "recruit", "招聘管理"),
    ("train_signup", "train", "培训管理"), ("knowledge_upload", "knowledge", "知识管理"),
    ("asset_apply", "asset", "资产管理"), ("contract_draft", "contract", "合同管理"),
    ("task_supervise", "task", "任务督办"), ("crm_add", "crm", "客户管理"),
    ("finance_apply", "finance", "财务管理"), ("purchase_req", "purchase", "采购管理"),
    ("survey_launch", "survey", "问卷调查"), ("security_apply", "security", "安全与权限"),
    ("integration_req", "integration", "系统集成"), ("analytics_board", "analytics", "数据分析"),
    ("mobile_checkin", "mobile", "移动办公"),
]
CODES = [m[0] for m in MODULES]

NEG_CODE = "not_exist_form_zzz"

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios")


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------
def login(session, host):
    """用 wjj_xu / User@123 登录，返回带 Authorization 的 session；失败抛错。"""
    candidates = [
        "/api/v1/auth/login", "/api/v1/login", "/login",
        "/api/v1/auth/signin", "/api/v1/user/login",
    ]
    payload = {"username": "wjj_xu", "password": "User@123"}
    last_err = None
    for path in candidates:
        try:
            r = session.post(host + path, json=payload, timeout=15)
            if r.status_code in (200, 201) and r.text.strip():
                body = r.json()
                token = (body.get("token") or body.get("accessToken")
                         or (body.get("data") or {}).get("token")
                         or (body.get("data") or {}).get("accessToken"))
                if token:
                    session.headers["Authorization"] = "Bearer %s" % token
                    print("  登录成功: %s" % path)
                    return True
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError("登录失败，未命中可用登录端点；last_err=%s" % last_err)


# ---------------------------------------------------------------------------
# 从 GET 响应抽取字段列表与类型（兼容 fields[] 与 schema_json 两种后端形态）
# ---------------------------------------------------------------------------
def extract_fields(body):
    """返回 (fields_list, schema_json_or_None)。fields_list 为 [{name,label,type,...}]。"""
    # 形态1：响应直接含 fields 数组
    if isinstance(body.get("fields"), list) and body["fields"]:
        return body["fields"], body.get("schema_json")
    # 形态2：响应含 schema_json（JSON Schema Draft 2020-12）
    sj = body.get("schema_json") or body.get("schema")
    if isinstance(sj, (str, bytes)):
        try:
            sj = json.loads(sj)
        except Exception:
            sj = None
    if isinstance(sj, dict):
        props = sj.get("properties", {})
        fields = []
        for name, spec in props.items():
            spec = spec or {}
            fields.append({
                "name": name,
                "label": spec.get("title", name),
                "type": spec.get("x-type") or spec.get("type"),
            })
        if fields:
            return fields, sj
    return [], sj


def schema_struct_ok(sj):
    """断言 E：schema_json 结构合法。返回 (ok, msg)。"""
    if not isinstance(sj, dict):
        return False, "schema_json 非对象"
    if sj.get("type") != "object":
        return False, "顶层 type 非 object"
    props = sj.get("properties")
    if not isinstance(props, dict) or not props:
        return False, "properties 为空或非对象"
    req = sj.get("required", [])
    if not isinstance(req, list):
        return False, "required 非数组"
    for name, spec in props.items():
        spec = spec or {}
        xt = spec.get("x-type") or spec.get("type")
        if xt not in TYPE_WHITELIST:
            return False, "属性 %s 类型 %r 越白名单" % (name, xt)
        if not spec.get("title"):
            return False, "属性 %s 缺 title" % name
    for r in req:
        if r not in props:
            return False, "required 含不存在属性 %s" % r
    return True, "ok"


# ---------------------------------------------------------------------------
# 断言 C：查库
# ---------------------------------------------------------------------------
def check_capability_db():
    conn = pymysql.connect(connect_timeout=10, **DB)
    cur = conn.cursor()
    missing = []
    for code, module_code, name in MODULES:
        cur.execute(
            "SELECT COUNT(*) FROM worker_capability c "
            "JOIN form_template t ON t.tenant_id=c.tenant_id AND t.code=c.form_code "
            "WHERE c.form_code=%s AND c.enabled=1", (code,)
        )
        n = cur.fetchone()[0]
        if n < 1:
            missing.append((code, name, n))
    cur.close()
    conn.close()
    return missing


def load_schema_json_from_db():
    """从 form_template 真源读 43 份 schema_json（平台模板 tenant_id=0）。

    为什么读库而不是读接口：GET /api/v1/forms/{code} 返回的是**渲染载荷 fields[]**
    （版本/标题/控件/选项都已解析），按设计不含 schema_json；拿它做结构断言必然为 None。
    结构是否合法属于「定义」本身，真源就在这张表里（铁律 12：判据回到事实源头）。
    """
    conn = pymysql.connect(connect_timeout=10, **DB)
    cur = conn.cursor()
    out = {}
    try:
        cur.execute(
            "SELECT code, schema_json FROM form_template "
            "WHERE tenant_id=0 AND status='ACTIVE' AND deleted_at IS NULL")
        for code, raw in cur.fetchall():
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            try:
                out[code] = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                out[code] = None
    finally:
        cur.close()
        conn.close()
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--no-proxy", action="store_true", help="等价 trust_env=False")
    args = ap.parse_args()

    session = requests.Session()
    if args.no_proxy:
        session.trust_env = False
    session.proxies = {}  # 清空可能存在的代理

    failures = []

    print("== 登录 ==")
    login(session, args.host)

    print("== 断言 A/B：GET /api/v1/forms/{code} ==")
    got_codes = []
    for code, module_code, name in MODULES:
        try:
            r = session.get(args.host + "/api/v1/forms/" + code, timeout=15)
        except Exception as e:  # noqa: BLE001
            failures.append("A FAIL %s(%s) 请求异常 %r" % (name, code, e))
            continue
        if r.status_code != 200:
            failures.append("A FAIL %s(%s) HTTP %d" % (name, code, r.status_code))
            continue
        body = r.json()
        # 信封 {code,message,data} → 取 data；不解信封会把「fields 为空」误报成产品缺陷
        if isinstance(body.get("data"), dict):
            body = body["data"]
        fields, sj = extract_fields(body)
        if not fields:
            failures.append("A FAIL %s(%s) fields 为空" % (name, code))
            continue
        bad_types = []
        for f in fields:
            t = f.get("type")
            if t not in TYPE_WHITELIST:
                bad_types.append((f.get("name"), t))
        if bad_types:
            failures.append("A FAIL %s(%s) 类型越白名单 %s" % (name, code, bad_types))
            continue
        got_codes.append(code)
        print("   A OK %s(%s) fields=%d" % (name, code, len(fields)))

    print("== 断言 B：43 code 互不相同 ==")
    if len(set(got_codes)) != 43:
        failures.append("B FAIL 去重后 code 数=%d 期望 43" % len(set(got_codes)))
    else:
        print("   B OK 43 code 互不相同")

    print("== 断言 C：worker_capability 覆盖（查库）==")
    missing_cap = check_capability_db()
    if missing_cap:
        for code, name, n in missing_cap:
            failures.append("C FAIL %s(%s) capability 行数=%d" % (name, code, n))
    else:
        print("   C OK 43 模块均有 ≥1 条 enabled capability 且 form_code 可解析")

    print("== 断言 D：负向对照 %s 必须非 200 ==" % NEG_CODE)
    try:
        r = session.get(args.host + "/api/v1/forms/" + NEG_CODE, timeout=15)
        if r.status_code == 200 and r.text.strip():
            failures.append("D FAIL 不存在的 code 返回 200（A 可能为恒真）")
        else:
            print("   D OK 不存在 code 返回 HTTP %d（非 200 空定义）" % r.status_code)
    except Exception as e:  # noqa: BLE001
        print("   D OK 不存在 code 请求异常（视为非 200）%r" % e)

    print("== 断言 E：schema_json 结构合法（真源=库，不读渲染接口）==")
    # 口径修正（2026-10-17）：GET /forms/{code} 是**渲染载荷**，按设计不返回 schema_json；
    # 之前拿它做结构断言 ⇒ 43 条全红且是假红。结构必须回到真源 form_template.schema_json。
    db_schemas = load_schema_json_from_db()
    if not db_schemas:
        failures.append("E FAIL 无法从库读取 schema_json（检查 MySQL 连接）")
    for code, module_code, name in MODULES:
        sj = db_schemas.get(code)
        if sj is None:
            failures.append("E FAIL %s(%s) 库里没有该 code 的 schema_json" % (name, code))
            continue
        ok, msg = schema_struct_ok(sj)
        if not ok:
            failures.append("E FAIL %s(%s) %s" % (name, code, msg))

    print("\n================ 哨兵结果 ================")
    if failures:
        print("失败 %d 条：" % len(failures))
        for f in failures:
            print("  - " + f)
    else:
        print("全部断言通过（A/B/C/D/E）")
    print("==========================================")
    sys.exit(len(failures))


if __name__ == "__main__":
    main()
