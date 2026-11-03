"""跨源数据聚合：把「总结周报」这类语义翻译成一次确定性的多源扇出。

## 为什么不是「让模型自己调工具」

工具存在 ≠ 模型会用。本项目已有两次同类实测：
  * 模糊实体（2026-11-02）：工具齐备，模型仍回「请提供姓名」，只好加确定性预取；
  * 企微写操作：模型看见工具却写散文反问，只好加确定性闸。

「周报」更严重 —— 它要求**多个源都查过**。模型的自然倾向是查一两个源就开始写，
而用户拿到的是「只覆盖企微会话、完全没看邮箱和审批」的半份周报，且**无法察觉**。
所以这里把「查哪些源、怎么并发、失败怎么办」交给代码，模型只负责组织语言。

## 与知识库预检索的分工

知识库（``knowledge/retrieval.py``）走自己的路：它是**语义检索**，需要 query 改写、
阈值、chunk 拼装，且受 ``kb_on`` 对话级开关控制，不该被这里重复实现。
本模块只负责**结构化数据源**（会话 / 邮件 / 待办 / 审批 / 日程），
两者产出的引用最终在 ``nodes.py`` 里合并去重。

## 失败口径（与审批引擎的「缺位顺延」同源）

单个源失败/超时/未授权**绝不打挂整条 run**，而是：
  1. 记进 ``SourceResult.error``；
  2. 在注入块的末尾**显式列出「本轮未能获取的源」**。
第 2 条是关键：静默跳过会让模型以为「已经查全了」，进而把半份数据写成完整周报。
把缺口告诉模型，它才会在回答里说「邮箱数据本次不可用」。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from aios_ai.knowledge import sources
from aios_ai.knowledge.kb import _citations_from_tool

logger = logging.getLogger("aios.ai.aggregate")

# ---------------------------------------------------------------------------
# 一、意图闸：什么话该触发「扇出多源」
# ---------------------------------------------------------------------------
# 口径刻意收窄 —— 触发即意味着**多发若干次工具调用**，误触发是实打实的延迟与配额消耗。
# 因此只认「明确的汇总诉求」，不认单点查询：
#   ✅ 总结这周工作 / 写个周报 / 汇总一下项目进展 / 复盘本月
#   ❌ 我上周请了几天假（这是查询，不是汇总）
AGGREGATE_RE = re.compile(
    r"(周报|日报|月报|季报|半月报|年报)"
    r"|(总结|汇总|归纳|整理).{0,6}(一下|这|本|近期|最近|本周|上周|本月|上月|工作|进展|情况)"
    r"|(这|本|上周|本周|最近|近期).{0,4}(周|月).{0,4}(工作|情况|进展|总结|汇报)"
    r"|(复盘|小结|汇报材料|工作汇报|述职)"
)

# 反向闸：出现这些词说明用户在问「怎么写/模板」，不是要我们真的去汇总。
_TEMPLATE_HINT_RE = re.compile(r"(怎么写|如何写|模板|格式|范例|范文|要求是什么)")


def is_aggregate_request(text: str | None) -> bool:
    """是否属于「跨源汇总」诉求。空文本/闲聊一律 False。"""
    t = (text or "").strip()
    if len(t) < 3:
        return False
    if _TEMPLATE_HINT_RE.search(t):
        return False
    return bool(AGGREGATE_RE.search(t))


# ---------------------------------------------------------------------------
# 二、源计划：每个源问什么
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceCall:
    """一个待扇出的数据源调用。

    ``tool`` 用**短名**（不带 ``mcp__<server>__`` 前缀），因为连接器是否在线、
    实际 serverCode 是什么，要到运行时看工具清单才知道（见 :func:`resolve`）。
    """

    code: str          # 归属数据源（citation 的 source）
    tool: str          # 工具短名
    args: dict         # 入参
    label: str         # 人看的动作名
    priority: int      # 越小越先展示


# 「周报」类诉求的默认扇出面：覆盖「我做了什么 / 别人跟我说了什么 / 我欠了什么」。
# 刻意不查 ``doc_search``：企微文档库通常是制度/资料，不属于「本周工作」，
# 查了反而把周报写歪成资料汇编。用户真要看文档会明说。
DEFAULT_PLAN: tuple[SourceCall, ...] = (
    SourceCall("wecom_cli", "recent_group_sessions", {"days": 7}, "最近会话", 10),
    SourceCall("wecom_cli", "todo_list", {"limit": 20}, "待办", 20),
    SourceCall("wecom_cli", "calendar_list", {}, "日历", 30),
    SourceCall("qq_mail", "list_messages", {"limit": 10}, "邮件列表", 40),
    SourceCall("approval", "list_my_approvals", {}, "我的审批", 50),
)

# 每个源最多注入多少字符：周报的输入是多源拼装，不设上限会把上下文撑爆，
# 也会让模型把「抓到的最长那段」当成重点。
MAX_CHARS_PER_SOURCE = 2200
# 单源超时：宁可缺一个源并在回答里说明，也不要让整轮卡住。
SOURCE_TIMEOUT = 12.0


@dataclass
class SourceResult:
    """一个源的执行结果。"""

    code: str
    label: str
    priority: int
    ok: bool = False
    text: str = ""
    count: int = 0
    error: str = ""
    citations: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"source": self.code, "label": self.label, "ok": self.ok,
                "count": self.count, "error": self.error}


# ---------------------------------------------------------------------------
# 三、工具解析：把「短名」对上「真实工具名」
# ---------------------------------------------------------------------------
def _tool_names(tools: list[dict] | None) -> set[str]:
    out: set[str] = set()
    for t in tools or []:
        fn = (t or {}).get("function") or {}
        n = fn.get("name")
        if n:
            out.add(str(n))
    return out


def resolve_plan(tools: list[dict] | None,
                 plan: tuple[SourceCall, ...] = DEFAULT_PLAN) -> list[tuple[SourceCall, str]]:
    """把计划里的短名解析成**本轮真实可用**的工具名。

    匹配规则：MCP 工具名为 ``mcp__<serverCode>__<tool>``，故按后缀精确匹配；
    网关工具（无前缀）按原名匹配。对不上 = 该连接器本轮不可用，直接跳过
    （不报错 —— 没装企微的用户不该因为「周报」这个词而报错）。
    """
    names = _tool_names(tools)
    out: list[tuple[SourceCall, str]] = []
    for call in plan:
        if call.code == "approval" or not call.tool:
            actual = call.tool if call.tool in names else ""
        elif call.tool in names:
            actual = call.tool
        else:
            actual = ""
            for n in names:
                if n.startswith("mcp__") and n.endswith("__" + call.tool):
                    # 同一个工具名可能挂在多个 server 上：优先与 code 同名的 server
                    parts = n.split("__", 2)
                    if len(parts) >= 3 and parts[1] == call.code:
                        actual = n
                        break
                    if not actual:
                        actual = n
        if actual:
            out.append((call, actual))
    return out


# ---------------------------------------------------------------------------
# 四、渲染：把结果拼成给模型看的素材包
# ---------------------------------------------------------------------------
def _render_payload(data) -> str:
    """工具返回 → 可读文本（超长截断）。"""
    payload = sources.normalize_payload(data)
    if isinstance(payload, str):
        s = payload.strip()
    elif isinstance(payload, (list, dict)):
        s = json.dumps(payload, ensure_ascii=False, indent=None)
    else:
        s = str(payload)
    if len(s) > MAX_CHARS_PER_SOURCE:
        s = s[:MAX_CHARS_PER_SOURCE] + "…（已截断）"
    return s


def build_block(results: list[SourceResult], total_planned: int,
                kb: dict | None = None) -> str:
    """把多源结果拼成注入 system 的素材包。

    形状刻意「先结论后素材」：顶部一句话说清有几个源成功/失败，
    否则模型会把「没查到的源」当成「没有数据」，写出虚假的完整性。

    ``kb`` = 知识库的命中情况 ``{"ok": bool, "count": int}``：
    知识库由 ``knowledge/retrieval.py`` 独立预检索（语义检索 + 阈值 + 切片），
    本模块不重复实现，但**必须把它算进覆盖面**——否则「周报」的来源清单里
    少了内部知识库，用户会以为 AI 只看了聊天记录。
    """
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    if not ok and not failed and not kb:
        return ""
    lines: list[str] = []
    lines.append("\n\n【本轮已自动汇总的数据源】（代码已代为拉取，无需重复调用同样的工具）")
    total_ok = len(ok) + (1 if kb and kb.get("ok") else 0)
    head = f"成功 {total_ok} 个源"
    if failed:
        head += f"，失败 {len(failed)} 个"
    lines.append(head + "。")
    if kb:
        lines.append("")
        lines.append("### 内部知识库 · 语义检索")
        if kb.get("ok"):
            lines.append(f"已命中 {kb.get('count', 0)} 个片段，原文见上文「参考片段」。")
        else:
            lines.append("已检索但**未命中**（没有与该问题相关的内部文档）。")
        lines.append("")
    if ok:
        for r in sorted(ok, key=lambda x: x.priority):
            head = f"### {sources.source_label(r.code)} · {r.label}"
            if r.count:
                head += f"（{r.count} 条）"
            lines.append(head)
            lines.append(r.text or "（空）")
            lines.append("")
    if failed:
        lines.append("### 本轮未能获取的源")
        for r in failed:
            lines.append(f"- {sources.source_label(r.code)} · {r.label}：{r.error or '不可用'}")
        lines.append("")
    lines.append(
        "【汇总要求】\n"
        "1. 按「谁 / 做了什么 / 何时 / 结果」组织，不要按数据源逐条罗列原始记录。\n"
        "2. **每一条要点都要能对上上面的源**；引用来源时写「据企业微信会话」「据邮箱邮件」这样的短语。\n"
        "3. 若某源本次未获取到（见上），必须在回答末尾**如实说明该源缺失**，"
        "不得用其它源的内容冒充它的覆盖范围。\n"
        "4. 数据为空就直说「本周在 X 上没有记录」，不要编造。\n"
        "5. 时间/数字必须来自素材，不要推算或补全。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 五、执行：并发扇出
# ---------------------------------------------------------------------------
async def gather(tool_client, tools: list[dict] | None,
                 plan: tuple[SourceCall, ...] = DEFAULT_PLAN) -> tuple[list[SourceResult], list[dict]]:
    """并发执行计划，返回 (源结果, 引用条目)。

    ``tool_client`` 需具备 ``async invoke(name, args) -> outcome``（.ok/.data/.error）。
    """
    pairs = resolve_plan(tools, plan)
    if not pairs:
        return [], []

    async def run_one(call: SourceCall, actual: str) -> SourceResult:
        res = SourceResult(code=call.code, label=call.label, priority=call.priority)
        try:
            outcome = await asyncio.wait_for(tool_client.invoke(actual, dict(call.args)),
                                             timeout=SOURCE_TIMEOUT)
        except asyncio.TimeoutError:
            res.error = f"超时（>{SOURCE_TIMEOUT:.0f}s）"
            return res
        except Exception as exc:                      # noqa: BLE001 —— 单源失败不外溢
            res.error = str(exc)[:200]
            return res
        if not getattr(outcome, "ok", False):
            res.error = str(getattr(outcome, "error", "") or "调用失败")[:200]
            return res
        payload = sources.normalize_payload(getattr(outcome, "data", None))
        if payload in (None, "", [], {}):
            # 明确区分「查到了但是空」与「没查成」：前者是有效结论（本周无待办）
            res.ok = True
            res.text = "（空）"
            res.count = 0
            return res
        res.ok = True
        res.count = len(payload) if isinstance(payload, list) else 1
        res.text = _render_payload(payload)
        res.citations = _citations_from_tool(actual, outcome)
        return res

    results = await asyncio.gather(
        *(run_one(c, n) for c, n in pairs), return_exceptions=False)
    citations: list[dict] = []
    seen: set = set()
    for r in results:
        for c in r.citations:
            key = c.get("docId")
            if key and key not in seen:
                seen.add(key)
                citations.append(c)
    logger.info("aggregate: %d/%d 源成功，%d 条引用",
                sum(1 for r in results if r.ok), len(results), len(citations))
    return list(results), citations


async def collect(tool_client, tools: list[dict] | None, text: str,
                  plan: tuple[SourceCall, ...] = DEFAULT_PLAN,
                  kb: dict | None = None
                  ) -> tuple[str, list[dict], list[dict]]:
    """对外唯一入口：判意图 → 扇出 → 返回 (注入块, 引用, 源观测)。

    非汇总诉求返回 ``("", [], [])``，调用方据此**完全不改动**既有链路。
    """
    if not is_aggregate_request(text):
        return "", [], []
    results, citations = await gather(tool_client, tools, plan)
    block = build_block(results, len(plan), kb)
    return block, citations, [r.as_dict() for r in results]
