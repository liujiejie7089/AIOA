#!/usr/bin/env python3
"""把 oa-demo.html 的样式层机械移植为 index.html 可用的作用域化 CSS。

为什么需要它：oa-demo 与 index.html 有 29 个同名类（card / tab / tabbar / seg / on / ic …），
直接粘贴会让两套样式互相污染。本脚本把 demo 的每条规则前缀 `.oa `，
并把外壳级规则（:root / * / html,body / body / .phone / .toast）剔除 —— 外壳由 index.html 自己负责。

输出：_oa_css.txt（供人工核对后再拼接）
"""
import re
import sys

SRC = 'oa-demo.html'
OUT = '_oa_css.txt'

# 这些顶层规则属于 demo 的手机外壳，index.html 已有自己的外壳，一律丢弃
DROP_EXACT = {':root', '*', 'html', 'body', 'html,body', '.toast'}
DROP_PREFIX = ('.phone',)


def split_blocks(css):
    """把 CSS 拆成 [(prelude, body, kind)]，kind ∈ {rule, at}。仅处理一层嵌套。"""
    blocks = []
    i, n = 0, len(css)
    while i < n:
        j = css.find('{', i)
        if j == -1:
            break
        prelude = css[i:j].strip()
        # 找到配对的 `}`
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        kind = 'at' if prelude.startswith('@') else 'rule'
        blocks.append((prelude, body, kind))
        i = k
    return blocks


def scope_selector(sel):
    """给单条选择器加 `.oa ` 前缀；返回 None 表示丢弃。"""
    sel = re.sub(r'\s+', ' ', sel).strip()
    if not sel:
        return None
    if sel in DROP_EXACT:
        return None
    # 外壳状态类：从 .phone 改挂到 .oa（抽屉/弹层的开合状态将加在 .oa 上）
    m = re.match(r'^\.phone\.(drawer-open|sheet-open)\b(.*)$', sel)
    if m:
        rest = m.group(2).strip()
        return '.oa.%s%s' % (m.group(1), (' ' + rest) if rest else '')
    if sel.startswith(DROP_PREFIX):
        return None
    return '.oa ' + sel


def transform(css):
    out = []
    for prelude, body, kind in split_blocks(css):
        if kind == 'at':
            head = re.match(r'@(\w[\w-]*)\s*(.*)$', prelude)
            name, arg = head.group(1), head.group(2).strip()

            if name == 'keyframes':
                kf = 'oa-rise' if arg == 'rise' else arg   # rise 可能与外部重名
                out.append('@keyframes %s{%s}' % (kf, body))
                continue

            inner = transform(body)                        # 递归：媒体查询内同样加前缀
            if not inner.strip():
                continue                                   # 空媒体块（如仅含 .phone 的宽屏规则）整块丢弃
            out.append('@%s %s{%s}' % (name, arg, inner))
            continue

        sels = []
        for s in prelude.split(','):
            got = scope_selector(s)
            if got:
                sels.append(got)
        if not sels:
            continue
        # 关键帧引用改名
        body = re.sub(r'animation-name:\s*rise\b', 'animation-name:oa-rise', body)
        body = re.sub(r'(animation:[^;{}]*?)\brise\b', r'\g<1>oa-rise', body)
        out.append('%s{%s}' % (','.join(sels), body))
    return '\n'.join(out) + '\n'


def main():
    src = open(SRC, encoding='utf-8').read()
    css = re.search(r'<style>(.*?)</style>', src, re.S).group(1)
    # 注释必须先剥离：`/* … */ :root` 这类前置注释会让序言匹配不上丢弃表
    # （首版就是栽在这里，把 demo 的 :root 与 .phone 一起搬了进来）。
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    scoped = transform(css)

    # 补三条 demo 依赖外壳提供、index.html 需要自备的规则
    scoped += """
/* ---- 移植补丁：demo 的 .tabbar 靠 `.tabbar.on` 显示，且绝对定位由外壳负责；
       这里改为 .oa 内的常规 flex 子元素，并压过 index.html 的 `.tabbar{position:absolute}` ---- */
.oa .tabbar{position:static;display:flex;border-top:1px solid var(--border)}
.oa .appbar{display:flex}
/* index.html 的 .tab 与 demo 的 .tab 同名：OA 内的以本段为准 */
.oa .tab{text-decoration:none}
"""
    open(OUT, 'w', encoding='utf-8').write(scoped)
    print('写出 %s：%d 条规则，%d 字节' % (OUT, scoped.count('{'), len(scoped)))
    for bad in ('data-page-node-id', '.phone', ':root'):
        if bad in scoped:
            print('  [警告] 输出仍含 %r' % bad, file=sys.stderr)


if __name__ == '__main__':
    main()
