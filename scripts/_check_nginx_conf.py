# -*- coding: utf-8 -*-
"""边缘 Nginx 配置结构校验（本机无 nginx / docker，用确定性解析替代人工目测）。

为什么需要它：`deploy/nginx/nginx.conf` 现在是 80/81 双 server 结构，且通过
`include /etc/nginx/api-proxy.conf` 复用 API 反代块。**一个括号打错或 include 路径
对不上，整个站点起不来**，而本机既没有 nginx 也没有 docker，跑不了 `nginx -t`。
本脚本做三件事：

  1. 按 nginx 语法切词并建树（正确处理注释、引号、map 的裸键值对）；
  2. 把 `include` 当**内联展开**（与 nginx 语义一致），再校验指令是否出现在合法上下文；
  3. 与 `docker-compose.yml` 交叉核对：listen 端口 ⇄ published ports、挂载的 include 文件是否都在。

用法：python scripts/_check_nginx_conf.py
退出码 0 = 全部通过；非 0 = 有 FAIL（会逐条打印行号）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NGINX_DIR = ROOT / "deploy" / "nginx"
COMPOSE = ROOT / "deploy" / "docker-compose.yml"

# 容器内路径 -> 仓库内真实文件。镜像自带、仓库里没有的写 None（跳过存在性检查）。
INCLUDE_MAP = {
    "/etc/nginx/mime.types": None,
    "/etc/nginx/api-proxy.conf": NGINX_DIR / "api-proxy.conf",
}

# 每个上下文允许出现的指令。未列出的指令一律 FAIL（宁严勿松：这条最容易真出错）。
ALLOWED = {
    "main": {"user", "worker_processes", "events", "http", "include", "error_log", "pid"},
    "events": {"worker_connections"},
    "http": {
        "include", "default_type", "sendfile", "keepalive_timeout", "client_max_body_size",
        "map", "upstream", "server", "log_format", "access_log", "gzip", "types",
    },
    "server": {
        "listen", "server_name", "root", "index", "location", "include",
        "client_max_body_size", "return", "charset",
    },
    "location": {
        "proxy_pass", "proxy_set_header", "proxy_http_version", "proxy_buffering",
        "proxy_cache", "proxy_read_timeout", "proxy_send_timeout", "add_header",
        "try_files", "alias", "root", "index", "include", "proxy_redirect",
        "proxy_connect_timeout", "client_max_body_size", "expires",
    },
    "upstream": {"server", "keepalive"},
    # map 块内是裸键值对（`default upgrade;` / `'' close;`），不是指令名 —— 只登记上下文，
    # 内容由 FREE_CONTEXT 短路跳过校验。
    "map": set(),
}
# map 块内是裸键值对（`default upgrade;` / `'' close;`），不做指令名校验。
FREE_CONTEXT = {"map"}

TOKEN_RE = re.compile(
    r'(?P<ws>\s+)'
    r'|(?P<comment>\#[^\n]*)'
    r'|(?P<string>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'
    r'|(?P<brace>[{};])'
    r'|(?P<word>[^\s{};]+)'
)


class Node:
    __slots__ = ("name", "args", "children", "line", "ctx")

    def __init__(self, name, args, line, ctx):
        self.name = name
        self.args = args
        self.children = []
        self.line = line
        self.ctx = ctx


def tokenize(text):
    """产出 (kind, value, line) —— kind ∈ {string, brace, word}。空白与注释只用于计行。"""
    line = 1
    pos = 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:  # 理论上不会发生；兜底也要正确计行
            if text[pos] == "\n":
                line += 1
            pos += 1
            continue
        kind = m.lastgroup
        val = m.group()
        if kind not in ("ws", "comment"):
            yield kind, val, line
        line += val.count("\n")
        pos = m.end()


def parse_tree(tokens):
    """建树。返回 (nodes, errors)。"""
    errors = []
    root = Node("__root__", [], 0, "main")
    stack = [root]
    pending = []  # 当前语句已读到的 word/string

    for kind, val, line in tokens:
        if kind in ("word", "string"):
            pending.append((val, line))
        elif val == ";":
            if pending:
                name, l = pending[0]
                args = [v for v, _ in pending[1:]]
                stack[-1].children.append(Node(name, args, l, stack[-1].ctx))
                pending = []
        elif val == "{":
            if not pending:
                errors.append("第 %d 行：出现孤立的 '{'" % line)
                continue
            name, l = pending[0]
            args = [v for v, _ in pending[1:]]
            node = Node(name, args, l, stack[-1].ctx)
            stack[-1].children.append(node)
            stack.append(node)
            pending = []
        elif val == "}":
            if pending:
                errors.append("第 %d 行：'}' 前有未以 ';' 结束的语句 '%s'" % (line, pending[0][0]))
                pending = []
            if len(stack) == 1:
                errors.append("第 %d 行：多余的 '}'" % line)
            else:
                stack.pop()
    if pending:
        errors.append("文件末尾有未以 ';' 结束的语句 '%s'（第 %d 行）" % (pending[0][0], pending[0][1]))
    if len(stack) != 1:
        errors.append("括号不配对：仍有 %d 个块未闭合（%s）"
                      % (len(stack) - 1, ", ".join(n.name for n in stack[1:])))
    return root, errors


def expand(node, errors, seen_files):
    """把 include 内联展开到当前位置。"""
    out = []
    for child in node.children:
        if child.name == "include" and child.args:
            target = child.args[0]
            real = INCLUDE_MAP.get(target, "MISSING")
            if real == "MISSING":
                errors.append("第 %d 行：include '%s' 不在白名单内（新增挂载点请同步 INCLUDE_MAP）"
                              % (child.line, target))
                continue
            if real is None:
                continue  # 镜像自带，跳过
            if not Path(real).is_file():
                errors.append("第 %d 行：include '%s' 期望来自 %s，但该文件不存在"
                              % (child.line, target, real))
                continue
            key = str(real)
            if key in seen_files:
                errors.append("第 %d 行：include 循环引用 %s" % (child.line, target))
                continue
            sub_tokens = list(tokenize(Path(real).read_text(encoding="utf-8")))
            sub_root, sub_err = parse_tree(sub_tokens)
            errors.extend("api-proxy.conf → " + e for e in sub_err)
            out.extend(expand(sub_root, errors, seen_files | {key}))
        else:
            child.children = expand(child, errors, seen_files)
            out.append(child)
    return out


def check_contexts(nodes, ctx, errors, path=""):
    for n in nodes:
        where = "%s%s (第 %d 行)" % (path, n.name, n.line)
        if ctx in FREE_CONTEXT:
            continue
        allowed = ALLOWED.get(ctx)
        if allowed is None:
            errors.append("%s：未知上下文 '%s'" % (where, ctx))
            continue
        if n.name not in allowed:
            errors.append("%s：指令 '%s' 不允许出现在 %s 上下文（允许：%s）"
                          % (where, n.name, ctx, ", ".join(sorted(allowed))))
            continue
        child_ctx = n.name if n.name in ALLOWED else ctx
        check_contexts(n.children, child_ctx, errors, where + " > ")
    return errors


def check(nodes, errors, warnings):
    http = [n for n in nodes if n.name == "http"]
    if len(http) != 1:
        errors.append("顶层必须且只能有一个 http 块，实际 %d 个" % len(http))
        return
    http = http[0]

    upstreams = {n.args[0] for n in http.children if n.name == "upstream" and n.args}
    servers = [n for n in http.children if n.name == "server"]
    if not servers:
        errors.append("http 块内没有任何 server")
        return

    listens = []
    for srv in servers:
        got = [a for n in srv.children if n.name == "listen" for a in n.args]
        if len(got) != 1:
            errors.append("第 %d 行的 server 应恰好有一个 listen，实际 %d 个" % (srv.line, len(got)))
        listens.extend(int(a.split()[0]) for a in got)

        locs = [n for n in srv.children if n.name == "location"]
        if not locs:
            warnings.append("第 %d 行的 server 没有任何 location" % srv.line)

        # proxy_pass 引用的 upstream 必须已定义
        for n in _walk(srv):
            if n.name == "proxy_pass" and n.args:
                m = re.match(r"https?://([A-Za-z0-9_.-]+)", n.args[0].strip('"').strip("'"))
                if m and m.group(1) not in upstreams:
                    errors.append("第 %d 行：proxy_pass 引用了未定义的 upstream '%s'"
                                  % (n.line, m.group(1)))

    if len(listens) != len(set(listens)):
        dup = sorted({p for p in listens if listens.count(p) > 1})
        errors.append("listen 端口重复：%s（同一端口只能由一个 server 监听）" % dup)
    return listens


def _walk(node):
    for c in node.children:
        yield c
        yield from _walk(c)


def check_compose(listens, errors, warnings):
    """listen 端口 ⇄ compose published ports；include 是否真的被挂进容器。"""
    if not COMPOSE.is_file():
        warnings.append("找不到 %s，跳过交叉核对" % COMPOSE)
        return
    text = COMPOSE.read_text(encoding="utf-8")

    m = re.search(r"^  nginx:\n(.*?)(?=^  \w|\Z)", text, re.S | re.M)
    if not m:
        errors.append("docker-compose.yml 里找不到 nginx 服务")
        return
    block = m.group(1)
    published = {int(a) for a in re.findall(r'-\s*"(\d+):\d+"', block)}
    missing = sorted(set(listens) - published)
    if missing:
        errors.append("nginx.conf 监听了 %s，但 compose 的 nginx.ports 未发布 %s（容器外访问不到）"
                      % (sorted(set(listens)), missing))

    for target, real in INCLUDE_MAP.items():
        if real is None:
            continue
        rel = real.relative_to(ROOT / "deploy").as_posix()
        if "nginx/%s" % Path(rel).name not in block:
            errors.append("nginx.conf include 了 '%s'，但 compose 未把 %s 挂进容器"
                          % (target, rel))


def main():
    errors, warnings = [], []
    conf = NGINX_DIR / "nginx.conf"
    if not conf.is_file():
        print("FAIL 找不到 %s" % conf)
        return 1

    root, errs = parse_tree(tokenize(conf.read_text(encoding="utf-8")))
    errors.extend("nginx.conf → " + e for e in errs)
    nodes = expand(root, errors, {str(conf)})
    check_contexts(nodes, "main", errors)
    listens = check(nodes, errors, warnings)
    if listens is not None:
        check_compose(listens, errors, warnings)

    print("=== 边缘 Nginx 配置结构校验 ===")
    print("nginx.conf             : %s" % conf)
    print("include 锚点           : %s" % ", ".join(INCLUDE_MAP))
    print("解析出的 server.listen : %s" % (sorted(set(listens)) if listens else "(未解析到)"))
    for w in warnings:
        print("  WARN  %s" % w)
    for e in errors:
        print("  FAIL  %s" % e)
    print("结果：%s（%d 项失败 / %d 项警告）" % ("通过" if not errors else "未通过", len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
