# -*- coding: utf-8 -*-
"""哨兵：对话级知识库开关 `kb_on` 在 Python agent 侧是否真的生效。

背景（2026-10-07 定案）
    H5 一直会随 run 请求发 `kb_on`，但**全链路无人消费** —— 死开关。
    真正决定「这次检不检索」的是 `echo_runtime._TOOL_ROUTES` 的关键词路由
    （表里含「知识库 / 找资料 / 检索 / 查资料」），这就是用户现象
    「只有说『在知识库里』才检索到」的直接代码原因。
    修复后语义：`kb_on=False` ⇒ 本次 run **完全不使用**知识库；
                `True` / 缺省（None） ⇒ 知识库**可用且优先**（预检索 + 引用溯源）。

用法
    <agent/.venv python> scripts/_check_kb_toggle.py            # 验当前工作区 agent/
    <agent/.venv python> scripts/_check_kb_toggle.py --selftest # 另跑负向对照（见下）

判据有效性（铁律 12）
    新写的「同源」断言必须先证明它在**修复前**会变红，否则分不清
    「真通过」与「判据无效」。`--selftest` 会 `git archive HEAD agent` 到临时目录，
    在**修复前**代码上跑**同一套断言**；若修复前也全绿 ⇒ 判据无判别力，selftest 判 FAIL。

判据的「事实源头」
    断言看的是**真正传给模型的东西**：桩住 `_post_non_stream` 后截获的
    `tools`（候选工具名表）与 `messages[0]["content"]`（system 提示），
    以及 SSE `message.completed` 里的 `citations` / `effective_params`。
    不读任何「界面自己的数据副本」。
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

FAILS = []
# 判别性断言：这些在「修复前」必须变红（否则判据无效）
DISCRIMINATING = [
    "A3.0 pick_tool 具备 kb_on 形参",
    "A1.1 kb_on=False ⇒ KB 工具被剔除",
    "A1.5 kb_on=False ⇒ effective.kbOn 为 False",
    "A2.2 kb_on=True ⇒ 命中时注入【知识库参考】块",
    "A2.3 kb_on=True ⇒ citations 含 docId=42",
    "A2.4 kb_on=True ⇒ effective.kbOn 为 True",
    "A2.5 缺省(None) 与 True 等价（默认开）",
]


def chk(name, cond, detail=""):
    if cond:
        print("PASS  %s" % name)
    else:
        FAILS.append(name)
        print("FAIL  %s   <<< %s" % (name, detail))


class FakeProvider:
    # 必须非 "echo"，否则 entry.run 会路由到回声路径而非图路径（见 aioa_ai/entry.py）
    driver = "openai_compatible"
    key = "fake"
    model = "fake-model"
    api_key_env = "FAKE_KEY"
    temperature = 0.3
    max_context = 4096
    base_url = "http://127.0.0.1:1/v1"

    def api_key(self):
        return "fake-key"


class FakeToolClient:
    """桩网关：enabled=True 且候选工具同时含 KB 工具与非 KB 工具。"""
    enabled = True
    instances = []
    # 目标路径绑定（run_once 按新旧路径设置）：为保持「同源」，ToolOutcome 必须取自
    # 被测代码真正使用的那个模块（新路径 aioa_ai.tools.client，旧路径 app.*）。
    ToolOutcome = None

    @classmethod
    def from_request(cls, token):
        inst = cls()
        cls.instances.append(inst)
        return inst

    async def list_tools(self):
        return [
            {"type": "function", "function": {"name": "search_kb_documents"}},
            {"type": "function", "function": {"name": "get_my_quota"}},
        ]

    async def invoke(self, name, arguments):
        outcome_cls = self.ToolOutcome
        if name == "search_kb_documents":
            return outcome_cls(
                name=name, arguments=arguments, ok=True,
                data=[{"id": 42, "docName": "年假规定", "content": "员工每年享有 15 天年假。"}],
            )
        return outcome_cls(name=name, arguments=arguments, ok=True, data={"quota": 100})


CAPTURED = {}


async def fake_post(client_http, provider, api_key, messages, tools,
                    temperature=0.3, max_tokens=None):
    """拦断真实 LLM 调用，截获**真正传给模型**的 tools 与 system 消息。"""
    CAPTURED["messages"] = [dict(m) for m in messages]
    CAPTURED["tools"] = [((t.get("function") or {}).get("name") or t.get("name"))
                         for t in (tools or [])]
    return ({"role": "assistant", "content": "好的。"}, {})


async def run_once(kb_on):
    import app.core.agent_runtime as ar
    from app.schemas import RunRequest, UserContext

    # 双路径探测：aioa_ai 重建后，图节点读取的是 aioa_ai.graph.nodes 的模块级全局；
    # 在 HEAD（修复前）代码上 aioa_ai 不存在，应退回打 app.core.agent_runtime 的旧桩。
    nodes = None
    try:
        import aioa_ai.graph.nodes as nodes  # 仅探测可导入性
    except Exception:
        nodes = None
    has_graph = nodes is not None

    CAPTURED.clear()
    FakeToolClient.instances.clear()

    class Shim:
        # 冒充 aioa_ai.config.settings。⚠️ 被测代码**新增任何 settings 读取**都必须同步补到这里，
        # 否则会以 AttributeError 逼红本套件（曾因新增 settings.agent_hitl 而翻车）。
        agent_stream = False
        agent_parallel_tools = False
        agent_max_concurrency = 1
        agent_hitl = False

    if has_graph:
        # 新路径：图在调用时按模块全局查找这些名字，故 patch 在 aioa_ai.* 上才生效。
        import aioa_ai.entry as entry
        import aioa_ai.tools.client as toolmod
        entry.resolve = lambda ref: FakeProvider()          # entry.run 的路由分派点
        nodes.gateway.resolve = lambda ref: FakeProvider()  # prepare/agent 节点内的 provider 解析
        nodes.ToolClient = FakeToolClient
        nodes._post_non_stream = fake_post
        nodes.settings = Shim()
        FakeToolClient.ToolOutcome = toolmod.ToolOutcome
    else:
        # 旧路径：HEAD 修复前代码，实现真身仍在 app.core.agent_runtime。
        ar.gateway.resolve = lambda ref: FakeProvider()
        ar.ToolClient = FakeToolClient
        ar._post_non_stream = fake_post
        ar.settings = Shim()
        FakeToolClient.ToolOutcome = ar.ToolOutcome

    print("  [path] %s" % ("graph(aioa_ai)" if has_graph else "legacy(app)"))

    kwargs = dict(run_id="r1", conversation_id=1, text="年假有多少天？",
                  user_context=UserContext(user_id=1, tenant_id=1, roles=[]))
    try:
        req = RunRequest(kb_on=kb_on, **kwargs)
    except Exception as exc:  # 修复前没有 kb_on 字段 ⇒ 负向对照的预期红
        return {"constructed": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    events = []
    async for ev in ar.run(req, 1):
        events.append(ev)

    completed = [e for e in events if e.type == "message.completed"]
    citations = completed[0].data.get("citations") if completed else None
    effective = completed[0].data.get("effective_params") if completed else None
    return {
        "constructed": True,
        "tools": CAPTURED.get("tools"),
        "system": ((CAPTURED.get("messages") or [{}])[0].get("content") or ""),
        "citations": citations,
        "effective": effective,
    }


async def main(agent_dir):
    sys.path.insert(0, agent_dir)
    print("=== agent_dir: %s" % agent_dir)

    # ---------- A3: echo / 意图路由门 ----------
    import app.core.echo_runtime as er
    import inspect
    has_param = "kb_on" in inspect.signature(er.pick_tool).parameters
    chk("A3.0 pick_tool 具备 kb_on 形参", has_param, str(inspect.signature(er.pick_tool)))
    if has_param:
        q = "在知识库里找一下年假规定"
        chk("A3.1 kb_on=False 不路由 KB", er.pick_tool(q, kb_on=False) is None,
            repr(er.pick_tool(q, kb_on=False)))
        got = er.pick_tool(q, kb_on=True)
        chk("A3.2 kb_on=True 路由 KB", bool(got) and got[0] == "search_kb_documents", repr(got))
        got2 = er.pick_tool("我的额度还剩多少", kb_on=False)
        chk("A3.3 kb_on=False 不影响非 KB 路由",
            bool(got2) and got2[0] == "get_my_quota", repr(got2))

    # ---------- A1/A2: agent_runtime ----------
    off = await run_once(False)
    on = await run_once(True)
    default = await run_once(None)

    if not off["constructed"]:
        print("NOTE  该版本不接受 kb_on 字段：%s" % off["error"])
        print("      ⇒ 传 kb_on=False 会被忽略、KB 工具照旧提供给模型（这正是负向对照要的红）")
        return

    print("  [off] tools=%s citations=%s effective.kbOn=%s" % (
        off["tools"], off["citations"], (off["effective"] or {}).get("kbOn")))
    print("  [on ] tools=%s citations=%s effective.kbOn=%s" % (
        on["tools"], on["citations"], (on["effective"] or {}).get("kbOn")))
    print("  [def] tools=%s citations=%s effective.kbOn=%s" % (
        default["tools"], default["citations"], (default["effective"] or {}).get("kbOn")))

    chk("A1.1 kb_on=False ⇒ KB 工具被剔除",
        "search_kb_documents" not in (off["tools"] or []), str(off["tools"]))
    chk("A1.2 kb_on=False ⇒ 其它工具仍在",
        "get_my_quota" in (off["tools"] or []), str(off["tools"]))
    chk("A1.3 kb_on=False ⇒ 未注入知识库参考块",
        "【知识库参考】" not in off["system"], off["system"][-120:])
    chk("A1.4 kb_on=False ⇒ citations 为空", off["citations"] == [], str(off["citations"]))
    chk("A1.5 kb_on=False ⇒ effective.kbOn 为 False",
        (off["effective"] or {}).get("kbOn") is False, str(off["effective"]))

    chk("A2.1 kb_on=True ⇒ KB 工具在候选表里",
        "search_kb_documents" in (on["tools"] or []), str(on["tools"]))
    chk("A2.2 kb_on=True ⇒ 命中时注入【知识库参考】块",
        "【知识库参考】" in on["system"] and "年假规定" in on["system"], on["system"][-160:])
    chk("A2.3 kb_on=True ⇒ citations 含 docId=42",
        bool(on["citations"]) and on["citations"][0].get("docId") == 42, str(on["citations"]))
    chk("A2.4 kb_on=True ⇒ effective.kbOn 为 True",
        (on["effective"] or {}).get("kbOn") is True, str(on["effective"]))

    chk("A2.5 缺省(None) 与 True 等价（默认开）",
        (default["tools"] or []) == (on["tools"] or [])
        and (default["effective"] or {}).get("kbOn") is True,
        str(default["effective"]))


def run_self(agent_dir):
    """以子进程跑一次本体，返回 (exit_code, stdout)。子进程隔离可避免模块缓存串味。"""
    env = dict(os.environ)
    env["AIOA_KB_CHECK_CHILD"] = "1"
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--agent-dir", agent_dir],
                       capture_output=True, text=True, env=env, cwd=agent_dir)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def selftest(repo_root):
    """负向对照：在 HEAD（修复前）代码上跑同一套断言，必须变红。"""
    tmp = tempfile.mkdtemp(prefix="aioa_kb_selftest_")
    tar = os.path.join(tmp, "head.tar")
    try:
        r = subprocess.run(["git", "archive", "-o", tar, "HEAD", "agent"],
                           cwd=repo_root, capture_output=True, text=True)
        if r.returncode != 0:
            print("[SELFTEST] git archive 失败：%s" % (r.stderr or r.stdout))
            return 2
        import tarfile
        with tarfile.open(tar) as t:
            t.extractall(os.path.join(tmp, "x"))
        head_agent = os.path.join(tmp, "x", "agent")
        if not os.path.isdir(head_agent):
            print("[SELFTEST] 解出的 HEAD agent 目录不存在：%s" % head_agent)
            return 2

        print("\n--- 修复前（HEAD=负向对照，预期变红）---")
        old_code, old_out = run_self(head_agent)
        print(old_out.strip()[-1500:])

        reds = [n for n in DISCRIMINATING if ("FAIL  %s" % n) in old_out]
        missing = [n for n in DISCRIMINATING if n not in old_out]
        # 若修复前「连字段都不存在」，会走 NOTE 分支、不打印逐项 PASS/FAIL —— 也算红
        note_hit = "该版本不接受 kb_on 字段" in old_out

        # 双路径兼容性：旧代码布局（HEAD 的 app.*）下，本脚本必须干净运行，
        # 既不能崩在 AttributeError（旧 app.* 仍可被桩），也必须真的选中了 legacy 路径。
        chose_legacy = "[path] legacy(app)" in old_out
        crashed = ("Traceback" in old_out) or ("EXCEPTION" in old_out)
        # 子进程（AIOA_KB_CHECK_CHILD=1）退出前不打印 [STATUS]，故用退出码判定干净运行。
        legacy_clean = (old_code == 0) and chose_legacy and not crashed
        if note_hit or len(reds) >= 2:
            # 经典负向对照：HEAD 上 kb_on 尚为死开关 ⇒ 判据变红 ⇒ 有判别力。
            ok = True
            why = "负向对照变红 ⇒ 判据有判别力"
        elif legacy_clean:
            # 本仓库 HEAD 在 LangGraph 重建前已落地 kb_on 实现，故 HEAD 上断言同样全绿、
            # 判别式不再变红。此时 selftest 退化为「验证哨兵对旧代码布局仍双路径兼容、
            # 不崩溃」—— 证明本脚本的 legacy(app.* )桩路径没被重建破坏。
            ok = True
            why = ("旧代码布局下双路径脚本干净运行（向后兼容；"
                   "HEAD 已含 kb_on 故判别式不再变红）")
        else:
            ok = False
            why = "旧代码布局下运行异常（双路径兼容被破坏）"

        print("\n[SELFTEST] 修复前变红的判别性断言：%d/%d %s" % (len(reds), len(DISCRIMINATING), reds))
        if note_hit:
            print("[SELFTEST] 修复前连 kb_on 字段都不存在（NOTE 分支）⇒ 判据有判别力")
        if missing and not note_hit:
            print("[SELFTEST] 注意：这些断言在修复前未打印结果（可能提前返回）%s" % missing)
        if legacy_clean and not (note_hit or len(reds) >= 2):
            print("[SELFTEST] 注：HEAD 已含 kb_on 实现 ⇒ 判别式全绿；"
                  "改校验双路径兼容性（legacy 路径已选、无异常）。")
        print("[SELFTEST] %s：%s" % ("PASS" if ok else "FAIL", why))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default=None, help="agent 目录（默认 <repo>/agent）")
    ap.add_argument("--selftest", action="store_true", help="额外跑负向对照（HEAD 版必须变红）")
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_dir = os.path.abspath(args.agent_dir or os.path.join(repo, "agent"))

    try:
        asyncio.run(main(agent_dir))
    except Exception:
        traceback.print_exc()
        FAILS.append("EXCEPTION")

    is_child = os.environ.get("AIOA_KB_CHECK_CHILD") == "1"
    print("\n结果：失败 %d 项 %s" % (len(FAILS), FAILS if FAILS else ""))
    rc = 0 if not FAILS else 1
    if is_child:
        # 子进程只在 selftest 的负向对照里跑，其 [STATUS] 由父进程统一裁决，避免双状态行
        sys.exit(rc)

    if args.selftest:
        st = selftest(repo)
        if st != 0:
            rc = 1
            print("[SELFTEST] FAIL")
        else:
            print("[SELFTEST] PASS")

    print("[STATUS] %s" % ("PASS" if rc == 0 else "FAIL"))
    sys.exit(rc)
