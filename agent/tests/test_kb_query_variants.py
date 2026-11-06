"""查询变体与多路召回合并（docs/74 根因 5）。

背景：原先 `pre_retrieve` 把**整句**当关键词丢给检索。「帮我统计下四川省的省级非遗项目
有多少个?」被拆成 19 个 2-gram，其中「帮我/我统/计下/有多/少个」全是噪声，
真正有区分度的只有「非遗」—— 覆盖率被稀释，排序随之失准。
这里验证：清洗后核心词保留、噪声去掉、多路结果能正确合并去重。
"""
from __future__ import annotations

import asyncio

from aios_ai.knowledge import retrieval
from aios_ai.knowledge.retrieval import query_variants, _merge_hits


def test_variants_strip_polite_prefix_and_question_tail():
    vs = query_variants("帮我统计下四川省的省级非遗项目有多少个?")
    assert vs[0] == "帮我统计下四川省的省级非遗项目有多少个?"
    cleaned = [v for v in vs if v != vs[0]]
    assert cleaned, "清洗句必须生成"
    # 「帮我」「多少个」必须被去掉，核心词必须留下
    assert "帮我" not in cleaned[0]
    assert "多少个" not in cleaned[0]
    assert "非遗" in cleaned[0]


def test_variants_keep_quoted_title():
    vs = query_variants("《2026.2省级非遗项目名录》里成都市有多少个")
    assert any("2026.2省级非遗项目名录" == v for v in vs)


def test_variants_strip_long_prefix_before_short_one():
    """B4：`替我` 写在 `替我看看` 前面会只剥短词，把「看看」留下当噪声。"""
    vs = query_variants("替我看看四川省非遗项目有多少个")
    cleaned = [v for v in vs if v != vs[0]]
    assert cleaned, f"清洗句必须生成: {vs}"
    assert "看看" not in cleaned[0], f"「看看」应被一起剥掉: {cleaned[0]}"
    assert cleaned[0].startswith("四川省"), f"核心词应从「四川省」开始: {cleaned[0]}"


def test_variants_strip_prefix_leaving_no_bare_pronoun():
    """B4：`麻烦` 先于 `麻烦你` ⇒ 剥完只剩一个「你」。"""
    vs = query_variants("麻烦你统计一下报销流程")
    cleaned = [v for v in vs if v != vs[0]]
    assert cleaned, f"清洗句必须生成: {vs}"
    assert not cleaned[0].startswith("你"), f"不应留下孤立的「你」: {cleaned[0]}"
    assert "报销流程" in cleaned[0]


def test_variants_dedup_and_nonempty():
    assert query_variants("报销流程") == ["报销流程"] or "报销流程" in query_variants("报销流程")
    assert query_variants("") == []
    assert query_variants(None) == []
    vs = query_variants("《报销制度》")
    assert len(vs) == len(set(vs)), f"变体不应重复: {vs}"


def test_merge_dedups_by_doc_and_chunk_keeping_higher_score():
    a = [{"id": 1, "chunkIndex": 3, "score": 0.2, "snippet": "A"},
         {"id": 1, "chunkIndex": 4, "score": 0.9, "snippet": "B"}]
    b = [{"id": 1, "chunkIndex": 3, "score": 0.7, "snippet": "A2"}]
    merged = _merge_hits([a, b])
    assert len(merged) == 2, f"同片段必须去重: {merged}"
    same = [m for m in merged if m["chunkIndex"] == 3][0]
    assert same["score"] == 0.7, "同一片段取最高分"
    assert merged[0]["score"] >= merged[-1]["score"], "按分数降序"


def test_merge_tolerates_dirty_rows():
    assert _merge_hits([[None, "x", {}]]) == [{}]
    assert _merge_hits([]) == []


class _Outcome:
    def __init__(self, data):
        self.ok = True
        self.data = data


class _Client:
    """记录每一次检索调用，按关键词返回不同片段（模拟「原句/清洗句命中不同内容」）。"""

    def __init__(self):
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append(args.get("keyword"))
        if "帮我" in (args.get("keyword") or ""):
            return _Outcome([{"id": 9, "docName": "名录.xlsx", "chunkIndex": 1,
                              "snippet": "| 1 | 川剧 |", "score": 0.3}])
        return _Outcome([{"id": 9, "docName": "名录.xlsx", "chunkIndex": 0,
                          "snippet": "【统计摘要】数据行合计：1241 条", "score": 0.8}])


def test_pre_retrieve_queries_all_variants_and_merges():
    client = _Client()
    block, citations = asyncio.run(
        retrieval.pre_retrieve(client, "帮我统计下四川省的省级非遗项目有多少个?", 5, 0.5, "hybrid", "ALL"))
    assert len(client.calls) >= 2, f"应当对多个变体各查一次: {client.calls}"
    # 两路的片段都要在参考块里（原句命中正文、清洗句命中统计摘要）
    assert "统计摘要" in block and "川剧" in block
    assert citations, "引用条目不能为空"


def test_pre_retrieve_survives_all_failures():
    class Boom:
        async def invoke(self, name, args):
            raise RuntimeError("tool down")

    block, citations = asyncio.run(
        retrieval.pre_retrieve(Boom(), "四川省非遗有多少个", 5, 0.5, "hybrid", "ALL"))
    assert block == "" and citations == []
