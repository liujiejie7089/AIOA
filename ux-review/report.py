# -*- coding: utf-8 -*-
"""生成《用户体验走查报告》自包含 HTML（截图 base64 内嵌）。"""
import base64, os, html

OUT = os.path.dirname(os.path.abspath(__file__))
IMG = {}
for n in ("zh-04-agent-workers", "ad-04-agent-workers", "zh-02-todo-pending",
          "ad-02-todo-pending", "zh-08-chat-answer", "zh-06-agent-experts",
          "zh-03-todo-mine", "zh-11-me", "zh-05-agent-cards", "ad-07-chat-open"):
    p = os.path.join(OUT, n + ".png")
    if os.path.exists(p):
        with open(p, "rb") as f:
            IMG[n] = "data:image/png;base64," + base64.b64encode(f.read()).decode()


def fig(name, cap):
    if name not in IMG:
        return ""
    return ('<figure class="fig"><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>'
            % (IMG[name], html.escape(cap), html.escape(cap)))


# (severity, id, area, title, symptom, evidence, impact, advice, figure)
F = [
    ("P0", "D-1", "数字员工", "「最近产出」把「索要材料的元回答」当成产出展示",
     "数字员工卡片与待办里的「最近产出/产出」出现了这样一段话：<code>[09-11 13:57] 请把需要重新汇总的工作内容发给我，例如：原始材料、会议纪要、聊天记录…</code>。<br><b>查库核对后的准确口径</b>：这是模型对该员工任务内容（<code>task_prompt='重新汇总这项工作'</code>）的<b>真实回答</b>——因为任务过于笼统，模型只能反问要材料。问题不在于「显示了模板」，而在于<b>UI 无差别地把任何一次运行结果都标成「产出 / 已送达」</b>，把一个「等待输入」的中间态当成了交付物。",
     "「数字员工」列表卡片（两角色）、待办-待我处理、待办-数字员工已代办 三处均出现；DB 对照 id=1 政策快讯员。",
     "用户会把它当成本次产出，实际是「等你补充材料」的中间态；直接拉低对数字员工能力的信任，也让「全程留痕」的承诺显得不实。",
     "双管齐下：① <b>数据侧</b>给定时员工补一条可执行的任务内容（如「汇总近 7 天行业政策，按 名称/主体/要点/影响/建议 五段输出，不要询问用户补充材料」）；② <b>展示侧</b>区分「有产出 / 尚未产出」两态，并把待办徽标由「已送达」改为「已执行」，不再把反问当交付。",
     "zh-04-agent-workers"),
    ("P0", "D-2", "数字员工", "触发式（事件驱动）员工被误判为「待配置 · 缺少执行时刻」",
     "「请假助手」的运行计划是 <code>触发式（有申请即审）</code>，却被打上黄色「待配置」徽标并提示<code>缺少执行时刻，尚未开始定时运行</code>；普通成员版本还让 TA「联系租户管理员」——而普通成员根本没有该权限。",
     "数字员工列表：请假助手卡片（普通成员/管理员两种文案）。",
     "事件驱动型员工永远呈现为「未配置完成」的异常态；且对无权处理的角色给出死路指引，制造无谓的求助与挫败。",
     "「待配置」判定按调度类型分叉：仅 <code>CRON</code> 型校验执行时刻；<code>EVENT</code> 型正常态显示「触发式 · 有申请即审」，不带任何告警；文案按角色分叉（成员侧不出现「请管理员配置」类指引）。",
     "ad-04-agent-workers"),
    ("P0", "A-1", "审批", "审批「通过 / 驳回」用浏览器原生 prompt 输入意见",
     "代码 <code>decideTodo()</code> 里用 <code>prompt('审批意见（可留空）：','同意')</code> 收集意见；同类原生弹窗还有 <code>confirm</code>（删除资料）、<code>prompt</code>（检索关键词/资料名称）、<code>alert</code>（检索结果），共 5 处。",
     "源码 <code>user-client/index.html:1651</code>（审批）、1393/1399/1405/1410（知识库）。",
     "与整站自研的手机壳 UI 风格割裂；移动端 WebView 中原生弹窗可能被拦截、样式不可控、无法做校验与长度限制；驳回意见必填的规则只能靠 code 兜底。",
     "统一替换为站内组件（复用已有的 <code>.notif-mask / .perm-modal</code>）：审批意见用自定义底部弹层，驳回时校验非空，支持常用语快捷项（同意/不同意/需补充材料）。",
     None),
    ("P0", "A-2", "审批", "普通成员「待我处理」把仅知会的事项标成「待处理」",
     "普通成员的「待我处理」里，「审批已通过」「审批被驳回」「数字员工已完成：政策快讯员」全部挂同一个「待处理」徽标，与真正的待办混在一起。",
     "待办-待我处理（普通成员）11 条；管理员侧同一标签是「待审批」单据，语义完全不同。",
     "语义错误：这些是通知知会、无需操作，却被判为待办并计入红点，长期造成红点疲劳；同一标签名在两种角色下含义不同，也会让后来者误读。",
     "把「需我操作」与「仅知会」分开：知会类用「已读/知会」样式且不计入角标；或直接将普通成员的该标签改名为「消息」，把审批结果单列「我的审批结果」。",
     "zh-02-todo-pending"),
    ("P1", "A-3", "审批", "审批列表缺少最关键的决策字段（请假起止日期）",
     "管理员待办里「请假申请 · 年假」只有标题、提交人、提交时间；请假时段只在详情页 <code>renderApprovalDetailExtra()</code> 才渲染出来。",
     "待办-待我处理（管理员）列表；详情页已有「请假时段」行。",
     "审批人必须逐条点开才能看到最影响判断的信息（请几天、与谁冲突），8+ 条待办时成本很高。",
     "列表行补一行摘要：<code>年假 · 2026-09-15 至 2026-09-16（2 天）</code>——后端 <code>formData</code> 已具备，前端行内解析即可。",
     "ad-02-todo-pending"),
    ("P1", "A-4", "审批", "审批项图标单一、无类型/结果区分",
     "所有审批项都用同一个 <code>doc</code> 图标（<code>todoRow('doc', …)</code> 硬编码），请假/文稿/成果视觉上不可辨；状态徽标也只有「待审批」一种色。",
     "待办-待我处理（管理员）8 条，图标完全一致。",
     "列表可扫读性差，用户无法靠视觉快速定位某一类事项。",
     "按 <code>bizType</code> 映射图标与主题色（请假=日历/蓝、文稿=文件/紫、成果=奖杯/金）；状态徽标按 PENDING/APPROVED/REJECTED 用蓝/绿/红三色。",
     None),
    ("P1", "A-5", "审批", "「我的申请」截断 5 条且无「查看全部」",
     "<code>renderTodo()</code> 中 <code>mineList.slice(0,5)</code>，只渲染前 5 条，界面上没有任何「还有 N 条 / 查看全部」的提示。",
     "源码 <code>user-client/index.html:1504</code> 附近；实测「我的申请」有 10+ 条只显示 5 条。",
     "用户以为申请丢了或没提交成功，反复重提，产生重复单据。",
     "列表尾部补「查看全部 N 条」入口（进独立列表页或弹层），并在计数处显示总数。",
     "zh-03-todo-mine"),
    ("P1", "D-3", "数字员工", "管理员卡片一行 4 个按钮，横向拥挤",
     "管理员视角下员工卡片底部同时出现「对话 / 运行记录 / 立即执行 / 调整任务」四个按钮，在 400px 宽的手机壳里已到极限，触及屏幕边缘。",
     "数字员工列表（管理员）政策快讯员卡片。",
     "按钮过密导致误触；主次不分，看不出哪个是最高频操作。",
     "保留「对话」为主按钮，其余收进「⋯」溢出菜单；或按「常看/偶尔看」分两级。",
     "ad-04-agent-workers"),
    ("P1", "D-4", "数字员工", "「数字员工」与「专家服务」概念重叠",
     "「办文助手」同时出现在「数字员工」标签与「专家服务」标签中，两处图标、文案、入口都不同，用户难以理解二者关系。",
     "专家服务标签：政策咨询专家/法律援助专家/企业开办顾问/办文助手；数字员工标签：政策快讯员/请假助手/办文助手。",
     "同一个东西两个身份，用户不知该在哪儿找；也削弱了 V1.2「数字员工」这一核心叙事。",
     "明确分层：「专家服务」定位为可订阅的<b>能力模板/人设</b>（只读、由管理员预置），「数字员工」定位为已<b>实例化、在跑、有产出</b>的角色；同名时在专家卡片标注「已实例化为数字员工 · 查看」。",
     "zh-06-agent-experts"),
    ("P1", "G-1", "通用", "会话页裸露技术术语「模型：deepseek-chat」",
     "会话头在运行开始时把后端 <code>p.model</code> 直接写入 <code>#chatModel</code>，显示为「模型：deepseek-chat」（默认态是「模型：智能路由」）。",
     "源码 <code>user-client/index.html:2129</code>；实测会话头出现 <code>模型：deepseek-chat</code>。",
     "模型标识属于工程细节，对业务用户是噪音；不同员工显示不同模型名还会引发「为什么这个更差」的无效比较。",
     "对外统一显示「智能路由」或「标准模型 / 增强模型」档位；真实模型名仅在调试模式或管理端可见。",
     "ad-07-chat-open"),
    ("P1", "G-2", "通用", "请假类会话仍显示无关的「知识库 开」开关",
     "与请假助手对话时，底部输入区仍有「知识库 开/关」离线开关，而请假审批并不依赖知识库检索。",
     "会话页底部输入区实测。",
     "无关控件增加认知负担，用户可能误开导致回答被知识库内容干扰。",
     "按 <code>workerType</code> 决定是否展示该开关：仅 <code>KB_ASSISTANT</code> 等知识型员工显示，其余隐藏。",
     None),
    ("P2", "D-5", "数字员工", "卡片信息密度过高",
     "「最近产出」正文一次铺满 5–6 行，把「运行计划/执行时刻」这些关键配置挤到很下面，卡片高度接近一屏。",
     "数字员工列表卡片。",
     "首屏可见员工数变少，滚动成本高。",
     "产出预览收敛到 2 行 + 「展开」；把「运行计划」提到标题下方作为副标题。",
     "zh-05-agent-cards"),
    ("P2", "A-6", "审批", "时间用绝对全量格式",
     "列表统一显示 <code>2026-09-11 16:11</code>，年份与秒级精度对近期事项是冗余信息。",
     "待办列表全部行。",
     "扫读效率低，重要度不易判断。",
     "改相对时间（今天 16:11 / 昨天 / 09-11），保留完整时间在 <code>title</code> 或详情页。",
     None),
    ("P2", "A-7", "审批", "提交请假后缺少结果确认",
     "<code>submitLeave()</code> 成功后仅 <code>toast('请假申请已提交，等待部门领导审批')</code> 随即跳转待办，没有新单据的摘要卡。",
     "源码 <code>user-client/index.html:2440</code> 附近。",
     "用户不确定是否提交成功、单号是什么、谁在审。",
     "提交成功展示一张结果卡：单号 / 类型 / 时段 / 当前状态 / 「查看详情」。",
     None),
    ("P2", "A-8", "审批", "请假表单缺关键校验",
     "<code>submitLeave()</code> 只校验开始/结束日期非空、事由非空；未校验「结束≥开始」，也未提示过去日期。",
     "源码 <code>user-client/index.html:2431</code> 附近。",
     "可提交出「结束早于开始」的非法单据，进入审批流后再被打回，浪费审批人时间。",
     "补 <code>end &gt;= start</code>、「结束日期不能早于开始日期」的行内提示；过去日期给出二次确认。",
     None),
    ("P2", "G-3", "通用", "表单内文字换行断裂",
     "请假表单里「＋ 上传附件」被拆成「＋ 上传附 / 件」，「支持病历/准假证明等」被拆成「支持病历/准假证 / 明等」。",
     "会话页请假表单截图。",
     "排版不精致，影响产品质感。",
     "给按钮 <code>white-space:nowrap</code>，并把提示文案放到按钮下方独立一行。",
     "zh-08-chat-answer"),
    ("P2", "G-4", "通用", "会话头信息冗余",
     "会话头同一行同时出现「对话模式 · 请假审批数字人」与「职责限定：请假审批数字人」，角色名重复两遍。",
     "源码 <code>useAgent()</code> 设置 <code>chatModel='对话模式 · '+roleName</code>，同时 scope 徽标为「职责限定：'+roleName」。",
     "占用宝贵的一行高度，信息量为零。",
     "合并为一条：「请假审批数字人 · 职责限定」，或让 <code>chatModel</code> 只显示模型档位。",
     "zh-08-chat-answer"),
    ("P2", "G-5", "通用", "演示/测试数据污染真实视图",
     "「我的成果」出现「回归-驳回链路」「回归-审批链路」（来源标注「回归测试」）；管理员待办里有名为「test」的审批单；成果列表时间戳显示「刚刚」。",
     "我的页（普通成员）成果区、管理员待办列表。",
     "走查/演示时会被误认为真实业务数据，影响判断与信任。",
     "清理测试单据与成果；或以统一的「示例数据」标记并在演示环境隔离。",
     "zh-11-me"),
]

SEV_LABEL = {"P0": "高", "P1": "中", "P2": "低"}

cards = []
for sev, fid, area, title, sym, ev, imp, adv, figname in F:
    f = fig(figname, "截图依据") if figname else ""
    cards.append("""
    <section class="card">
      <div class="chead"><span class="sev %s">%s</span><span class="fid">%s</span>
        <span class="area">%s</span><h3>%s</h3></div>
      <div class="cbody">
        <div class="blk"><span class="k">现象</span><p>%s</p></div>
        <div class="blk"><span class="k">证据</span><p>%s</p></div>
        <div class="blk"><span class="k">影响</span><p>%s</p></div>
        <div class="blk fix"><span class="k">建议</span><p>%s</p></div>
        %s
      </div>
    </section>""" % (sev, SEV_LABEL[sev], fid, area, html.escape(title), sym, ev, imp, adv, f))

cnt = {"P0": 0, "P1": 0, "P2": 0}
for sev, *_ in F:
    cnt[sev] += 1

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f4f6fb;color:#1b2230;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.7}
.wrap{max-width:1080px;margin:0 auto;padding:32px 22px 80px}
.hero{background:linear-gradient(135deg,#1f4fd8,#3b7dea);color:#fff;border-radius:18px;padding:26px 28px;
  box-shadow:0 12px 30px rgba(31,79,216,.22)}
.hero h1{margin:0 0 6px;font-size:25px}
.hero .sub{opacity:.92;font-size:13.5px}
.hero .meta{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px}
.hero .meta span{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);
  border-radius:999px;padding:4px 12px;font-size:12.5px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0 4px}
.stat{background:#fff;border:1px solid #e6eaf3;border-radius:14px;padding:14px 16px}
.stat b{display:block;font-size:24px;color:#1f4fd8}
.stat span{font-size:12.5px;color:#66718a}
.stat.p0 b{color:#d92d20}.stat.p1 b{color:#e08600}.stat.p2 b{color:#3b7dea}
h2.sec{font-size:18px;margin:34px 0 12px;padding-left:11px;border-left:4px solid #1f4fd8}
.card{background:#fff;border:1px solid #e6eaf3;border-radius:14px;padding:16px 18px;margin-bottom:14px;
  box-shadow:0 2px 8px rgba(22,34,64,.04)}
.chead{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:6px}
.chead h3{margin:0;font-size:15.5px;flex:1 1 100%;order:4;font-weight:700}
.sev{font-size:11.5px;font-weight:700;color:#fff;border-radius:6px;padding:2px 8px}
.sev.P0{background:#d92d20}.sev.P1{background:#e08600}.sev.P2{background:#3b7dea}
.fid{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:#66718a}
.area{font-size:11.5px;color:#1f4fd8;background:#eaf1ff;border:1px solid #cfe0ff;border-radius:6px;padding:2px 8px}
.blk{margin:9px 0}
.blk .k{display:inline-block;font-size:11.5px;font-weight:700;color:#fff;background:#8a94a8;border-radius:5px;
  padding:1px 8px;margin-bottom:3px}
.blk p{margin:4px 0 0;font-size:13.5px;color:#2b3448}
.blk.fix .k{background:#1f8a4d}.blk.fix p{background:#f1faf4;border:1px solid #cdeada;border-radius:9px;padding:9px 12px}
code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:#f1f4fa;border:1px solid #e2e8f4;
  border-radius:5px;padding:1px 5px;color:#25406e;word-break:break-word}
.fig{margin:12px 0 2px;text-align:center}
.fig img{max-width:100%;border:1px solid #e0e5f0;border-radius:12px}
.fig figcaption{font-size:12px;color:#7a8499;margin-top:6px}
.theme{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.theme .t{background:#fff;border:1px solid #e6eaf3;border-radius:14px;padding:15px 17px}
.theme .t b{display:block;color:#1f4fd8;margin-bottom:5px;font-size:14.5px}
.theme .t p{margin:0;font-size:13.3px;color:#3a4358}
.note{background:#fff8e6;border:1px solid #ffe1a3;border-radius:12px;padding:13px 16px;font-size:13.3px;color:#6b5312}
ol.flow{font-size:13.3px;color:#3a4358}
"""

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIOA 用户端体验走查报告（数字员工 · 审批）</title><style>%s</style></head><body><div class="wrap">

<div class="hero">
  <h1>AIOA 用户端体验走查报告</h1>
  <div class="sub">范围：<code style="background:rgba(255,255,255,.18);border-color:rgba(255,255,255,.3);color:#fff">http://localhost:5181</code> 公开页面 · 重点：数字员工 与 审批<br>
  方式：真实浏览器（Edge 无头）以「普通成员 zhangsan」与「租户管理员 admin」两种身份各走一遍全流程，逐页截图取证</div>
  <div class="meta"><span>普通成员 zhangsan</span><span>管理员 admin</span><span>截图 26 张</span><span>问题 %d 项</span><span>2026-09-11</span></div>
</div>

<div class="stats">
  <div class="stat p0"><b>%d</b><span>高优先级（P0）</span></div>
  <div class="stat p1"><b>%d</b><span>中优先级（P1）</span></div>
  <div class="stat p2"><b>%d</b><span>低优先级（P2）</span></div>
  <div class="stat"><b>2</b><span>覆盖角色</span></div>
</div>

<h2 class="sec">一、总体印象（先说好的）</h2>
<div class="card"><div class="cbody">
<ol class="flow">
<li><b>角色分档已经真实生效</b>：普通成员看不到创建/启停/立即执行/调整任务，只剩「对话 + 运行记录」，并显示「管理操作仅租户管理员可执行」的说明；管理员侧按钮齐全。越权拦截提示文案清楚。</li>
<li><b>「与服务对象对话」的闭环走通了</b>：向请假助手说「我要请假两天」→ 得到职责内的专业回答 → 自动发放《请假申请》表单 → 表单字段（类型/起止/事由/证明材料）齐全。</li>
<li><b>信息架构方向正确</b>：「专家与员工」双标签、待办三标签、会话头「职责限定」徽标，都在往「角色化 + 可追溯」的方向走。</li>
<li><b>可追溯性有体现</b>：每次回答后显示「本次消耗 N 词元（输入/输出）· 已入账本并留痕」，符合平台定位。</li>
</ol>
</div></div>

<h2 class="sec">二、问题清单（按优先级）</h2>
%s

<h2 class="sec">三、改进方向总结</h2>
<div class="theme">
  <div class="t"><b>① 语义纠偏：让「产出 / 待办 / 待配置」名副其实</b>
  <p>当前最伤信任的不是缺功能，而是<b>标签与内容不符</b>：空产出显示成产出（D-1）、纯知会显示成待处理（A-2）、事件驱动员工显示成待配置（D-2）。这三处都属「状态语义」缺陷，改动量小、收益最大，建议列为第一批。</p></div>
  <div class="t"><b>② 审批闭环：从「能用」到「好用」</b>
  <p>把原生 <code>prompt/confirm/alert</code> 全部换成本站自研弹层（A-1）；列表行前置关键决策字段（请假时段/天数，A-3）；提交后给结果确认卡（A-7）；补 <code>结束≥开始</code> 校验（A-8）。目标是让审批人在列表页就能判断「批不批」。</p></div>
  <div class="t"><b>③ 信息架构：厘清「数字员工」与「专家」</b>
  <p>同名角色双列（D-4）会让核心叙事失效。建议把「专家服务」明确定义为<b>管理员预置的能力模板</b>，「数字员工」为<b>已实例化在跑的角色</b>，并允许「由专家一键实例化为数字员工」，把两者从竞争关系变成上下游关系。</p></div>
  <div class="t"><b>④ 产品化收口：去技术味、去测试味</b>
  <p>面向业务用户隐藏模型名等技术细节（G-1）、按员工类型裁剪控件（G-2）、清理「test / 回归测试」类演示数据（G-5）。这些是「看起来像不像成品」的关键细节。</p></div>
</div>

<h2 class="sec">四、建议的落地顺序</h2>
<div class="card"><div class="cbody">
<ol class="flow">
<li><b>第一批（低成本高收益，1–2 天）</b>：D-1 产出语义、D-2 待配置判定、A-2 待处理语义、A-1 审批弹窗组件化、G-1 隐藏模型名。</li>
<li><b>第二批（审批体验，2–3 天）</b>：A-3 列表前置决策字段、A-4 类型图标与色彩、A-5 查看全部、A-7 提交结果卡、A-8 表单校验。</li>
<li><b>第三批（信息架构与打磨，3–5 天）</b>：D-4 员工/专家分层、D-3 按钮溢出菜单、D-5 密度收敛、G-2 控件裁剪、G-3 排版、G-4 头部去重、A-6 相对时间、G-5 数据清理。</li>
</ol>
<div class="note" style="margin-top:12px">说明：本报告所有结论均来自本次真实渲染的截图与源码定位（<code>user-client/index.html</code> 行号已标注），未做主观臆测；问题按「现象—证据—影响—建议」四段式给出，可直接转成待办。</div>
</div></div>

</div></body></html>""" % (CSS, len(F), cnt["P0"], cnt["P1"], cnt["P2"], "".join(cards))

with open(os.path.join(OUT, "用户体验走查报告.html"), "w", encoding="utf-8") as f:
    f.write(HTML)
print("报告已生成：", os.path.join(OUT, "用户体验走查报告.html"))
print("内嵌截图 %d 张，问题 %d 项" % (len(IMG), len(F)))
