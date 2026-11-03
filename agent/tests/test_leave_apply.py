# -*- coding: utf-8 -*-
"""请假发起 + 指定处理人：意图闸 / 字段卡 / 候选预取。

## 为什么要有这一层

请假要 4~5 项信息（假种、起止、事由、交给谁）。若交给模型用正文追问，实测会变成
五六轮往返，且假种码经常靠猜（猜错被服务端拒，用户被迫重填）。
所以这里：代码先把候选查好 → 合成一张字段卡 → 一次填完。

## 用例口径

  L1  触发面：请假类词 + 指派语义；问政策/查记录/陈述事实都**不**触发
  L2  候选缺失时不弹空控件（宁可不弹，也不给一张点了没反应的卡）
  L3  字段卡形状：假种 select、起止 date、事由 textarea、处理人 searchable select
  L4  候选上限与脏数据过滤
  L5  提示块必须给出 userId（否则模型不知道 assigneeUserId 该填什么）
"""
from __future__ import annotations

import asyncio

from aios_ai.intent import leave_apply as la

# ---------------------------------------------------------------- L1 触发面

def test_trigger_with_assign():
    for t in ("帮我请个假，交给张三代批", "我明天调休，让李四处理",
              "年假交给王五审批", "请一天假，指定赵六负责"):
        assert la.needs_handler_pick(t), t


def test_no_trigger_without_assign():
    """只说「帮我请假」⇒ 走既有表单链路，本闸不介入（零回归）。"""
    for t in ("帮我请假", "我要休年假", "帮我请个假"):
        assert not la.needs_handler_pick(t), t


def test_no_trigger_for_question_or_query():
    for t in ("请假流程是什么", "年假有几天", "请假要给谁看",
              "我的请假记录查一下", "上个月的请假批了吗"):
        assert not la.needs_handler_pick(t), t


def test_no_trigger_for_short_or_empty():
    assert not la.needs_handler_pick("")
    assert not la.needs_handler_pick(None)
    assert not la.needs_handler_pick("假")


# ---------------------------------------------------------------- L2/L3 字段卡

TYPES = [
    {"code": "annual", "name": "年假", "needProof": False},
    {"code": "personal", "name": "事假", "needProof": False},
    {"code": "sick", "name": "病假", "needProof": True},
]
HANDLERS = [
    {"userId": 11, "name": "张三", "jobTitle": "算法部负责人"},
    {"userId": 12, "name": "李四", "jobTitle": None, "dutyCode": "DEPT_DUTY"},
]


def test_card_shape():
    card = la.build_card(TYPES, HANDLERS)
    assert card and card["name"] == "ask_user"
    fields = card["arguments"]["fields"]
    ids = [f["id"] for f in fields]
    assert ids == ["leave_type", "start", "end", "reason", "handler"]
    by = {f["id"]: f for f in fields}
    assert by["leave_type"]["type"] == "select"
    assert by["start"]["type"] == "date" and by["end"]["type"] == "date"
    assert by["reason"]["type"] == "textarea"
    # 处理人必须是**可检索**下拉：人一多，纯菜单滚不动
    assert by["handler"]["type"] == "select" and by["handler"]["searchable"] is True
    assert by["handler"]["required"] is True
    # 需证明的假种要在标签上提示，避免提交时才被拒
    sick = [o for o in by["leave_type"]["options"] if o["value"] == "sick"][0]
    assert "需证明" in sick["label"]


def test_handler_value_is_userid():
    card = la.build_card(TYPES, HANDLERS)
    opts = {f["id"]: f for f in card["arguments"]["fields"]}["handler"]["options"]
    assert opts[0]["value"] == 11           # 机器值必须是 userId，不是姓名
    assert "张三" in opts[0]["label"]
    assert "算法部负责人" in opts[0]["label"]
    # 无 jobTitle 时退到 dutyCode，两个都没有就只显示姓名
    assert "DEPT_DUTY" in opts[1]["label"]


def test_card_none_without_handlers():
    """查不到可审批人 ⇒ 不弹卡（弹了也没人能选）。"""
    assert la.build_card(TYPES, []) is None
    assert la.build_card(TYPES, None) is None


def test_card_falls_back_to_text_type_when_no_types():
    """假种目录查不到时退化为文本输入，而不是少一个必填项。"""
    card = la.build_card([], HANDLERS)
    by = {f["id"]: f for f in card["arguments"]["fields"]}
    assert by["leave_type"]["type"] == "text"
    assert by["leave_type"]["required"] is True


# ---------------------------------------------------------------- L4 上限与脏数据

def test_caps():
    many_types = [{"code": f"t{i}", "name": f"假{i}"} for i in range(50)]
    many_handlers = [{"userId": i, "name": f"人{i}"} for i in range(1, 100)]
    card = la.build_card(many_types, many_handlers)
    by = {f["id"]: f for f in card["arguments"]["fields"]}
    assert len(by["leave_type"]["options"]) <= la.MAX_LEAVE_TYPES
    assert len(by["handler"]["options"]) <= la.MAX_HANDLERS


def test_dirty_handlers_skipped():
    """没有 userId 的成员不能进候选：建不出审批任务。"""
    card = la.build_card(TYPES, [{"name": "幽灵"}, {"userId": 21, "name": "真人"}])
    opts = {f["id"]: f for f in card["arguments"]["fields"]}["handler"]["options"]
    assert [o["value"] for o in opts] == [21]


# ---------------------------------------------------------------- L5 提示块

def test_block_contains_userid():
    block = la.build_block(TYPES, HANDLERS)
    assert "userId=11" in block
    assert "submit_leave_request" in block
    assert "assigneeUserId" in block
    # 必须明确「别再追问」：否则模型拿到回填值仍会再问一遍
    assert "不要" in block


def test_block_empty_without_handlers():
    assert la.build_block(TYPES, []) == ""


# ---------------------------------------------------------------- 预取

class _Outcome:
    def __init__(self, ok, data=None, error=""):
        self.ok = ok
        self.data = data
        self.error = error


class _Client:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    async def invoke(self, name, args=None):
        self.calls.append(name)
        v = self.mapping.get(name)
        if isinstance(v, Exception):
            raise v
        return v or _Outcome(True, [])


def test_prefetch_both_sources():
    client = _Client({
        "list_leave_types": _Outcome(True, TYPES),
        "list_approval_handlers": _Outcome(True, HANDLERS),
    })
    types, handlers = asyncio.run(la.prefetch(client))
    assert len(types) == 3 and len(handlers) == 2
    assert set(client.calls) == {"list_leave_types", "list_approval_handlers"}


def test_prefetch_tolerates_failures():
    """单侧失败不能打挂 run：返回空列表即可（build_card 会据此决定不弹卡）。"""
    client = _Client({
        "list_leave_types": RuntimeError("boom"),
        "list_approval_handlers": _Outcome(False, error="未绑定机构"),
    })
    types, handlers = asyncio.run(la.prefetch(client))
    assert types == [] and handlers == []
