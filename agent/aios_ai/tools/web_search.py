# -*- coding: utf-8 -*-
"""联网检索（内置工具，不需要任何密钥，也不依赖连接器授权）。

为什么要它
----------
2026-10-30 实测：用户说「没有，在网上找」，澄清卡片选完「就业政策」后，数字人回
「抱歉，我未能找到关于『就业政策』的邮件……」—— 因为**系统里根本没有联网工具**：
模型手里只有 QQ 邮箱与企微的 MCP 工具 + 知识库检索，于是把「找不到内部资料」当成
「找不到」，还用「帮你起草一封邮件」来收尾。提示词再怎么写也变不出一个不存在的工具，
所以这里补的是**能力**，不是措辞。

设计取舍
--------
1. **不进 mcp-hub、不进连接器体系**：联网检索是平台自带能力，不该需要用户去「连接」一次，
   也不该受 `connector_connection` 闸门影响（连接器是「别人的账号」，搜索不是）。
2. **免密钥**：走 Bing 结果页（`b_algo` 块）解析，不引入需要申请 key 的服务商 ——
   密钥缺失会让这条链在生产上悄悄失效，而它恰恰是最常被用到的一条。
   两个 host（`www.bing.com` / `cn.bing.com`）互为兜底，都失败才算失败。
3. **两个工具而不是一个**：`web_search` 只回标题/链接/摘要（快），`web_fetch` 再读正文（准）。
   合成一个「搜索并抓前三条」的工具会让每次调用都变慢，且模型无法按需取舍。
4. **失败必须可读、绝不伪装成功**：网络不通 / 反爬拦截 / 页面没有结果块，一律
   `ok=False` + 中文原因，由模型如实告知用户并按提示词走兜底；**绝不返回空列表冒充
   「没有搜到」**（这两件事对用户的意义完全不同）。
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from urllib.parse import quote_plus, urlparse

import httpx

logger = logging.getLogger("aios.agent.web_search")

WEB_SEARCH_TOOL_NAME = "web_search"
WEB_FETCH_TOOL_NAME = "web_fetch"
WEB_TOOL_NAMES = (WEB_SEARCH_TOOL_NAME, WEB_FETCH_TOOL_NAME)

# 浏览器 UA：Bing 对默认 httpx UA 会返回一个没有结果块的精简页（实测 2026-10-30）
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}

_HOSTS = ("https://www.bing.com/search", "https://cn.bing.com/search")

# 单个结果块：<li class="b_algo"> 后到下一个 b_algo 之间（Bing 的 li 内会再嵌 ul/li，
# 用 `</li>` 收尾会截断，故按「下一个块起点」切）
_H2A = re.compile(r"<h2[^>]*>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def is_web_tool(name: str) -> bool:
    return name in WEB_TOOL_NAMES


# --------------------------------------------------------------------------- specs

WEB_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": WEB_SEARCH_TOOL_NAME,
        "description": (
            "联网搜索公开网页（真实发起 HTTP 请求，非模型记忆）。"
            "当用户要求「在网上查/搜/找」「查最新的」「外部资料/政策/新闻/行情」时**必须**先调用它；"
            "知识库与邮箱里没有的内容也用它。返回标题、链接与摘要。"
            "需要正文细节时，对返回的链接再调用 web_fetch。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索词，用中文自然语言即可"},
                "count": {"type": "integer", "description": "返回条数，1-10，默认 6"},
            },
            "required": ["query"],
        },
    },
}

WEB_FETCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": WEB_FETCH_TOOL_NAME,
        "description": (
            "抓取指定网页并抽取正文纯文本（用于读取 web_search 返回链接的详细内容）。"
            "只能抓 http/https 公网地址。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页地址"},
                "max_chars": {"type": "integer", "description": "正文上限字符数，默认 3000"},
            },
            "required": ["url"],
        },
    },
}


# --------------------------------------------------------------------------- 内部

def _clean(raw: str) -> str:
    text = _TAG.sub("", _html.unescape(raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def _parse_bing(page: str, limit: int) -> list[dict]:
    """从 Bing 结果页里抽 [{title,url,snippet}]。抽不到就返回 []（由调用方判失败）。"""
    out: list[dict] = []
    for chunk in page.split('<li class="b_algo"')[1:]:
        m = _H2A.search(chunk)
        if not m:
            continue
        url = _html.unescape(m.group(1)).strip()
        title = _clean(m.group(2))
        # 跳过 Bing 自己的站内导航链接
        if not url.startswith("http") or not title:
            continue
        p = _P.search(chunk)
        snippet = _clean(p.group(1)) if p else ""
        out.append({"title": title[:200], "url": url[:600], "snippet": snippet[:500]})
        if len(out) >= limit:
            break
    return out


async def _get(url: str, timeout: float) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 trust_env=False, headers=_HEADERS) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return resp.text


async def run_search(query: str, count: int = 6) -> dict:
    """联网搜索。返回 {...} 或抛 RuntimeError（由 invoke 包装成 ok=False）。"""
    q = (query or "").strip()
    if not q:
        raise RuntimeError("搜索词为空")
    limit = max(1, min(int(count or 6), 10))
    last = ""
    for host in _HOSTS:
        url = (f"{host}?q={quote_plus(q)}&count={limit}"
               f"&setlang=zh-CN&mkt=zh-CN&form=QBLH")
        try:
            page = await _get(url, timeout=8.0)
        except Exception as exc:                      # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            continue
        results = _parse_bing(page, limit)
        if results:
            return {"query": q, "engine": urlparse(host).netloc, "count": len(results),
                    "results": results}
        last = "结果页里没有可解析的条目（可能被反爬拦截）"
    raise RuntimeError(last or "搜索失败")


async def run_fetch(url: str, max_chars: int = 3000) -> dict:
    """抓网页正文纯文本。"""
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        raise RuntimeError("只支持 http/https 地址")
    cap = max(300, min(int(max_chars or 3000), 8000))
    started = time.monotonic()
    page = await _get(u, timeout=10.0)
    text = _SCRIPT_STYLE.sub(" ", page)
    text = re.sub(r"(?is)<head[^>]*>.*?</head>", " ", text)
    text = _clean(text)
    if not text:
        raise RuntimeError("页面没有可抽取的文本（可能需要登录或为纯前端渲染）")
    return {"url": u, "chars": min(len(text), cap), "text": text[:cap],
            "truncated": len(text) > cap,
            "elapsedMs": int((time.monotonic() - started) * 1000)}


async def invoke(name: str, arguments: dict) -> tuple[bool, object, str | None]:
    """统一入口（供 ToolClient.invoke 调用）：(ok, data, error)，永不抛。"""
    args = arguments or {}
    try:
        if name == WEB_SEARCH_TOOL_NAME:
            data = await run_search(str(args.get("query") or ""), args.get("count") or 6)
            return True, data, None
        if name == WEB_FETCH_TOOL_NAME:
            data = await run_fetch(str(args.get("url") or ""), args.get("max_chars") or 3000)
            return True, data, None
        return False, None, f"未知的联网工具：{name}"
    except RuntimeError as exc:
        # 这类失败**必须**原样告诉模型：用户要知道「没联网成功」，而不是「网上没有」
        logger.warning("web tool %s failed: %s", name, exc)
        return False, None, f"联网检索失败：{exc}"
    except Exception as exc:                          # noqa: BLE001
        logger.warning("web tool %s crashed: %s", name, exc)
        return False, None, f"联网检索失败：{type(exc).__name__}: {exc}"
