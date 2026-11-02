# -*- coding: utf-8 -*-
"""动态字段协议（`ask_user.fields`）：归一化与回填形状。

## 为什么需要这层归一

字段卡把「该问哪几样 / 用什么控件」交给模型（语义判断），
但**模型给的 schema 不可信**：类型可能拼错、依赖可能指向不存在的字段、
两个字段互相依赖（成环）、一口气给九个字段。这些都必须在服务端收敛掉，
否则前端要么渲染出死控件，要么在依赖求值里来回跳（控件闪烁、确认按钮乱变）。

## 收敛原则（每条都有用例）

  F1  未知 type ⇒ text（宁可让人打字，也不要渲染空白块）
  F2  select/multi 没有候选 ⇒ 降级 text（没有选项的「菜单」是死控件）
  F3  id 重复 ⇒ 保留第一个；缺 id/label ⇒ 丢弃
  F4  字段超过 6 个 ⇒ 截断（再多就该拆成两问）
  F5  依赖指向不存在的字段 / 指向自己 ⇒ 剪掉条件（**保留字段**）
  F6  依赖成环 ⇒ 剪掉闭环那条边（字段退化成"总是显示"），绝不进入死循环
  F7  op 非法 ⇒ 按 eq；in 缺数组 ⇒ 剪掉条件
  F8  有 fields ⇒ 旧 options/text_input 一律丢弃（一张卡不能两套控件两套规则）
  F9  回填 {values} 原样交给模型；value 缺失时取第一个非空字段
  F10 没有 fields 时载荷形状**逐字节不变**（老断言/老客户端零影响）
"""
from __future__ import annotations

from aios_ai.graph import nodes
from aios_ai.tools import ask_user as au


def _spec(*fields, **kw) -> dict:
    return au.build_clarification({"question": "q", "fields": list(fields), **kw})


def test_unknown_type_falls_back_to_text() -> None:
    """F1：模型拼错类型（rang/textt）不能让前端拿到未知 type。"""
    s = _spec({"id": "a", "label": "A", "type": "rang"},
              {"id": "b", "label": "B", "type": "textt"})
    assert [f["type"] for f in s["fields"]] == ["text", "text"]


def test_menu_without_options_downgrades_to_text() -> None:
    """F2：没有候选项的菜单是死控件 —— 降级成文本框，用户至少能填。"""
    s = _spec({"id": "a", "label": "选一个", "type": "select", "options": []},
              {"id": "b", "label": "多选", "type": "multi"})
    assert [f["type"] for f in s["fields"]] == ["text", "text"]


def test_dup_and_invalid_fields_are_dropped() -> None:
    """F3：重复 id 保留第一个；缺 id / 缺 label 的直接丢。"""
    s = _spec({"id": "a", "label": "第一个", "type": "text"},
              {"id": "a", "label": "重复的", "type": "number"},
              {"id": "", "label": "没 id"},
              {"id": "c"},
              {"id": "d", "label": "正常"})
    ids = [f["id"] for f in s["fields"]]
    assert ids == ["a", "d"]
    assert s["fields"][0]["label"] == "第一个"


def test_fields_capped_at_six() -> None:
    """F4：超过 6 个字段截断（再多就该拆成两问，而不是做成问卷）。"""
    raw = [{"id": f"f{i}", "label": f"字段{i}"} for i in range(9)]
    s = _spec(*raw)
    assert len(s["fields"]) == au.MAX_FIELDS == 6
    assert [f["id"] for f in s["fields"]] == ["f0", "f1", "f2", "f3", "f4", "f5"]


def test_dangling_and_self_condition_are_pruned() -> None:
    """F5：依赖指向不存在的字段 / 指向自己 ⇒ 只剪条件，字段本人保留。"""
    s = _spec({"id": "a", "label": "A",
               "visible_when": {"field": "nope", "op": "eq", "value": 1}},
              {"id": "b", "label": "B",
               "visible_when": {"field": "b", "op": "eq", "value": 1}})
    assert "visible_when" not in s["fields"][0]
    assert "visible_when" not in s["fields"][1]


def test_cycle_is_broken_not_hung() -> None:
    """F6：a←b、b←a 成环 ⇒ 至少剪掉一条边，且不进入死循环。

    死循环的后果不是报错，而是页面上控件反复显隐（闪烁）+ 确认按钮灰度乱跳。
    """
    s = _spec({"id": "a", "label": "A", "visible_when": {"field": "b", "value": 1}},
              {"id": "b", "label": "B", "visible_when": {"field": "a", "value": 1}})
    conds = [f.get("visible_when") for f in s["fields"]]
    assert conds.count(None) >= 1, f"环没被剪开：{conds}"
    # 剪开之后仍是一条合法链（最多一条边）
    assert sum(1 for c in conds if c) <= 1


def test_bad_op_and_in_value() -> None:
    """F7：op 不认识 ⇒ 按 eq；in 的 value 不是数组 ⇒ 剪掉条件（不乱比较）。"""
    s = _spec({"id": "a", "label": "A", "visible_when": {"field": "z", "op": "eq", "value": 1}},
              {"id": "z", "label": "Z"},
              {"id": "b", "label": "B", "visible_when": {"field": "z", "op": "wat", "value": 2}},
              {"id": "c", "label": "C", "visible_when": {"field": "z", "op": "in", "value": "x"}})
    assert s["fields"][2]["visible_when"] == {"field": "z", "op": "eq", "value": 2}
    assert "visible_when" not in s["fields"][3]


def test_fields_win_over_legacy_options() -> None:
    """F8：字段卡与旧选项/卡级输入不能共存（两套控件两套必填规则）。"""
    s = au.build_clarification({
        "question": "q",
        "options": [{"value": "a", "label": "A"}],
        "text_input": {"label": "补充"},
        "fields": [{"id": "x", "label": "X", "type": "text"}],
    })
    assert s["suggested_options"] == []
    assert "text_input" not in s
    assert s["fields"][0]["id"] == "x"


def test_legacy_payload_shape_untouched() -> None:
    """F10：没有 fields 时，载荷键与改造前**完全一致**（老断言零影响）。"""
    s = au.build_clarification({"question": "q", "options": [{"value": "a", "label": "A"}]})
    assert set(s) == {"question", "suggested_options"}


def test_answer_with_values_is_passed_through() -> None:
    """F9：字段卡的 values 原样交给模型（键就是 schema 里的 id）。"""
    out = nodes._clarify_answer({
        "value": "meeting", "label": "约会议", "text": "",
        "values": {"action": "meeting", "when": "2026-11-03T15:00", "notify": []},
    })
    assert out["values"] == {"action": "meeting", "when": "2026-11-03T15:00", "notify": []}
    assert out["value"] == "meeting"


def test_answer_values_fill_missing_value() -> None:
    """F9：只给 values、没给 value 时，取第一个非空字段当主值（别把答案丢了）。"""
    out = nodes._clarify_answer({"values": {"a": "", "b": "内容", "c": []}})
    assert out["value"] == "内容"
    assert out["values"]["b"] == "内容"


def test_answer_without_values_keeps_three_keys() -> None:
    """F10：老形状回填不带 values 键（多出来的键只在真用到时出现）。"""
    assert set(nodes._clarify_answer({"value": "v", "label": "l", "text": "t"})) == \
        {"value", "label", "text"}
    assert set(nodes._clarify_answer("wob1")) == {"value", "text"}


def test_empty_values_dict_not_carried() -> None:
    """空 values 等于没给 —— 不要给模型塞一个空对象增加噪音。"""
    assert "values" not in nodes._clarify_answer({"value": "v", "values": {}})
