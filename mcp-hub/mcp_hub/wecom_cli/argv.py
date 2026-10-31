# -*- coding: utf-8 -*-
"""企微 CLI 的参数向量构造 —— **纯函数、零依赖**，可离线单测。

## 为什么单独抽出来

原先这些参数是在 `server.py` 里内联拼的，而「拼错一个 flag」的后果**不是本地异常**：
CLI 会返回一句 `error: unexpected argument 'true' found`，被 `_err()` 包成工具错误
交给模型 —— 模型于是对用户说「调用企业微信邮箱搜索工具时出现了参数错误」，然后放弃。
用户看到的是「这个助手不会用企微」，真实原因只是一个 flag 少写/多写。

2026-10-31 生产实测就是这么炸的：

    mail search ... --only-unread true        # ← 错
    error: unexpected argument 'true' found   # CLI 原话

`--only-unread` 在官方 CLI 里是**布尔开关（不带值）**，和 `--has-attachments`
`--only-subject` / `--has-star` 一样；帮助文本里那句「true-仅未读 false-都返回」
是文档的通用措辞，容易让人误以为要传值。

抽成纯函数后，`scripts/_check_wecom_cli_argv.py` 可以拿**真 CLI 的 `--help` 当事实源**，
逐个核对「flag 拼没拼错 / 该带值的带没带 / 布尔开关有没有多塞值」。
改这里的任何一行，那个哨兵都会先叫。

## 纪律

- 本模块**不许 import mcp / fastmcp / 任何网络库** —— 哨兵要在没有 hub 依赖时也能跑。
- 每个函数返回「`bin_path()` 之后的完整 argv」，即 `["mail", "search", ...]`。
- 时间格式由调用方给（`YYYY-MM-DD HH:MM:SS`），本模块不碰时钟，保证可测。
"""
from __future__ import annotations

# 官方 CLI 里「布尔开关」型 flag：**只写 flag 本身，后面绝不跟值**。
# 新增命令时如果用到新的布尔 flag，先登记在这里，再写进 argv 构造函数。
BOOLEAN_FLAGS: frozenset[str] = frozenset({
    "--only-unread",
    "--has-attachments",
    "--has-star",
    "--only-reminder",
    "--only-subject",
})


def kw_list(raw: str) -> list[str]:
    """把「张三,李四」拆成列表；中文逗号也认。"""
    return [x.strip() for x in (raw or "").replace("，", ",").split(",") if x.strip()]


def mail_search(begin: str, end: str, keywords: str = "", limit: int = 10,
                only_unread: bool = False) -> list[str]:
    """`wecom-cli mail search`。布尔开关 `--only-unread` **不带值**。"""
    args = ["mail", "search",
            "--begin-time", begin, "--end-time", end,
            "--limit", str(max(1, min(int(limit or 10), 30)))]
    kws = kw_list(keywords)
    if kws:
        args += ["--keywords", *kws]
    if only_unread:
        args.append("--only-unread")      # ★ 开关，别跟 "true"
    return args


def session_messages(chat_id: str, begin: str, end: str) -> list[str]:
    """`wecom-cli chat messages list`。三个参数都是必填且带值。"""
    return ["chat", "messages", "list",
            "--chat-id", chat_id,
            "--begin-time", begin, "--end-time", end]


def recent_sessions(begin: str, end: str) -> list[str]:
    """`wecom-cli chat groups list`。"""
    return ["chat", "groups", "list", "--begin-time", begin, "--end-time", end]


def contact_search(keywords: str) -> list[str]:
    """`wecom-cli contact users search`。`--keywords` 是**变参**，可跟多个词。"""
    return ["contact", "users", "search", "--keywords", *kw_list(keywords)]


def flag_violations(argv: list[str], takes_value: dict[str, bool]) -> list[str]:
    """按 `{flag: 是否带值}` 校验一条 argv，返回人类可读的问题列表。

    三件事都查：
      1. flag 不认识（拼错 / 版本里没有）；
      2. 该带值的没带（后面直接跟了下一个 flag 或到头了）；
      3. 布尔开关后面多塞了一个值（就是本次事故）。
    """
    problems: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("--"):
            i += 1
            continue
        if tok not in takes_value:
            problems.append(f"未知 flag {tok}")
            i += 1
            continue
        if takes_value[tok]:
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is None or nxt.startswith("--"):
                problems.append(f"{tok} 需要值，但后面是 {nxt!r}")
                i += 1
                continue
            i += 2
        else:
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is not None and not nxt.startswith("--"):
                problems.append(f"{tok} 是布尔开关，不该带值（发现 {nxt!r}）")
            i += 1
    return problems
