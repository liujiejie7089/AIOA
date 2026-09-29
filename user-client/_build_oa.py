#!/usr/bin/env python3
"""把 OA 形态一次性拼入 user-client/index.html（零构建单文件 H5）。

拼入内容
  ① 23 个缺失的图标 symbol（demo 有、index.html 没有）
  ② OA 样式层，三段拼接：demo CSS 的作用域化副本（段1）+ OA 外壳/对话坞样式（段2）
     + 视觉精修层（段3，_oa_polish.css）
  ③ .oa 容器标记（5 个主视图 + 数字员工/专家/定时/技能/最近/审批详情
     + 额度与账单/操作记录/权限申请/投诉与建议 4 个账户内页）
  ④ OA 应用层脚本
  ⑤ 数字人位图内联（生产镜像只 COPY index.html，外链必然 404）

注：经典「我的」里的「切换布局」按钮与经典侧的口径纯函数（billTokens / logIsOk /
quotaNumbers / fbRouteLine …）都在基线 _backup_index_pre_oa.html 内，本脚本不再注入它们 ——
它们属于经典形态自身，改它们要改基线，否则下次重建会静默丢掉。

同时剥离 present_files 预览注入的 data-page-node-id（800 处），
它们只服务预览面板，不该进仓库。

锚点全部做唯一性断言：拼错位置比不拼更危险。

【重建（非幂等，必须先还原基线）】
    cp _backup_index_pre_oa.html index.html && python _build_oa.py
  ⚠️ 若在 OA 版 index.html 上**直接**改过经典部分（page-* 等），先还原快照会静默丢掉那些改动。
     此时应改为「把改动同步进 _backup_index_pre_oa.html 再重建」，不要直接跑上面那行。
     前置闸门 preflight() 会在基线已含 OA 层时中止，避免重复注入。
"""
import base64
import os
import re
import sys

HTML = 'index.html'
CSS_SCOPED = '_oa_css.txt'
CSS_EXTRA = '_oa_extra.css'
CSS_POLISH = '_oa_polish.css'
MARKUP = '_oa_markup.html'
APPJS = '_oa_app.js'
ROBOT = 'assets/robot.webp'

# demo 图标精灵中 index.html 缺失的 23 个（同名的不重复添加 —— index.html 的先出现即生效）
ADD_SYMBOLS = [
    'i-task', 'i-folder', 'i-cal', 'i-stamp', 'i-book', 'i-people', 'i-note', 'i-qr',
    'i-swap', 'i-info', 'i-grid', 'i-help', 'i-logout', 'i-menu', 'i-back', 'i-search',
    'i-dots', 'i-mic', 'i-pin', 'i-bulb', 'i-target', 'i-square-plus', 'i-puzzle',
]


def die(msg):
    print('[FAIL] ' + msg, file=sys.stderr)
    sys.exit(1)


def once(text, anchor, what):
    n = text.count(anchor)
    if n != 1:
        die('%s 锚点出现 %d 次（要求恰好 1 次）：%r' % (what, n, anchor[:70]))
    return True


def preflight(src):
    """基线体检：已含 OA 层的文件不能当基线（否则重复注入）。
    给出可直接照抄的修复命令，而不是让人对着 once() 的『锚点出现 2 次』猜。"""
    marks = {
        'OA 容器': 'id="oaRoot"',
        'OA 应用层': 'window.oaBoot = oaBoot',
        'OA 样式层': 'OA 形态样式层（新版 · 协同工作台）',
    }
    hit = [k for k, v in marks.items() if v in src]
    if hit:
        die('基线已含 OA 层（%s）—— 拒绝重复注入。\n'
            '      正确做法：先还原基线段再重建\n'
            '        cp _backup_index_pre_oa.html index.html\n'
            '        python _build_oa.py\n'
            '      若你刚在 OA 版 index.html 里改过经典部分，请先把改动同步进\n'
            '      _backup_index_pre_oa.html（那是重建的唯一基线段），否则改动会被覆盖。'
            % '、'.join(hit))
    if src.count('</script>') != 1:
        die('基线预期恰好 1 个 </script>，实际 %d 个' % src.count('</script>'))


def main():
    src = open(HTML, encoding='utf-8').read()
    preflight(src)
    original_len = len(src)

    # ---- 0. 剥离预览注入属性 ----
    src, n_inj = re.subn(r'\s+data-page-node-id="[^"]*"', '', src)
    print('剥离 data-page-node-id：%d 处' % n_inj)

    # ---- 1. 图标 sprite ----
    demo = open('_oa_clean.html', encoding='utf-8').read()
    symbols = re.findall(r'(<symbol id="([^"]+)" viewBox="0 0 24 24">.*?</symbol>)', demo, re.S)
    by_name = {name: full for full, name in symbols}
    have = set(re.findall(r'<symbol id="([^"]+)"', src))
    add = []
    for k in ADD_SYMBOLS:
        if k in have:
            continue
        if k not in by_name:
            die('图标 %s 在 demo 精灵中不存在' % k)
        add.append(by_name[k])
    extra_icons = '\n'.join('    ' + s for s in add)
    once(src, '</defs>', 'sprite </defs>')
    src = src.replace('</defs>', extra_icons + '\n  </defs>', 1)
    print('新增图标 symbol：%d 个（原有 %d 个同名图标保持优先）' % (len(add), len(set(ADD_SYMBOLS) & have)))

    # ---- 2. OA 样式层 ----
    scoped = open(CSS_SCOPED, encoding='utf-8').read()
    extra = open(CSS_EXTRA, encoding='utf-8').read()
    polish = open(CSS_POLISH, encoding='utf-8').read()
    for bad in ('data-page-node-id',):
        if bad in scoped or bad in extra or bad in polish:
            die('样式层含 %r' % bad)
    css_block = (
        '\n<!-- ============================================================================\n'
        '     OA 形态样式层（新版 · 协同工作台）\n'
        '     第 1 段由 user-client/oa-demo.html 的样式作用域化而来：demo 与 index.html\n'
        '     有 29 个同名类（card / tab / tabbar / seg / on / ic …），故每条规则统一前缀\n'
        '     `.oa `，外壳级规则（:root / * / body / .phone / .toast）整体剔除，\n'
        '     避免两套样式互相污染。第 2 段为 OA 外壳与首页对话坞（demo 里没有原地对话）。\n'
        '     第 3 段为视觉精修层：阴影五级梯子 / 对比度 / 命中区 / 动效；只写覆盖，\n'
        '     不改前两段，故「本次精修动了什么」可只看 _oa_polish.css 一个文件的 diff。\n'
        '     ============================================================================ -->\n'
        '<style>\n/* ===== 段 1：demo 样式的作用域化移植 ===== */\n'
        + scoped +
        '\n/* ===== 段 2：外壳显隐 + 对话坞 + 锚点气泡 + 部门联系方式 ===== */\n'
        + extra +
        '\n/* ===== 段 3：视觉精修（阴影梯级 / 对比度 / 命中区 / 动效） ===== */\n'
        + polish + '\n</style>\n')
    once(src, '</style>', '样式 </style>')
    src = src.replace('</style>', '</style>' + css_block, 1)
    print('注入 OA 样式层：%d 字节（段1 %d + 段2 %d + 段3 %d）'
          % (len(css_block), len(scoped), len(extra), len(polish)))

    # ---- 4. OA 标记 ----
    markup = open(MARKUP, encoding='utf-8').read()
    robot_b64 = base64.b64encode(open(ROBOT, 'rb').read()).decode('ascii')
    if '__ROBOT_B64__' not in markup:
        die('标记层缺少 __ROBOT_B64__ 占位符')
    markup = markup.replace('__ROBOT_B64__', 'data:image/webp;base64,' + robot_b64)
    anchor = '  <div class="toast" id="toast">'
    once(src, anchor, 'toast 起始')
    src = src.replace(anchor, markup.rstrip() + '\n\n' + anchor, 1)
    print('注入 OA 标记：%d 字节（含数字人位图 %d KB base64）'
          % (len(markup), len(robot_b64) // 1024))

    # ---- 5. OA 应用层 ----
    appjs = open(APPJS, encoding='utf-8').read()
    once(src, '</body>', 'body 结束')
    if src.count('</script>') != 1:
        die('预期恰好 1 个既有 </script>，实际 %d 个' % src.count('</script>'))
    src = src.replace('</body>',
                      '<script>\n' + appjs + '</script>\n</body>', 1)
    print('注入 OA 应用层：%d 字节' % len(appjs))

    open(HTML, 'w', encoding='utf-8', newline='\n').write(src)
    print('\n完成：%d → %d 字节（+%d KB）' % (original_len, len(src), (len(src) - original_len) // 1024))


if __name__ == '__main__':
    main()
