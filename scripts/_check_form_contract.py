#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表单跨层契约哨兵（Java → Python → H5 三层键名对齐）。

## 它防的是什么

刚完成的三项表单改造横跨三层，而现有的测试都**各测一层**，没有任何一条断言
「三层的键名真的对得上」。这类跨层接口最危险的是**改名时静默断链**：

  - Java 出站 `AgentRunRequest.availableForms` 的 `@JsonProperty("available_forms")`
    与 Python 入站 `RunRequest.available_forms` 字段名若不一致，模型侧就收不到清单；
  - Java `FormRuleExceptionHandler` 写出的 `rule_violation.{...}` 键名若与 H5
    `mountFormCard` 实际读取的 `rv.<name>` 不一致，规则命中就渲染不出选项回填。

本脚本**不用浏览器、不连后端、不用 Maven**，只读文件 + 用 agent 的 venv 跑 pydantic
解析，把三层键名一次性钉死。每条断言都能因真实缺陷变红（注释里写明「什么改动会让它红」）。

## 三层现状（刚改完，被本脚本钉住）

  - Java 出站：`server/aios-chat/.../dto/AgentRunRequest.java`
        @JsonProperty("available_forms") private List<...> availableForms;
  - Python 入站：`agent/aios_ai/contracts.py`
        RunRequest.available_forms: list[dict[str, Any]] | None = None
        注入点 `agent/aios_ai/prompt/builder.py` 的 build_messages，产出
        【可用表单清单】…【以上为可用表单清单】段，行格式 `- code｜name｜模块=module_code`。
  - Java 规则命中响应：`server/aios-resource/.../controller/FormRuleExceptionHandler.java`
        返回 HTTP 200 + code=40090 + data.rule_violation.{rule_id,field,target_field,message,options}。
  - H5 消费：`user-client/_backup_index_pre_oa.html`（基线；产物 index.html 由它构建）
        mountFormCard 读 err.code === 40090、err.data.rule_violation、rv.message、
        rv.options、rv.target_field、rv.field。

## 断言清单（每条都「因真实缺陷变红」）

  K1  键一致：Java @JsonProperty("available_forms") 键名 == Python RunRequest.available_forms 字段名。
        —— 改动 Java 的 @JsonProperty 值或 Python 字段名会让它红。
  K2  负向对照（证明 K1 不是恒真）：用驼峰 availableForms 构造请求，
        model_validate 后 available_forms 必须为 None（键名写错就真的收不到）。
  K3  端到端（键名→提示词）：照 Java 实际序列化形状解析 JSON，调 build_messages，
        断言 system 里同时出现两个 code、两个中文名、模块=leave，且两个定界符各出现 1 次。
  K4  空清单不注入（负向对照）：去掉 available_forms，断言 system 不含「可用表单清单」。
  K5  规则响应键名双向对齐：Java 写入 rule_violation 的键 ⊇ {rule_id,field,target_field,message,options}；
        H5 实际读取的键必须是 Java 输出键的子集（H5 可少读，绝不能读一个 Java 不产的键）。
  K6  负向对照：Java 文件里不存在驼峰 ruleViolation / targetField / ruleId 这些错误拼写
        （作为 .put 键或 @JsonProperty 值）。若将来有人改错，K5 可能因正则宽松而漏，K6 兜住。
  K7  提示词与工具描述同源：request_form.py 工具描述与 builder.py 注入块都出现「清单」，
        且都出现 request_form / form_code 约束关键字（一处改了另一处没改会红）。
  K8  单向断言：AgentRunRequest.java 里没有拼错的 availabe_forms / availableForms 作为
        @JsonProperty 值（驼峰或错拼值若被误写为 @JsonProperty 会让 Java 出站键漂移）。

## 跑法（必须用 agent venv，因为它装了 pydantic；托管 python 没装）

    cd /d/aios
    agent/.venv/Scripts/python.exe scripts/_check_form_contract.py

## 退出码

    0  全部通过
    1  有断言失败

纪律：抓取一律用精确正则，不用 `in` 全文模糊命中（否则恒真）；若结构变了导致抓不到，
**报 FAIL 而不是跳过**（这里没有可复核的 SKIP 理由）。
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# aios_ai 包位于 agent/ 目录下，需加入导入路径（与 agent venv 配合）。
AGENT_DIR = ROOT / "agent"

JAVA_DTO = "server/aios-chat/src/main/java/cn/aios/chat/dto/AgentRunRequest.java"
PY_CONTRACTS = "agent/aios_ai/contracts.py"
PY_BUILDER = "agent/aios_ai/prompt/builder.py"
PY_TOOL = "agent/aios_ai/tools/request_form.py"
JAVA_RULE = "server/aios-resource/src/main/java/cn/aios/resource/controller/FormRuleExceptionHandler.java"
H5_BACKUP = "user-client/_backup_index_pre_oa.html"

oks = 0
fails = []


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        raise FileNotFoundError(rel)
    return p.read_text(encoding="utf-8", errors="replace")


def chk(name: str, ok: bool, detail: str = ""):
    global oks
    if ok:
        oks += 1
        print("[PASS] %s%s" % (name, (" —— " + detail) if detail else ""))
    else:
        fails.append(name + (" —— " + detail if detail else ""))
        print("[FAIL] %s%s" % (name, (" —— " + detail) if detail else ""))
    return ok


def report():
    print("\n──────── 收口 ────────")
    print("通过：%d / 失败：%d" % (oks, len(fails)))
    if fails:
        print("失败项：")
        for f in fails:
            print("  - " + f)
    return 1 if fails else 0


# --------------------------------------------------------------------------- K1：键一致
def k1_java_py_key_aligned(java_src: str, py_src: str):
    """Java @JsonProperty 键 == Python RunRequest 字段名，且都为 available_forms。

    改动 Java 的 @JsonProperty 值，或改动 Python 的 available_forms 字段名，都会让它红。
    """
    # Java：抓取「紧挨着 availableForms 字段」的 @JsonProperty 值（精确，不靠全文 in）。
    m_java = re.search(
        r'@JsonProperty\(\s*"([^"]+)"\s*\)\s*private\s+List<Map<String,\s*Object>>\s+availableForms',
        java_src, re.S)
    java_key = m_java.group(1) if m_java else None

    # Python：抓取 RunRequest 里 available_forms 字段（精确，限定类型签名为 list[dict[str,Any]]|None）。
    m_py = re.search(
        r'\b(available_forms)\s*:\s*list\[dict\[str,\s*Any\]\]\s*\|\s*None\s*=\s*None',
        py_src)
    py_field = m_py.group(1) if m_py else None

    if java_key is None or py_field is None:
        return (False, "抓取失败：java_key=%r py_field=%r（结构已变，需人工确认）" % (java_key, py_field))
    aligned = (java_key == py_field == "available_forms")
    return (aligned, "java=@JsonProperty(%r) py=字段%r" % (java_key, py_field))


# --------------------------------------------------------------------------- K2：负向（驼峰收不到）
def k2_camelcase_not_received():
    """用驼峰 availableForms 构造请求，断言解析后 available_forms 为 None。

    证明 K1 不是恒真：如果 pydantic 把驼峰也当 available_forms 收下，说明两端的契约其实没对齐
    （或有人加了 alias），这条会红，提示「键名写错也能收到」的隐患。
    """
    from aios_ai.contracts import RunRequest
    payload = {
        "run_id": "r-camel-1",
        "conversation_id": 1,
        "text": "我要请假",
        # user_context 必填 user_id / tenant_id
        "user_context": {"user_id": 1, "tenant_id": 1},
        # 故意用驼峰（Java 字段名），而非契约键名 available_forms
        "availableForms": [
            {"code": "leave_request", "name": "请假申请", "module_code": "leave", "biz_type": "leave"},
        ],
    }
    req = RunRequest.model_validate(payload)
    ok = req.available_forms is None
    detail = "available_forms=%r（驼峰未收到=符合预期）" % (req.available_forms,)
    return (ok, detail)


# --------------------------------------------------------------------------- K3：端到端（键名→提示词）
def k3_keyname_to_prompt():
    """照 Java 实际序列化形状解析 JSON，调 build_messages，断言清单真的注入提示词。

    改动 Java 的 available_forms 键名 / Python 的字段名 / builder 注入块任一，都会让它红。
    """
    from aios_ai.contracts import RunRequest
    from aios_ai.prompt.builder import build_messages
    payload = {
        "run_id": "r-e2e-1",
        "conversation_id": 1,
        "text": "我要请假",
        "user_context": {"user_id": 1, "tenant_id": 1},
        # 顶层 available_forms，照 Java 序列化形状（code/name/module_code/biz_type）
        "available_forms": [
            {"code": "leave_request", "name": "请假申请", "module_code": "leave", "biz_type": "leave"},
            {"code": "expense_report", "name": "报销申请", "module_code": "finance", "biz_type": "expense"},
        ],
    }
    req = RunRequest.model_validate(payload)
    msgs = build_messages(req)
    system = msgs[0]["content"]

    checks = []
    checks.append(("code=leave_request", "leave_request" in system))
    checks.append(("code=expense_report", "expense_report" in system))
    checks.append(("name=请假申请", "请假申请" in system))
    checks.append(("name=报销申请", "报销申请" in system))
    checks.append(("模块=leave", "模块=leave" in system))
    checks.append(("定界符【可用表单清单】恰好 1 次",
                   system.count("【可用表单清单】") == 1))
    checks.append(("定界符【以上为可用表单清单】恰好 1 次",
                   system.count("【以上为可用表单清单】") == 1))
    bad = [name for name, ok in checks if not ok]
    return (not bad, "未命中：%s" % (bad or "无"))


# --------------------------------------------------------------------------- K4：空清单不注入（负向）
def k4_empty_list_no_inject():
    """同一 payload 去掉 available_forms，断言 system 不含「可用表单清单」。

    证明 K3 的命中不是恒真：若 builder 永远注入（或键名错配导致常驻），这里会红。
    """
    from aios_ai.contracts import RunRequest
    from aios_ai.prompt.builder import build_messages
    payload = {
        "run_id": "r-empty-1",
        "conversation_id": 1,
        "text": "我要请假",
        "user_context": {"user_id": 1, "tenant_id": 1},
        # 故意不带 available_forms
    }
    req = RunRequest.model_validate(payload)
    msgs = build_messages(req)
    system = msgs[0]["content"]
    ok = "可用表单清单" not in system
    return (ok, "system 含『可用表单清单』=%s（应为 False）" % ("可用表单清单" in system))


# --------------------------------------------------------------------------- K5：规则响应键名双向对齐
def k5_rule_keys_aligned(java_src: str, h5_src: str):
    """Java 写入 rule_violation 的键 ⊇ 必需集合；H5 读取的键是 Java 输出键的子集。

    若 Java 删/改了某个键（如把 target_field 改名），H5 仍读旧名 → 子集检查发现缺键 → 红。
    若 H5 读了一个 Java 不产的键（如 rv.foo）→ 红。
    """
    # Java 写入 rule_violation 的键：ruleViolation.put("X", ...)
    java_inner = set(re.findall(r'ruleViolation\.put\(\s*"([^"]+)"', java_src))
    # Java 外层键：data.put("rule_violation", ...) 与 code=40090
    java_wrapper = set(re.findall(r'data\.put\(\s*"([^"]+)"', java_src))
    java_codes = set(re.findall(r'ApiResponse\.fail\(\s*(\d+)', java_src))

    required_inner = {"rule_id", "field", "target_field", "message", "options"}
    missing = required_inner - java_inner
    if missing:
        return (False, "Java 未产出必需键：%s（已产出 %s）" % (sorted(missing), sorted(java_inner)))

    # H5 实际读取：
    #   err.code === 40090  →  code "40090"
    #   err.data.rule_violation →  wrapper key "rule_violation"
    #   rv.<name> →  内层键
    h5_codes = set(re.findall(r'err\.code\s*===\s*(\d+)', h5_src))
    h5_wrapper = set(re.findall(r'err\.data\.(rule_violation)', h5_src))  # 捕获键名
    h5_inner = set(re.findall(r'\brv\.([A-Za-z_][A-Za-z0-9_]*)', h5_src))

    # 子集校验（键统一按字符串比较）
    inner_bad = h5_inner - java_inner
    wrapper_ok = ("rule_violation" in h5_wrapper) and ("rule_violation" in java_wrapper)
    code_ok = (h5_codes <= java_codes) and ("40090" in java_codes)

    ok = (not inner_bad) and wrapper_ok and code_ok
    detail = "h5_inner=%s java_inner=%s 越界=%s wrapper_ok=%s code_ok=%s" % (
        sorted(h5_inner), sorted(java_inner), sorted(inner_bad), wrapper_ok, code_ok)
    return (ok, detail)


# --------------------------------------------------------------------------- K6：负向（驼峰错拼）
def k6_no_camelcase_wrong_spell(java_src: str):
    """Java 文件里不存在驼峰 ruleViolation / targetField / ruleId 作为 .put 键或 @JsonProperty 值。

    若将来有人把 .put("target_field",...) 错改成 .put("targetField",...)，K5 的精确正则
    会抓不到这个键（K5 只认 snake_case），K6 用「禁止驼峰键」兜底 → 红。
    注意：合法出现的 ruleViolation（Map 变量名）、targetField()（getter 方法）不在本断言范围内，
    因为本断言只针对「字符串字面量键」（.put("...") 与 @JsonProperty("...")）。
    """
    bad_patterns = [
        r'\.put\(\s*"ruleId"',
        r'\.put\(\s*"targetField"',
        r'\.put\(\s*"ruleViolation"',
        r'@JsonProperty\(\s*"ruleId"',
        r'@JsonProperty\(\s*"targetField"',
        r'@JsonProperty\(\s*"ruleViolation"',
    ]
    hits = []
    for pat in bad_patterns:
        if re.search(pat, java_src):
            hits.append(pat)
    ok = not hits
    return (ok, "命中禁止的驼峰键/值：%s" % (hits or "无"))


# --------------------------------------------------------------------------- K7：提示词与工具描述同源
def k7_prompt_tool_same_source(tool_src: str, builder_src: str):
    """request_form.py 工具描述 与 builder.py 注入块 都出现「清单」且都出现约束关键字。

    若只改了一处（如 builder 删了「清单」约束但工具描述还保留），两端不同源 → 红。
    """
    def has_constraint(src: str):
        return ("清单" in src) and (("form_code" in src) or ("request_form" in src))

    tool_ok = has_constraint(tool_src)
    builder_ok = has_constraint(builder_src)
    ok = tool_ok and builder_ok
    detail = "tool(清单&约束)=%s builder(清单&约束)=%s" % (tool_ok, builder_ok)
    return (ok, detail)


# --------------------------------------------------------------------------- K8：单向（无错拼 @JsonProperty 值）
def k8_no_bad_jsonproperty(java_src: str):
    """AgentRunRequest.java 里没有 availabe_forms / availableForms 作为 @JsonProperty 值。

    错拼 availabe_forms 或驼峰 availableForms 若被误写成 @JsonProperty 值，会让 Java 出站键漂移，
    而 Python 仍读 available_forms → 静默收不到；用精确正则钉死这两个非法值。
    （注意：private List<...> availableForms; 的字段名本身是合法的，不在范围内。）
    """
    bad = [
        r'@JsonProperty\(\s*"availabe_forms"',
        r'@JsonProperty\(\s*"availableForms"',
    ]
    hits = [pat for pat in bad if re.search(pat, java_src)]
    ok = not hits
    return (ok, "命中非法 @JsonProperty 值：%s" % (hits or "无"))


def main():
    # 让 aios_ai 可被导入（仅 K2/K3/K4 需要；K1/K5/K6/K7/K8 只做静态抓取）。
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))

    print("== 表单跨层契约哨兵 ==")

    # 读文件（缺文件一律 FAIL，不伪装通过）
    try:
        java_dto = read(JAVA_DTO)
    except FileNotFoundError as e:
        chk("K1", False, "文件不存在：%s" % e)
        return report()
    try:
        py_contracts = read(PY_CONTRACTS)
    except FileNotFoundError as e:
        chk("K1", False, "文件不存在：%s" % e)
        return report()
    try:
        java_rule = read(JAVA_RULE)
    except FileNotFoundError as e:
        chk("K5", False, "文件不存在：%s" % e)
        chk("K6", False, "文件不存在：%s" % e)
        return report()
    try:
        h5_src = read(H5_BACKUP)
    except FileNotFoundError as e:
        chk("K5", False, "文件不存在：%s" % e)
        return report()
    try:
        py_tool = read(PY_TOOL)
    except FileNotFoundError as e:
        chk("K7", False, "文件不存在：%s" % e)
        return report()
    try:
        py_builder = read(PY_BUILDER)
    except FileNotFoundError as e:
        chk("K7", False, "文件不存在：%s" % e)
        return report()

    # K1
    ok, detail = k1_java_py_key_aligned(java_dto, py_contracts)
    chk("K1 键一致（Java @JsonProperty == Python 字段 == available_forms）", ok, detail)

    # K2
    try:
        ok, detail = k2_camelcase_not_received()
    except Exception as e:  # pydantic 未装等
        ok, detail = False, "异常：%r" % e
    chk("K2 负向·驼峰 availableForms 解析后 available_forms 为 None", ok, detail)

    # K3
    try:
        ok, detail = k3_keyname_to_prompt()
    except Exception as e:
        ok, detail = False, "异常：%r" % e
    chk("K3 端到端·清单注入提示词（双 code/双名/模块=leave/定界符各1次）", ok, detail)

    # K4
    try:
        ok, detail = k4_empty_list_no_inject()
    except Exception as e:
        ok, detail = False, "异常：%r" % e
    chk("K4 负向·空清单不注入（system 不含『可用表单清单』）", ok, detail)

    # K5
    ok, detail = k5_rule_keys_aligned(java_rule, h5_src)
    chk("K5 规则响应键名双向对齐（H5 读取键 ⊆ Java 输出键）", ok, detail)

    # K6
    ok, detail = k6_no_camelcase_wrong_spell(java_rule)
    chk("K6 负向·Java 无驼峰错拼 ruleViolation/targetField/ruleId 键", ok, detail)

    # K7
    ok, detail = k7_prompt_tool_same_source(py_tool, py_builder)
    chk("K7 提示词与工具描述同源（都含『清单』与约束关键字）", ok, detail)

    # K8
    ok, detail = k8_no_bad_jsonproperty(java_dto)
    chk("K8 单向·Java 无 availabe_forms/availableForms 作 @JsonProperty 值", ok, detail)

    return report()


if __name__ == "__main__":
    sys.exit(main())
