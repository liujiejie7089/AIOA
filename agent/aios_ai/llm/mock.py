"""本地 mock LLM（方案 P4 / D-4）：不打真实 API，但温度、召回参数真实影响输出。

设计：
  - 温度真实生效：用「种子化采样」——候选 token 按置信度排序，温度越低越倾向
    最高概率候选（确定性），温度越高越均匀采样。温度 0.1 与 0.9 的输出可被客观区分，
    不是摆设（这是验证「参数真实生效」的关键一环）。
  - 输入为「已执行工具的结果」，输出为把结构化结果转成自然语言摘要的文本，
    由调用方决定要不要把结果重新「喂」给生成器。
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass


@dataclass
class MockGeneration:
    content: str
    temperature: float


def _seeded_rng(seed_text: str) -> random.Random:
    """用文本哈希做种子，保证同输入同温度下结果可复现。"""
    h = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def summarize_tool_result(name: str, data: object, temperature: float = 0.3) -> str:
    """把工具结果转成自然语言摘要（mock「反思/整合」阶段）。

    温度的影响点：数值类结果（如统计数字）会按温度做扰动措辞——
    低温度用确定性的「精确值」，高温度用「约 / 大约 / 接近」等模糊措辞，
    从而让温度真实可观测。
    """
    rng = _seeded_rng(f"{name}:{str(data)[:200]}")

    if name == "sql_query":
        return _summarize_sql(data, temperature, rng)
    if name == "search_kb_documents":
        rows = data if isinstance(data, list) else []
        if not rows:
            return "知识库中没有找到相关资料。"
        lines = [f"在知识库中找到 {len(rows)} 份相关资料："]
        for r in rows[:5]:
            score = r.get("score")
            score_txt = "" if score is None else f"（相关度 {round(float(score), 3)}）"
            lines.append(f"· 《{r.get('docName')}》{score_txt}")
        return "\n".join(lines)
    if name == "list_my_approvals" or name == "list_todo_approvals":
        rows = data if isinstance(data, list) else []
        label = "待你审批" if name == "list_todo_approvals" else "你提交的审批"
        if not rows:
            return f"当前{label}单：暂无。"
        lines = [f"当前{label}单共 {len(rows)} 条："]
        for r in rows:
            lines.append(f"· #{r.get('id')} {r.get('title')}（{r.get('status')}）")
        return "\n".join(lines)
    if name == "get_my_quota":
        if isinstance(data, dict):
            quota, used, left = data.get("quota"), data.get("used"), data.get("left")
            return _fuzzy(f"当前词元额度：总量 {quota}，已用 {used}，剩余 {left}", temperature, rng)
    return f"工具返回：{data}"


def _summarize_sql(data, temperature: float, rng: random.Random) -> str:
    if not isinstance(data, dict):
        return f"查询结果：{data}"
    rows = data.get("rows") or []
    row_count = data.get("rowCount") or len(rows)
    columns = data.get("columns") or []
    if row_count == 0:
        return "查询结果为空，没有符合条件的数据。"

    # 单行单列：标量结果
    if row_count == 1 and len(columns) == 1:
        key = columns[0]
        val = rows[0].get(key)
        return _fuzzy(f"查询结果：{key} = {val}", temperature, rng)

    lines = [f"查询共返回 {row_count} 行："]
    for r in rows[:10]:
        cells = "，".join(f"{c}={r.get(c)}" for c in columns[:6])
        lines.append(f"· {cells}")
    if row_count > 10:
        lines.append(f"… 仅展示前 10 行，共 {row_count} 行")
    return "\n".join(lines)


def _fuzzy(text: str, temperature: float, rng: random.Random) -> str:
    """按温度对确定性表述做模糊化，让温度可观测。"""
    if temperature < 0.3:
        return text
    if temperature < 0.7:
        if rng.random() < 0.5:
            return text.replace("：", "约为：", 1)
        return text
    # 高温：措辞更模糊、更口语
    prefixes = ["据当前数据来看，", "大致情况是：", "粗略统计，", "从现有数据观察，"]
    return rng.choice(prefixes) + text.replace("=", "≈")


def sample_temperature_demo(seed_text: str, temperature: float, candidates: list[str]) -> str:
    """温度采样演示：从候选里按温度选一个。低温度总选最高优先项，高温趋均匀。

    这是温度「真实生效」的直接可验证单元：同 seed、不同 temperature 选出的结果分布不同。
    """
    rng = _seeded_rng(seed_text)
    if not candidates:
        return ""
    if temperature <= 0.2:
        return candidates[0]
    # softmax 权重随温度升高而摊平
    weights = [math.exp(-i / max(temperature, 0.05)) for i in range(len(candidates))]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return candidates[i]
    return candidates[-1]
