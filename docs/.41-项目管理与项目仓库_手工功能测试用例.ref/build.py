# -*- coding: utf-8 -*-
"""生成《AIOA 项目管理 / 项目与仓库 · 手工功能测试用例》工作簿。

期望结果全部与「当天实测系统」同源（接口 / 视图源码 / DB 结构），
差异项集中在「数据对齐说明」页，避免测试者按虚构数据误报缺陷。
"""
try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess
    import sys

    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "openpyxl>=3.1.0"])
    import openpyxl

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import CellIsRule

# ----------------------------------------------------------------------------
# 配色（CSS #RRGGBB -> OOXML ARGB）
# ----------------------------------------------------------------------------


def xl_color(css_hex: str) -> str:
    value = css_hex.removeprefix("#").upper()
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB, got: {css_hex}")
    return "FF" + value


XL_HEAD = xl_color("#4472C4")      # 表头底（商务蓝）
XL_HEAD_FG = xl_color("#FFFFFF")
XL_TITLE = XL_HEAD
XL_BORDER = xl_color("#BFBFBF")
XL_SUM_BG = xl_color("#D9E2F3")    # 汇总区浅蓝
XL_SUM_FG = xl_color("#1F3864")
XL_OK_BG = xl_color("#C6EFCE")
XL_OK_FG = xl_color("#006100")
XL_BAD_BG = xl_color("#FFC7CE")
XL_BAD_FG = xl_color("#9C0006")
XL_WARN_BG = xl_color("#FFEB9C")
XL_WARN_FG = xl_color("#9C6500")
XL_GREY_BG = xl_color("#F2F2F2")
XL_GREY_FG = xl_color("#595959")
XL_POS_BG = xl_color("#E2EFDA")

THIN = Side(style="thin", color=XL_BORDER)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TOP_WRAP = Alignment(vertical="top", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center")

TITLE_FONT = Font(bold=True, size=13, color=XL_HEAD_FG)
HEAD_FONT = Font(bold=True, size=10, color=XL_HEAD_FG)
BODY_FONT = Font(size=10)
SUM_FONT = Font(bold=True, size=10, color=XL_SUM_FG)


def write_title(ws, ncols, text):
    """标题区：第 1 行合并居中。"""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(row=1, column=1, value=text)
    c.font = TITLE_FONT
    c.fill = PatternFill("solid", fgColor=XL_TITLE)
    c.alignment = CENTER
    for i in range(2, ncols + 1):
        ws.cell(row=1, column=i).fill = PatternFill("solid", fgColor=XL_TITLE)
    ws.row_dimensions[1].height = 26


def write_header(ws, row, headers):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = HEAD_FONT
        c.fill = PatternFill("solid", fgColor=XL_HEAD)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    ws.row_dimensions[row].height = 30


def write_rows(ws, start_row, rows, ncols, center_cols=()):
    r = start_row
    for row in rows:
        for i in range(1, ncols + 1):
            v = row[i - 1] if i - 1 < len(row) else None
            c = ws.cell(row=r, column=i, value=v)
            c.font = BODY_FONT
            c.border = BORDER
            c.alignment = CENTER if i in center_cols else TOP_WRAP
        r += 1
    return r - 1  # 最后一个数据行


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def add_summary(ws, anchor, data_last_row, result_col="I"):
    """执行进度统计块：标签在 A，公式在 B，全部引用用例数据区。"""
    ws.cell(row=anchor, column=1, value="执行进度统计（随【执行结果】列自动更新）")
    ws.cell(row=anchor, column=1).font = Font(bold=True, size=11, color=XL_SUM_FG)

    rng = f"${result_col}$3:${result_col}${data_last_row}"
    idr = f"$A$3:$A${data_last_row}"
    typer = f"$C$3:$C${data_last_row}"

    s1 = anchor + 1  # 用例总数
    s2 = anchor + 2  # 正向
    s3 = anchor + 3  # 反向
    s4 = anchor + 4  # 已执行
    s5 = anchor + 5  # 已通过
    s6 = anchor + 6  # 通过率
    s7 = anchor + 7  # 待执行

    items = [
        ("用例总数", f"=COUNTA({idr})"),
        ("正向用例", f'=COUNTIF({typer},"正向")'),
        ("异常反向用例", f'=COUNTIF({typer},"反向")'),
        ("已执行（通过+失败+阻塞）",
         f'=COUNTIF({rng},"通过")+COUNTIF({rng},"失败")+COUNTIF({rng},"阻塞")'),
        ("已通过", f'=COUNTIF({rng},"通过")'),
        ("通过率", f'=IF(OR(B{s4}="",B{s4}=0),"",B{s5}/B{s4})'),
        ("待执行", f'=COUNTIF({rng},"未执行")'),
    ]
    for idx, (label, formula) in enumerate(items):
        r = s1 + idx
        lc = ws.cell(row=r, column=1, value=label)
        lc.font = SUM_FONT
        lc.fill = PatternFill("solid", fgColor=XL_SUM_BG)
        lc.border = BORDER
        vc = ws.cell(row=r, column=2, value=formula)
        vc.font = SUM_FONT
        vc.fill = PatternFill("solid", fgColor=XL_SUM_BG)
        vc.border = BORDER
        vc.alignment = Alignment(horizontal="center", vertical="center")
        vc.number_format = "0.00%" if label == "通过率" else "0"
    return s6


wb = openpyxl.Workbook()
wb.properties.title = "AIOA 项目管理与项目仓库 手工功能测试用例"

# ============================================================================
# Sheet 1：重点联动场景对照
# ============================================================================
ws = wb.active
ws.title = "重点联动场景对照"
HEAD1 = ["场景号", "场景（需求原话）", "关键验证点", "关联用例ID", "实测结论（与当天系统同源）", "风险提示"]
W1 = [8, 30, 36, 22, 62, 28]
write_title(ws, len(HEAD1), "AIOA 项目管理 / 项目与仓库 · 五大重点联动场景对照")
write_header(ws, 2, HEAD1)
set_widths(ws, W1)

ROWS1 = [
    ("场景1",
     "建开发项目 PROJ-2026-002，绑定仓库 fagai-project-ledger，验证能在【项目与仓库】列表中看到",
     "① 项目类型=开发项目才有【代码仓库】页签；② 绑定后仓库归属唯一；③ 仓库出现在【项目与仓库】列表",
     "PM-005、PM-006、GR-012、GR-013",
     "链路成立，但与你给的数据有两处不符：\n"
     "① 仓库名由平台按「dept{部门ID}-{项目名slug}」派生（实测库内既有仓库全部形如 dept10-xxx / dept11-xxx），"
     "不会出现字面量 fagai-project-ledger，除非项目名恰好能被 slug 成该串；\n"
     "② 只有「尚未归属任何项目」的仓库才能被绑定（一个仓库只归一个项目）；\n"
     "③ 实测当前库中不存在名为 fagai-project-ledger 的仓库，需先按 GR-012 新建。",
     "中。若按字面仓库名逐字核对，会把「派生命名」误判为缺陷。请以列表中的实际 repoName 为准。"),
    ("场景2",
     "建业务项目 PROJ-2026-001，验证不出现代码仓库绑定选项",
     "① 新建对话框类型=业务项目时仓库字段全部不渲染；② 提示文案正确；③ 服务端同样拒绝（前端隐藏≠边界）",
     "PM-002、PM-003、PM-023",
     "成立。界面层在类型=业务项目时不渲染【代码仓库策略】分隔线、仓库策略单选、选择仓库下拉与可见性，"
     "改为提示「业务项目无需仓库配置」；服务端 ProjectTypeGuard（BR-01）在创建/绑仓库/建任务三条写入路径上兜底拒绝，"
     "直接构造请求也返回 400「业务项目不支持代码仓库配置」。",
     "无。"),
    ("场景3",
     "Gitee 未初始化时，进入开发项目尝试绑仓库，验证拦截文案为「尚未初始化，使用企业自己的访问令牌与组织登录名初始化后，建仓等写操作将使用企业令牌，不依赖个人 OAuth 绑定」",
     "① 文案是否存在且逐字一致；② 它出现在哪个位置；③ 是否真的「拦住」建仓/绑仓库动作",
     "GR-002、GR-003、GR-004",
     "★ 需重点澄清：文案存在，但它不是「绑仓库时的拦截」，而是常驻告知横幅。\n"
     "位置：【项目与仓库】→「企业 Gitee 初始化」卡片内的 info 提示框（标题「尚未初始化」+ 正文逐字一致）。\n"
     "拦截：当前**没有**任何「未初始化即禁止建仓」的守卫。令牌获取顺序为「个人令牌优先 → 企业令牌兜底 → 都没有才报错」"
     "（GiteeTokenService.requireAccessToken）。实测个人账号已绑定（liu-yang20 / 刘尖尖），"
     "因此未初始化状态下建仓会**回落到个人 OAuth 令牌并可能成功**。",
     "高。若按「进开发项目→绑仓库应被弹窗拦截」验收，会误报缺陷。正确口径：文案=告知；硬拦截=不存在（属需求增量）。"),
    ("场景4",
     "验证运维/校准面板统计、手动校准按钮、定时校准开关",
     "① 四项统计与 Worker 名；② 手动校准可触发；③ 定时校准是否可切换",
     "GR-005、GR-006、GR-007、GR-008",
     "统计完全一致：待处理(PENDING)=0、执行中(RUNNING)=0、已完成(DONE)=1836、失败(FAILED)=1445、"
     "Worker=aioa-gitee-1，与 GET /api/v1/gitee/tasks/stats 实测逐字相符；定时校准标签=开启、删除连仓标签=否；"
     "【手动校准】按钮存在且可用（POST /gitee/calibrate，返回 scope=TENANT:2）。\n"
     "但【定时校准】是**只读标签（el-tag）**，页面上**没有开关控件**。",
     "中。若「定时校准开关」被要求为可切换，属功能缺口，需先确认需求口径再记缺陷。"),
    ("场景5",
     "列表筛选：按项目类型、项目编号、仓库名查询",
     "① 项目管理侧：类型/状态/编号关键字；② 项目与仓库侧：归属部门 + 仓库名",
     "PM-008、PM-009、PM-010、PM-011、PM-012、GR-009、GR-010、GR-011",
     "成立。PM 侧关键字同时匹配「项目名称 LIKE」与「项目编号 LIKE」（后端 and(name like OR project_no like)）；"
     "项目与仓库侧关键字匹配「项目名称/仓库名」，另有【归属部门】下拉（取自 /gitee/departments，含命名前缀如 dept11-）。\n"
     "注意：两处列表均**无分页**（PM 返回全量数组；仓库侧返回 items+total），筛选是服务端过滤后整表返回。",
     "低。数据量大时无分页只是体验问题，不是缺陷。"),
]
last1 = write_rows(ws, 3, ROWS1, len(HEAD1), center_cols=(1, 4))
ws.freeze_panes = "A3"
ws.auto_filter.ref = f"A2:{get_column_letter(len(HEAD1))}{last1}"

# ============================================================================
# Sheet 2：项目管理用例
# ============================================================================
ws2 = wb.create_sheet("项目管理用例")
HEAD2 = ["用例ID", "模块", "场景类型", "测试点", "前置条件", "操作步骤", "预期结果", "实测依据 · 说明", "执行结果", "备注"]
W2 = [10, 12, 11, 26, 40, 54, 58, 46, 11, 26]
write_title(ws2, len(HEAD2), "【项目管理】模块 · 手工功能测试用例（V71 批次 1 口径）")
write_header(ws2, 2, HEAD2)
set_widths(ws2, W2)

ENV = "管理端 http://127.0.0.1:8080/aioa/web/ ；账号 dsj_admin / User@123 / 租户「某某市某某区大数据管理局」；后端 8080 正常、V71 迁移已应用"
ROWS2 = [
    ("PM-001", "项目管理", "正向", "菜单可达性与页面结构",
     ENV,
     "1) 左侧菜单点【成果与项目】\n2) 点【项目管理】\n3) 观察页面结构",
     "进入 /pm/projects。页顶 info 提示：「项目管理 —— 立项 → 成员 → 任务 → 文档 → 经费 → 合同。项目分【业务项目】与【开发项目】两类；仅开发项目涉及代码仓库绑定与任务仓库关联。」\n"
     "卡片标题「项目列表」；筛选区含【项目类型】【项目状态】两个下拉、「按编号或名称搜索」输入框、【查询】；右上【刷新】【新建项目】。\n"
     "表头列依次为：项目编号 / 项目名称 / 类型 / 状态 / 负责人 / 任务 / 成员 / 仓库 / 我的角色 / 操作。\n"
     "无数据时表格区显示「暂无项目」。",
     "PmProjectsView.vue L1-105；实测列表当前为空（pm_project 基线 0 行）",
     "未执行", "空列表是当前基线，勿当成加载失败"),

    ("PM-002", "项目管理", "正向", "新建业务项目 PROJ-2026-001",
     ENV + "；项目编号 PROJ-2026-001 未被占用",
     "1) 点【新建项目】\n2) 项目类型选【业务项目】\n3) 项目编号填 PROJ-2026-001\n4) 项目名称填「发改局2026政务信息化需求调研项目」\n"
     "5) 负责人选「王振华」\n6) 预算总额填 128000\n7) 起止日期 2026-01-05 ~ 2026-12-31\n8) 点【创建】",
     "提示「项目已创建」，对话框关闭，列表新增该行：项目编号=PROJ-2026-001、类型=业务项目（灰色 plain 标签）、"
     "状态=进行中（蓝色标签）、负责人=王振华、仓库列显示「—」。\n"
     "点项目名称进详情：【概览】预算总额=¥128,000.00、类型=业务项目、状态=进行中；"
     "页签只有 概览 / 任务 / 成员 / 文档 / 经费 / 合同，**没有【代码仓库】页签**。",
     "创建时后端恒置 status=ACTIVE；仓库列 `projectType==='DEV' ? repoCount : '—'`（L77-82）；"
     "isDev 控制仓库页签（PmProjectDetailView L340）",
     "未执行", "负责人只能选「在册员工」，不能填 admin"),

    ("PM-003", "项目管理", "反向", "业务项目不应渲染任何仓库配置项（BR-01 界面层）",
     ENV,
     "1) 点【新建项目】\n2) 项目类型选【业务项目】\n3) 观察表单剩余字段",
     "不出现「代码仓库策略（仅开发项目）」分隔线、【仓库策略】单选组（绑定既有仓库 / 自动建仓 / 暂不绑定）、"
     "【选择仓库】下拉、【仓库可见性】单选。\n"
     "取而代之显示 info 提示框：标题「业务项目无需仓库配置」，正文「业务项目只含业务字段。若后续需要代码仓库，可在项目详情中把类型改为「开发项目」。」",
     "PmProjectsView L157 `v-if=\"form.projectType === 'DEV'\"`；L186-194 为 v-else 提示框",
     "未执行", "—"),

    ("PM-004", "项目管理", "反向", "项目编号重复必须被拒（唯一性）",
     "PM-002 已创建 PROJ-2026-001",
     "1) 点【新建项目】\n2) 类型选【业务项目】\n3) 编号填 PROJ-2026-001\n4) 名称填「重复编号验证」\n5) 点【创建】",
     "弹出红色错误提示「项目编号已存在：PROJ-2026-001」；对话框不关闭；列表不新增行。\n"
     "服务端返回 409，数据层由唯一键 uk_pm_project_no(tenant_id, project_no, alive) 兜底。",
     "PmProjectService L124 抛 409；MySQL 实测存在索引 uk_pm_project_no",
     "未执行", "—"),

    ("PM-005", "项目管理", "正向", "新建开发项目 PROJ-2026-002（含自动建仓分支）",
     ENV + "；已绑定个人 Gitee 账号 或 已完成企业 Gitee 初始化（见 GR-021）",
     "1) 点【新建项目】\n2) 项目类型选【开发项目】（出现「代码仓库策略（仅开发项目）」分隔线）\n"
     "3) 仓库策略选【自动建仓】\n4) 仓库可见性选【私有】\n5) 编号填 PROJ-2026-002\n"
     "6) 名称填「发改局项目台账管理系统开发」\n7) 负责人选「王振华」\n8) 预算总额填 365000\n9) 点【创建】",
     "成功分支：提示「项目已创建」；列表新行 类型=开发项目（橙色 warning 标签）、仓库列=1；详情出现【代码仓库】页签并列出该仓库。\n"
     "降级分支（当前环境更可能命中）：黄色警告「项目已创建，但自动建仓未成功：<原因>（可在「项目与仓库」建好仓库后，回本项目详情页「仓库」页签绑定）」，"
     "**项目仍然创建成功**，仓库列=0。\n"
     "两个分支都判为通过。",
     "自动建仓为「尽力而为」：失败 catch 后回 repoWarning，不阻断立项（PmProjectService L165-181）；"
     "前端 created.repoWarning → ElMessage.warning",
     "未执行", "★ 不可把「建仓失败」直接记为缺陷，只有「提示缺失」才是缺陷"),

    ("PM-006", "项目管理", "正向", "开发项目【代码仓库】页签 + 绑定既有仓库",
     "存在 1 个尚未归属任何项目的仓库（先用 GR-012 造数）；项目类型=开发项目",
     "1) 进入开发项目详情\n2) 点【代码仓库】页签\n3) 点【绑定仓库】\n4) 在【选择仓库】下拉选一个仓库\n5) 点【绑定】",
     "绑定成功；页签表格新增该仓库行（仓库名 / 路径 / 默认分支 / 状态）；【概览】仓库计数 +1；列表页「仓库」列 +1。",
     "PmProjectDetailView L44-70；POST /pm/projects/{id}/repos",
     "未执行", "业务项目详情看不到该页签"),

    ("PM-007", "项目管理", "反向", "一个仓库只能归一个项目（候选去重 + 服务端拒绝）",
     "仓库 R 已被项目 A 绑定",
     "1) 项目 B（开发项目）详情 →【绑定仓库】\n2) 展开【选择仓库】下拉，观察 R 是否出现\n"
     "3) 若未出现，用接口 POST /api/v1/pm/projects/{B}/repos body {\"repoId\": R} 复验",
     "① 下拉候选中**不含** R；\n② 绕过界面直接提交时返回 409，提示「该仓库已归属其它项目，请先在其项目中解绑」。",
     "PmProjectService L387-391；提示语逐字来自源码",
     "未执行", "—"),

    ("PM-008", "项目管理", "正向", "按项目编号筛选",
     "PM-002 / PM-005 已创建两个项目",
     "1) 在「按编号或名称搜索」输入框输入 PROJ-2026-002\n2) 回车或点【查询】",
     "列表仅剩 PROJ-2026-002 一行，PROJ-2026-001 不出现。",
     "后端 keyword → `.like(name) OR .like(project_no)`（PmProjectService L206-207）",
     "未执行", "—"),

    ("PM-009", "项目管理", "正向", "按项目名称关键字筛选",
     "同上",
     "1) 关键字改为「台账管理」\n2) 回车或点【查询】",
     "命中 PROJ-2026-002（名称含「台账管理」）；PROJ-2026-001 不出现。",
     "同上",
     "未执行", "—"),

    ("PM-010", "项目管理", "正向", "按项目类型筛选",
     "同上",
     "1) 【项目类型】选【业务项目】\n2) 再选【开发项目】\n3) 再点下拉的 clearable 清除",
     "① 只剩业务项目行；② 只剩开发项目行；③ 恢复全部行。每次选择后自动查询，无需点【查询】。",
     "query.projectType → /pm/projects?projectType=BUSINESS|DEV；下拉 @change=\"reload\"",
     "未执行", "—"),

    ("PM-011", "项目管理", "正向", "按项目状态筛选",
     "同上",
     "1) 【项目状态】选【进行中】\n2) 再选【草稿】",
     "① 两个新建项目都出现（新建即 ACTIVE/进行中）；② 选【草稿】时列表为空并显示「暂无项目」。",
     "状态枚举实测为 DRAFT/ACTIVE/SUSPENDED/CLOSED/ARCHIVED；创建恒 ACTIVE",
     "未执行", "「进行中」是新建项目的默认态"),

    ("PM-012", "项目管理", "反向", "类型 + 状态交叉筛选无交集",
     "同上",
     "1) 【项目类型】选【业务项目】\n2) 【项目状态】选【已归档】\n3) 点【查询】",
     "列表为空，表格区显示「暂无项目」；页面不报错、不白屏、控制台无未捕获异常。",
     "两个条件 AND 组合查询；空态由 el-table #empty 模板渲染",
     "未执行", "—"),

    ("PM-013", "项目管理", "正向", "项目状态合法流转（进行中 ⇄ 暂停）",
     "PROJ-2026-001 状态=进行中；当前账号对该项目 canManage=true",
     "1) 进入详情\n2) 点【变更状态】→ 选【暂停】→ 确认\n3) 再点【变更状态】→ 选【进行中】→ 确认",
     "状态依次变为「暂停」（黄色标签）→「进行中」（蓝色标签）；列表页状态列同步刷新。",
     "状态机白名单：ACTIVE→{SUSPENDED,CLOSED,ARCHIVED}；SUSPENDED→{ACTIVE,CLOSED,ARCHIVED}",
     "未执行", "—"),

    ("PM-014", "项目管理", "反向", "非法状态流转必须被拒（进行中 → 草稿）",
     "PROJ-2026-001 状态=进行中",
     "1) 详情 →【变更状态】→ 选【草稿】→ 确认",
     "红色提示「不允许从 ACTIVE 变更为 DRAFT」；状态保持不变（仍为「进行中」）。\n"
     "注意：下拉里能选到【草稿】——下拉渲染的是全部枚举，拒绝发生在提交时。",
     "PmProjectService L337-338；DRAFT 不是任何状态的合法目标（TRANSITIONS 中无 →DRAFT）",
     "未执行", "下拉可选但提交被拒，属预期行为"),

    ("PM-015", "项目管理", "反向", "【草稿】状态在界面上不可达（枚举与状态机一致性核对）",
     ENV,
     "1) 尝试通过新建（无状态字段）\n2) 尝试通过详情【变更状态】改成【草稿】（见 PM-014）\n3) 汇总两条路径的结论",
     "无法通过任何界面操作把项目置为「草稿」。结论：当前实现下 DRAFT 只可能来自库内直接造数。\n"
     "判定：属**已知实现口径**，不作为缺陷；但若业务要求「立项后可先保存为草稿再提交」，属需求缺口，需另立需求。",
     "创建恒 ACTIVE（PmProjectService L144）；TRANSITIONS 无任何 →DRAFT 的迁移",
     "未执行", "★ 记录为口径说明，不作为缺陷上报"),

    ("PM-016", "项目管理", "反向", "已结项/已归档为只读终态，禁止再加成员、建任务",
     "把 PROJ-2026-001 流转到【已结项】（进行中 → 已结项，合法）",
     "1) 详情【任务】页签观察【新建任务】按钮\n2) 详情【成员】页签观察【添加成员】按钮\n"
     "3) 直接 POST /api/v1/pm/projects/{id}/tasks 复验",
     "① 界面按钮被隐藏或置灰不可用；② 直接调接口被拒（只读终态不允许写入子对象）。\n"
     "若界面按钮仍可点且接口能写成功 → 记缺陷。",
     "PmProjectStatus.isReadOnly(CLOSED/ARCHIVED)；CLOSED→{ARCHIVED} 合法",
     "未执行", "★ 该条是终态守卫，重点看「是否真的挡住」"),

    ("PM-017", "项目管理", "正向", "添加项目成员并指定项目内角色",
     "PROJ-2026-001 状态=进行中（未结项）",
     "1) 详情 →【成员】页签 →【添加成员】\n2) 选在册员工「刘敏」\n3) 项目角色选【项目经理】\n4) 点【添加】",
     "成员表新增行：姓名=刘敏、工号、职务、项目角色=项目经理；【概览】成员数 +1；列表页「成员」列 +1。",
     "项目内角色枚举 OWNER/PM/DEV/MEMBER/VIEWER（不是系统角色，仅本项目生效）",
     "未执行", "—"),

    ("PM-018", "项目管理", "反向", "负责人必须是本企业在册员工（BR-03）",
     ENV,
     "1) 【新建项目】→ 展开【负责人】下拉，记录候选范围\n"
     "2) 用接口 POST /api/v1/pm/projects 传 ownerMemberId=<非本企业 / 非在册员工的 id>",
     "① 界面下拉只列出 state=ACTIVE 的在册员工，无法录入任意 id；\n"
     "② 接口侧返回 400，提示「该员工不存在或不属于当前企业」或「该员工不在册（状态：xxx）」。",
     "PmProjectService L574 / L577；前端 listMembers({status:'ACTIVE'})",
     "未执行", "负责人≠系统账号，是机构在册员工"),

    ("PM-019", "项目管理", "正向", "开发项目任务可关联仓库 Issue（BR-12 成对）",
     "PROJ-2026-002 已绑定仓库 R",
     "1) 详情 →【任务】页签 →【新建任务】\n2) 标题填「台账接口开发」\n3) 选择代码仓库 R\n4) 关联 Issue 填 12\n5) 点【保存】",
     "任务创建成功；任务表「关联 Issue」列显示 12（该列**仅开发项目显示**）；任务计数 +1。",
     "PmProjectDetailView L100 `v-if=\"isDev\"`；BR-12 成对校验通过",
     "未执行", "—"),

    ("PM-020", "项目管理", "反向", "任务只填 Issue、不选仓库 → 拒绝",
     "PROJ-2026-002 详情 → 任务页签",
     "1) 【新建任务】→ 标题填「错误组合A」\n2) 仓库留空\n3) 关联 Issue 填 12\n4) 点【保存】",
     "红色提示「填写 issue / 分支 / 提交前必须先选择代码仓库」；任务不创建。",
     "ProjectTypeGuard.assertRepoPairing L75-77；提示语逐字来自源码",
     "未执行", "—"),

    ("PM-021", "项目管理", "反向", "任务选了仓库、不填 Issue → 拒绝",
     "同上",
     "1) 【新建任务】→ 标题填「错误组合B」\n2) 选择仓库 R\n3) 关联 Issue 留空\n4) 点【保存】",
     "红色提示「选择代码仓库后必须填写关联的 issue 号」；任务不创建。",
     "ProjectTypeGuard.assertRepoPairing L78-80",
     "未执行", "—"),

    ("PM-022", "项目管理", "反向", "文档 / 经费 / 合同页签为占位（**预期即空状态，不是缺陷**）",
     "已进入任一项目详情",
     "1) 依次点【文档】【经费】【合同】三个页签\n2) 记录每个页签的空状态文案",
     "三个页签各显示空状态（el-empty），文案分别为：\n"
     "· 文档：「项目文档（企业级公共 / 项目专属文件夹）随批次 3 交付」\n"
     "· 经费：「项目经费收支流水随批次 4 交付」\n"
     "· 合同：「合同、收付款明细与里程碑随批次 4 交付」\n"
     "结论：本批次刻意不做假界面，空状态即正确表现。",
     "PmProjectDetailView L171-181 占位页签 + L343-345 hint 文案",
     "未执行", "★ 你提供的合同 HT-2026-001 / 收付款 64000+64000 / 里程碑在本版本无法验证"),

    ("PM-023", "项目管理", "反向", "业务项目不允许绑仓库（BR-01 服务端边界，绕过界面）",
     "PROJ-2026-001（业务项目）已创建；存在仓库 R",
     "直接 POST /api/v1/pm/projects/{PROJ-2026-001 的 id}/repos  body {\"repoId\": R}",
     "返回 400，提示「业务项目不支持代码仓库配置」；该项目不新增仓库关联。",
     "PmProjectService L419；ProjectTypeGuard.assertRepoAllowed L30",
     "未执行", "★ 该用例证明「前端隐藏 ≠ 安全边界」"),

    ("PM-024", "项目管理", "反向", "开发项目改回业务项目受 BR-02 约束",
     "PROJ-2026-002（开发项目）已绑定 1 个仓库",
     "直接 PUT /api/v1/pm/projects/{id}  body {\"projectType\": \"BUSINESS\"}",
     "返回 409，提示「已存在仓库关联（已绑仓库 1 个、带仓库信息的任务 0 条），不能改为业务项目；请先解绑仓库并移除任务的仓库信息」。",
     "ProjectTypeGuard.assertTypeChangeable L50-55；提示语逐字来自源码",
     "未执行", "★ 界面无「改类型」入口（详情页只有 变更状态/绑定/解绑/任务/成员）→ 必须走接口"),

    ("PM-025", "项目管理", "正向", "解绑仓库后即可改回业务项目（BR-02 对照组）",
     "接 PM-024，先把该仓库【解绑】（并清掉任务的仓库信息）",
     "1) 详情【代码仓库】→ 对仓库点【解绑】\n2) 再 PUT /api/v1/pm/projects/{id} body {\"projectType\":\"BUSINESS\"}",
     "返回 200，类型变为业务项目；详情页【代码仓库】页签消失；列表页「仓库」列变为「—」。",
     "BR-02 条件（无仓库、无带仓库信息的任务）满足即放行",
     "未执行", "与 PM-024 构成正反对照"),

    ("PM-026", "项目管理", "反向", "无新建权限的角色看不到【新建项目】",
     "改用普通成员账号登录（ROLE_MEMBER）。可先试 fagai_liu / fagai_li；若其系统角色非普通成员，需另找 MEMBER 账号",
     "1) 进入【项目管理】\n2) 观察右上按钮区与行内操作列",
     "页面可见、列表只含其数据范围内的项目；右上**无**【新建项目】按钮；行内无【删除】（canManage=false）。",
     "PM_CREATE_ROLES = ADMIN/TENANT_ADMIN/ORG_ADMIN/DEPT_LEADER（不含 MEMBER）；"
     "模板 `v-if=\"canCreate\"` / `v-if=\"row.canManage\"`",
     "未执行", "先确认该账号的真实系统角色再下结论"),

    ("PM-027", "项目管理", "反向", "数据范围隔离：机构 A 管理员不得看到机构 B 的项目",
     "先用机构1管理员建 1 个项目（不选部门，落为机构直属），再用机构3管理员建 1 个",
     "1) 用机构1管理员（fagai_admin 王振华）登录查看列表\n2) 用机构3管理员（chengtou_admin 赵文博）登录查看列表",
     "各自只看到本机构项目；机构直属（department_id=0）项目对其机构管理员**可见**；对方机构项目不出现。",
     "数据范围共享判定点 canSee()：ORG_ADMIN 按 institutionId 匹配（含 dept-0 直属项目）；"
     "list 与 requireVisible 共用同一判定",
     "未执行", "★ 历史缺陷点：list 曾漏掉 dept=0 的机构直属项目"),

    ("PM-028", "项目管理", "正向", "删除项目：级联软删 + 仓库仅解绑不删代码",
     "PROJ-2026-001 存在且当前账号 canManage=true",
     "1) 列表页对 PROJ-2026-001 点【删除】\n2) 读确认框文案\n3) 点确认",
     "确认框文案为「确认删除项目「发改局2026政务信息化需求调研项目」？将级联软删其成员与任务（仓库仅解绑，不删除代码）。」；"
     "确认后提示「项目已删除」，列表该行消失，详情页不可再访问；库中为软删（deleted_at 有值），非物理删除。",
     "PmProjectsView.removeProject L244-261；软删由 alive/deleted_at 控制",
     "未执行", "测完请自行决定是否清理临时项目，避免污染后续基线"),
]
last2 = write_rows(ws2, 3, ROWS2, len(HEAD2), center_cols=(1, 2, 3, 9))
ws2.freeze_panes = "D3"
ws2.auto_filter.ref = f"A2:{get_column_letter(len(HEAD2))}{last2}"
# 条件格式：场景类型 + 执行结果
ws2.conditional_formatting.add(
    f"C3:C{last2}", CellIsRule(operator="equal", formula=['"正向"'],
                             fill=PatternFill("solid", bgColor=XL_POS_BG), font=Font(color=XL_OK_FG)))
ws2.conditional_formatting.add(
    f"C3:C{last2}", CellIsRule(operator="equal", formula=['"反向"'],
                             fill=PatternFill("solid", bgColor=XL_WARN_BG), font=Font(color=XL_WARN_FG)))
ws2.conditional_formatting.add(
    f"I3:I{last2}", CellIsRule(operator="equal", formula=['"通过"'],
                             fill=PatternFill("solid", bgColor=XL_OK_BG), font=Font(color=XL_OK_FG)))
ws2.conditional_formatting.add(
    f"I3:I{last2}", CellIsRule(operator="equal", formula=['"失败"'],
                             fill=PatternFill("solid", bgColor=XL_BAD_BG), font=Font(color=XL_BAD_FG)))
ws2.conditional_formatting.add(
    f"I3:I{last2}", CellIsRule(operator="equal", formula=['"阻塞"'],
                             fill=PatternFill("solid", bgColor=XL_WARN_BG), font=Font(color=XL_WARN_FG)))
ws2.conditional_formatting.add(
    f"I3:I{last2}", CellIsRule(operator="equal", formula=['"未执行"'],
                             fill=PatternFill("solid", bgColor=XL_GREY_BG), font=Font(color=XL_GREY_FG)))
dv_scene = DataValidation(type="list", formula1='"正向,反向"', allow_blank=True)
dv_scene.error = "请选择：正向 / 反向"
ws2.add_data_validation(dv_scene)
dv_scene.add(f"C3:C{last2}")
dv_result = DataValidation(type="list", formula1='"未执行,通过,失败,阻塞"', allow_blank=True)
dv_result.error = "请选择：未执行 / 通过 / 失败 / 阻塞"
ws2.add_data_validation(dv_result)
dv_result.add(f"I3:I{last2}")
add_summary(ws2, last2 + 2, last2)

# ============================================================================
# Sheet 3：项目与仓库用例
# ============================================================================
ws3 = wb.create_sheet("项目与仓库用例")
write_title(ws3, len(HEAD2), "【项目与仓库】（Gitee 联动）模块 · 手工功能测试用例")
write_header(ws3, 2, HEAD2)
set_widths(ws3, W2)

ROWS3 = [
    ("GR-001", "项目与仓库", "正向", "菜单可达性与页面分块",
     ENV,
     "1) 左侧菜单点【成果与项目】\n2) 点【项目与仓库】\n3) 观察页头与页面分块",
     "进入 /gitee/projects。页头托管方文案随后端 provider 渲染（当前 provider=gitee → 显示「Gitee」）。\n"
     "页面按角色分块：① 个人账号绑定；② 本企业 Gitee 组织；③ 企业 Gitee 初始化（仅租户管理员）；"
     "④ 运维与校准（仅租户管理员）；⑤ 项目列表。",
     "GiteeProjectsView.vue 模板结构；实测 GET /gitee/config → provider=gitee、providerLabel=Gitee",
     "未执行", "③④ 仅租户管理员可见"),

    ("GR-002", "项目与仓库", "正向", "★重点场景3：企业初始化「未初始化」状态与告知文案",
     ENV + "；当前 gitee_tenant_config(tenant 2) init_status=PENDING，且未配置企业令牌",
     "1) 进入【项目与仓库】\n2) 定位【企业 Gitee 初始化】卡片\n3) 逐项核对状态与文案",
     "① 状态标签=【未初始化】（灰色 info）；②【生效组织】=AI-OA；③【令牌所属账号】=—；④【令牌范围】=—；"
     "⑤【组织校验】= 未通过（warning 标签）；⑥ 按钮文案=【初始化】；\n"
     "⑦ 出现 info 提示框 —— 标题「尚未初始化」，正文「使用企业自己的访问令牌与组织登录名初始化后，建仓等写操作将使用企业令牌，不依赖个人 OAuth 绑定。」",
     "实测 GET /api/v1/gitee/init → initialized=false、initStatus=PENDING、orgName=AI-OA、tokenConfigured=false；"
     "前端 initStatusLabel：非 ACTIVE/FAILED 一律显示「未初始化」",
     "未执行", "★ 你是要验证的就是这条文案，位置在「企业 Gitee 初始化」卡片"),

    ("GR-003", "项目与仓库", "反向", "★重点场景3澄清：未初始化 ≠ 禁止建仓（令牌回落个人 OAuth）",
     "个人 Gitee 账号已绑定（实测 /gitee/bind → bound=true、giteeUsername=liu-yang20）；企业初始化仍为未初始化",
     "1) 在【项目列表】点【新建项目】\n2) 填项目名称、选归属部门\n3) 提交（触发建仓）",
     "建仓请求会**先取个人令牌**（存在即直接返回，不读企业令牌），因此未初始化状态下建仓**仍可能成功**。\n"
     "即：页面上「尚未初始化」只是告知，不构成对写操作的硬拦截。",
     "GiteeTokenService.requireAccessToken L121-137：个人令牌优先 → 企业令牌兜底 → 都没有才抛错",
     "未执行", "★ 设计如此，不是缺陷。若要求「未初始化即拦住建仓」属需求增量"),

    ("GR-004", "项目与仓库", "反向", "既无个人绑定、又未做企业初始化时，建仓必须给出明确指引",
     "先在【个人账号绑定】点【解绑】；企业初始化仍为未初始化",
     "1) 撤回个人绑定后，用【新建项目】提交一次建仓",
     "失败并给出明确指引（「当前账号尚未绑定 Gitee 账号…」或企业令牌失效类提示）；"
     "**不得静默失败**；项目行要么不创建，要么停在可重试的失败态并把原因写进 errorMsg，可在列表中看到。",
     "GiteeTokenService L135-137（staleBindingHint / 尚未绑定）",
     "未执行", "★ 有副作用：需解绑个人账号；建议放在最后执行，测完务必重新绑定或完成企业初始化"),

    ("GR-005", "项目与仓库", "正向", "★重点场景4：运维与校准面板统计",
     "以租户管理员登录（dsj_admin）；该卡片 v-if=\"isTenantAdmin\"",
     "1) 定位【运维与校准】卡片\n2) 核对四项统计、Worker 名与两个标签",
     "待处理（PENDING）=0；执行中（RUNNING）=0；已完成（DONE）=1836；失败（FAILED）=1445；\n"
     "文本「Worker：aioa-gitee-1」；标签【定时校准：开启】；标签【删除连仓：否】；【手动校准】按钮存在且可点。",
     "实测 GET /api/v1/gitee/tasks/stats → {PENDING:0, RUNNING:0, DONE:1836, FAILED:1445, worker:\"aioa-gitee-1\"}；"
     "定时校准/删除连仓取自 /gitee/config 的 syncEnabled=true、purgeRepoOnDelete=false",
     "未执行", "统计值与实测逐字一致，可直接作为预期"),

    ("GR-006", "项目与仓库", "反向", "★重点场景4澄清：【定时校准】是只读标签，不是开关",
     ENV,
     "1) 在【定时校准：开启】标签上尝试点击\n2) 在页面内查找是否存在定时校准的开关/切换控件",
     "该处为只读标签（el-tag）展示，**没有**开关控件；页面其他位置也没有定时校准开关。\n"
     "判定：若需求确为「可切换开关」→ 记功能缺口（需提需求）；若仅要求「查看状态」→ 符合实现。",
     "GiteeProjectsView L200-202 为 el-tag（只读）",
     "未执行", "★ 建议先与业务确认口径，再决定是否记缺陷"),

    ("GR-007", "项目与仓库", "正向", "手动校准可触发",
     "租户管理员登录",
     "1) 点【手动校准】按钮\n2) 观察提示\n3) 点【刷新】再看统计",
     "请求 POST /api/v1/gitee/calibrate；成功提示；返回体含 enqueued=<n>、scope=TENANT:2、"
     "note「校准任务已入队，由后台队列限速执行；可在任务统计中查看进度」。刷新后 PENDING 可能 >0，随后被 Worker 消费。",
     "GiteeController.calibrate L236-246：非平台管理员时 scope=本租户（TENANT:2）",
     "未执行", "平台管理员执行时为 ALL_TENANTS"),

    ("GR-008", "项目与仓库", "反向", "非租户管理员不得看到运维与校准，且接口 403",
     "用非租户管理员账号登录（如机构管理员 fagai_admin）",
     "1) 进入【项目与仓库】观察是否渲染【运维与校准】卡片\n2) 直接 GET /api/v1/gitee/tasks/stats",
     "① 界面**不渲染**【运维与校准】卡片；② 接口返回 403。",
     "模板 v-if=\"isTenantAdmin\"；GiteeController L226 guard.requireTenantAdmin()",
     "未执行", "—"),

    ("GR-009", "项目与仓库", "正向", "★重点场景5：项目列表按【归属部门】筛选",
     ENV,
     "1) 【项目列表】→【归属部门】下拉选「发展规划科（dept11-）」\n2) 点【查询】",
     "仅剩 departmentId=11 的项目（实测该部门下有「AIOA 个人令牌验证 1789636649」「AIOA 真机验证 1789630096」等）；"
     "部门下拉选项来自 GET /gitee/departments，受组织作用域限制，选项形如「名称（命名前缀）」。",
     "GiteeController.projects L253-257；实测 /gitee/departments 返回 部门10=办公室…部门16=综合科（机构1=发改局）",
     "未执行", "★ 你给的「发改局」是机构，仓库侧筛的粒度是「部门」"),

    ("GR-010", "项目与仓库", "正向", "★重点场景5：项目列表按仓库名 / 项目名称筛选",
     "接 GR-009",
     "1) 归属部门选「发展规划科（dept11-）」\n2) 关键字输入 fagai-project-ledger\n3) 点【查询】\n"
     "4) 关键字改为已存在项目的仓库名前缀（如 dept11-aioa）再查一次",
     "① 输入 fagai-project-ledger 时列表为空（实测库中不存在该仓库）；\n"
     "② 输入 dept11-aioa 时命中对应项目。\n"
     "关键字同时匹配「项目名称」与「仓库名」（输入框占位文案为「项目名称/仓库名」）。",
     "输入框占位文案 L241；后端按 departmentId + keyword 过滤",
     "未执行", "★ 当前库中无 fagai-project-ledger，先按 GR-012 建仓再复验"),

    ("GR-011", "项目与仓库", "反向", "关键字无匹配 → 空列表且页面不报错",
     "接 GR-010",
     "1) 关键字输入 zzz_not_exist\n2) 点【查询】\n3) 点【重置】",
     "① 列表为空，页面不报错、无未捕获异常；② 点【重置】后筛选条件清空并恢复全部列表。",
     "resetFilters；列表渲染 rows.length=0",
     "未执行", "—"),

    ("GR-012", "项目与仓库", "正向", "★重点场景1前置：新建仓库项目并观察「仓库名派生规则」",
     "已绑定个人 Gitee 账号 或 已完成企业 Gitee 初始化；已选出一个归属部门",
     "1) 【项目列表】点【新建项目】\n2) 项目名称填「发改局项目台账管理系统开发」\n"
     "3) 归属部门选「发展规划科」\n4) 可见性选私有\n5) 提交",
     "创建成功，列表新增一行。**关键**：仓库名（repoName）由平台按 `dept{部门ID}-{项目名 slug}` 派生，"
     "即形如 `dept11-…`，**不会**等于你提供的字面量 `fagai-project-ledger`。默认分支以建仓返回值为准（实测既有行为多为 master）。",
     "实测既有仓库 repoName 全部形如 dept10-e2e-2-… / dept11-aioa-…；命名由 GiteeNaming.repoPath 派生",
     "未执行", "★ 若必须叫 fagai-project-ledger，需把项目名设成可被 slug 的英文，或在 Gitee 侧重命名（平台不保证跟随）"),

    ("GR-013", "项目与仓库", "反向", "归属部门未选时不允许提交（或给出明确提示）",
     "在【新建项目】对话框内",
     "1) 不选归属部门\n2) 直接提交\n3) 记录实际表现",
     "前端拦截或后端返回明确错误提示（部门是仓库命名前缀 dept{id}- 的来源，缺失则无法派生仓库名）。\n"
     "记录实际行为即可；若静默成功并生成无前缀仓库名，记缺陷。",
     "仓库命名依赖 departmentId（dept{deptId}- 前缀）",
     "未执行", "该条为探索性用例，以实际表现为准"),

    ("GR-014", "项目与仓库", "正向", "项目详情：仓库信息与事件流",
     "列表中存在至少一个仓库项目",
     "1) 在【项目列表】对某项目点【详情】\n2) 逐页签浏览",
     "进入 /gitee/projects/{id}；展示仓库地址（httpUrl / sshUrl）、默认分支、可见性、状态、成员、"
     "分支 / 文件 / 提交 / 事件流等信息；页面文案的托管方名称随 provider 渲染。",
     "GiteeProjectDetailView.vue；实测列表项含 httpUrl/sshUrl/defaultBranch/visibility/status",
     "未执行", "—"),

    ("GR-015", "项目与仓库", "反向", "建仓失败必须留下可读原因 + 可重试",
     "库内已有 FAILED 行（实测 id=77「AIOA 个人令牌验证 1789636649」、id=69「AIOA 真机验证 1789630096」）",
     "1) 在【项目列表】找到状态=失败的记录\n2) 查看【失败原因】列\n3) 点【重试】",
     "① 列表在**存在 FAILED 行时**才显示【失败原因】列；\n"
     "② 失败原因文案完整可读，实测样例：「建仓已完成，但「配置 Webhook」这一步没成功，项目因此停在未就绪状态。"
     "当时的具体原因见任务队列中该项目的 Webhook 配置任务；点「重试建仓」可只重跑这一步。」\n"
     "③ 点【重试】只重跑失败的那一步（不重复建仓）。",
     "实测 GET /gitee/projects 返回的 errorMsg 与上述逐字一致；模板 v-if=\"hasFailed\" 控制该列",
     "未执行", "★ 这就是「每一步失败都要有终态」的正面样例"),

    ("GR-016", "项目与仓库", "正向", "企业初始化：先「校验配置」（只校验、不落库）",
     "租户管理员登录。测前记录当前 init_status=PENDING，便于用【撤销初始化】复原",
     "1) 【企业 Gitee 初始化】→【初始化】打开对话框\n2) 组织登录名填 fagai-org\n"
     "3) 访问令牌填 gitee-enterprise-token-202601\n4) 点【校验配置】",
     "逐步骤返回 7 步报告：GLOBAL_ENABLED → TENANT_ENABLED → TOKEN_FORMAT → ORG_FORMAT → "
     "TOKEN_VALID → ORG_ACCESSIBLE → PERSIST；**不写库**（复看 init_status 仍为 PENDING）。\n"
     "因该令牌是虚构值，预期在 TOKEN_VALID 或 ORG_ACCESSIBLE 步失败并给出原因。",
     "GiteeTenantInitService 7 步校验；POST /gitee/init/verify 永不写库",
     "未执行", "令牌格式校验正则 ^[A-Za-z0-9._\\-]{8,512}$"),

    ("GR-017", "项目与仓库", "反向", "组织登录名格式非法 → 前端就地拦截",
     "初始化对话框已打开",
     "1) 组织登录名输入「发改局 org」（含中文与空格）\n2) 观察表单提示\n3) 点【校验配置】",
     "表单下就地显示「格式错误：仅允许字母/数字/._-，长度 1-128」；点【校验配置】**不发请求**（控制台无网络请求）。",
     "ORG_NAME_RE = ^[A-Za-z0-9._-]{1,128}$；orgNameError computed 先于请求拦截",
     "未执行", "—"),

    ("GR-018", "项目与仓库", "反向", "访问令牌必填性由后端 tokenConfigured 决定",
     "当前 tokenConfigured=false（从未配置过企业令牌）",
     "1) 初始化对话框令牌留空\n2) 组织名填 fagai-org\n3) 点【校验配置】",
     "返回失败并在 TOKEN_FORMAT 步给出「请填写访问令牌」类原因（未配置过企业令牌时令牌必填）。",
     "前端 tokenRequired = !tokenConfigured；后端 TOKEN_PATTERN 校验",
     "未执行", "已配置过企业令牌时，留空=沿用旧令牌（rotateToken=false）"),

    ("GR-019", "项目与仓库", "正向", "用有效企业令牌完成初始化（**环境依赖，当前环境可能无法执行**）",
     "需要一个真实可用、且对目标组织有权限（含 projects 权限、账号为目标组织成员）的 Gitee 企业令牌；组织名需真实存在",
     "1) 初始化对话框填 组织登录名 + 访问令牌\n2) 点【立即初始化】",
     "7 步全部通过 → 状态标签变【已激活】（绿色 success）；【令牌所属账号】【令牌范围】【初始化时间】有值，"
     "【组织校验】= 已通过；按钮变【重新初始化】；出现【撤销初始化】按钮。此后建仓等写操作走**企业令牌**，不依赖个人 OAuth 绑定。",
     "GiteeTenantInitService.initialize；前端 initStatusLabel ACTIVE→「已激活」；"
     "GiteeTokenService.requireAccessToken 企业令牌兜底分支",
     "未执行", "★ 你给的 gitee-enterprise-token-202601 / fagai-org 是虚构值，在真实 Gitee 上必然失败；"
     "需替换为真实凭据，或改用桩（scripts/gitee_stub.py）"),

    ("GR-020", "项目与仓库", "正向", "撤销初始化",
     "GR-019 已完成（initialized=true）",
     "1) 点【撤销初始化】\n2) 确认\n3) 恢复后再次点【撤销初始化】",
     "① 首次：清空 access_token / token_owner / token_scope / org_verified，init_status 复位 PENDING，"
     "按钮回到【初始化】；② 再次点击：报「该企业尚未初始化 Gitee 令牌，无可撤销内容」。",
     "GiteeTenantInitService L125（提示语逐字来自源码）；DELETE /gitee/init",
     "未执行", "★ 本用例可用于恢复 GR-016 造成的影响"),

    ("GR-021", "项目与仓库", "反向", "个人账号绑定状态展示与解绑",
     ENV,
     "1) 观察【个人账号绑定】卡片\n2) 点【解绑】并确认\n3) 观察解绑后的形态",
     "① 已绑定时展示：头像、Gitee 账号、昵称、授权范围、绑定时间、最近刷新、令牌到期（过期时附「已过期（系统将自动刷新）」标签）、刷新令牌是否已保存；【解绑】按钮可用。\n"
     "② 解绑后转为未绑定态：提示「尚未绑定 Gitee 账号」+【绑定 Gitee 账号】按钮。",
     "实测 GET /gitee/bind → bound=true、giteeUsername=liu-yang20、giteeName=刘尖尖、hasRefreshToken=true、tokenExpired=false",
     "未执行", "★ 解绑会影响 GR-003 的分支走向，注意执行顺序"),

    ("GR-022", "项目与仓库", "反向", "「本企业 Gitee 组织」≠「企业令牌初始化」（两个独立配置面，勿混验）",
     ENV,
     "1) 观察【本企业 Gitee 组织】卡片\n2) 点【配置组织】\n3) 保存后观察提示",
     "该卡片展示：组织登录名=AI-OA、来源=企业自配置（success 标签）、启用状态；"
     "保存后若有可见性探测结果会以 warning 提示「组织校验未通过（不影响本次保存）：<原因>」。\n"
     "要点：它只决定「新建项目落在哪个组织下」，**不等于**企业令牌是否已初始化——两者独立判定、独立接口。",
     "实测 GET /gitee/tenant-config → orgName=AI-OA、source=TENANT、orgVerified=false、"
     "verifyMessage=「未提供操作人，跳过组织可见性校验」",
     "未执行", "★ 页面上两块卡片相邻，容易误判为同一件事"),
]
last3 = write_rows(ws3, 3, ROWS3, len(HEAD2), center_cols=(1, 2, 3, 9))
ws3.freeze_panes = "D3"
ws3.auto_filter.ref = f"A2:{get_column_letter(len(HEAD2))}{last3}"
ws3.conditional_formatting.add(
    f"C3:C{last3}", CellIsRule(operator="equal", formula=['"正向"'],
                             fill=PatternFill("solid", bgColor=XL_POS_BG), font=Font(color=XL_OK_FG)))
ws3.conditional_formatting.add(
    f"C3:C{last3}", CellIsRule(operator="equal", formula=['"反向"'],
                             fill=PatternFill("solid", bgColor=XL_WARN_BG), font=Font(color=XL_WARN_FG)))
for val, bg, fg in (("通过", XL_OK_BG, XL_OK_FG), ("失败", XL_BAD_BG, XL_BAD_FG),
                    ("阻塞", XL_WARN_BG, XL_WARN_FG), ("未执行", XL_GREY_BG, XL_GREY_FG)):
    ws3.conditional_formatting.add(
        f"I3:I{last3}", CellIsRule(operator="equal", formula=[f'"{val}"'],
                                 fill=PatternFill("solid", bgColor=bg), font=Font(color=fg)))
dv_scene3 = DataValidation(type="list", formula1='"正向,反向"', allow_blank=True)
ws3.add_data_validation(dv_scene3)
dv_scene3.add(f"C3:C{last3}")
dv_result3 = DataValidation(type="list", formula1='"未执行,通过,失败,阻塞"', allow_blank=True)
ws3.add_data_validation(dv_result3)
dv_result3.add(f"I3:I{last3}")
add_summary(ws3, last3 + 2, last3)

# ============================================================================
# Sheet 4：数据对齐说明
# ============================================================================
ws4 = wb.create_sheet("数据对齐说明")
HEAD4 = ["序号", "项", "你提供的数据 / 预期", "系统实测事实（判定依据）", "差异类型", "用例中的处理方式"]
W4 = [6, 22, 32, 58, 14, 40]
write_title(ws4, len(HEAD4), "★ 执行前必读：你提供的测试数据 与 系统实测事实 的对齐说明")
write_header(ws4, 2, HEAD4)
set_widths(ws4, W4)

ROWS4 = [
    ("项目状态枚举", "进行中 / 待启动 / 已完成 / 已终止",
     "实测枚举为 DRAFT(草稿) / ACTIVE(进行中) / SUSPENDED(暂停) / CLOSED(已结项) / ARCHIVED(已归档)。"
     "来源：GET /pm/config 的 statuses，与后端 PmProjectStatus 同源",
     "枚举不一致",
     "全部用例改用系统枚举；「待启动 / 已完成 / 已终止」在系统中不存在对应值"),
    ("测试项目2 的状态为「待启动」", "待启动",
     "后端创建项目时**恒**置 status=ACTIVE（进行中），且状态机 TRANSITIONS 中没有任何 →DRAFT 的迁移。"
     "即「草稿」状态在界面上不可达",
     "不可实现",
     "PM-005 的预期改为「进行中」；并新增 PM-015 记录该口径。若业务要求先草稿后提交，需另立需求"),
    ("成员 张三 / 李四 / 王五 / 赵六", "4 个虚拟人名",
     "租户 2 的真实用户为：李国强(dsj_admin)、王振华(fagai_admin)、刘敏(fagai_liu)、李思远(fagai_li)、"
     "陈静怡(fagai_chen)、吴俊杰(fagai_wu) 等；发改局=机构1（id=1，某某区发展和改革局）",
     "数据虚构",
     "用例改用真实在册员工（王振华/刘敏/李思远/陈静怡/吴俊杰）。注意「负责人」选的是机构在册员工，不是系统账号"),
    ("仓库名 fagai-project-ledger", "字面量仓库名",
     "仓库名由平台派生：`dept{部门ID}-{项目名 slug}`。实测库内既有仓库 repoName 全部形如 dept10-e2e-2-… / "
     "dept11-aioa-…；且当前库中**不存在** fagai-project-ledger",
     "生成规则不同",
     "场景1 需先按 GR-012 建仓，并以列表中的实际 repoName 为准；若要该名字需让项目名可被 slug 成它"),
    ("合同 HT-2026-001 / 收付款 64000+64000 / 里程碑", "具体合同与收付款数据",
     "【合同】页签为占位，文案「合同、收付款明细与里程碑随批次 4 交付」；pm_project 表也**没有**合同 / 收付款 / 里程碑字段",
     "功能未实现",
     "本版本无法验证。PM-022 按「占位即预期」断言，不记缺陷"),
    ("经费 128000 / 365000", "经费与实际发生额",
     "仅 pm_project.budget_amount（预算总额）已实现，可在新建时录入（UI 字段名「预算总额」，提示「元（计划值，实际发生额在「经费」页签维护）」）；"
     "「经费收支流水」在【经费】页签，属占位（批次 4）",
     "部分实现",
     "用例只验证「预算总额」字段；收支流水按 PM-022 占位断言"),
    ("文档", "项目文档",
     "【文档】页签为占位，文案「项目文档（企业级公共 / 项目专属文件夹）随批次 3 交付」",
     "功能未实现",
     "PM-022 按占位断言，不记缺陷"),
    ("负责人 admin", "负责人为 admin",
     "管理端登录账号为 dsj_admin（昵称李国强，租户管理员）；而「负责人」下拉取的是**机构在册员工**（org_employee，status=ACTIVE），与系统账号是两套主体",
     "主体不同",
     "登录用 dsj_admin / User@123；负责人选王振华等员工。PM-018 专门验在册约束"),
    ("登录租户名", "某某市某区大数据管理局",
     "实测租户名=「某某市某某区大数据管理局」（id=2）。机构1=某某区发展和改革局(ORG 代码 FAGAI 口径)",
     "名称略有差异",
     "用实测租户名登录，否则会因租户名校验失败而登录不了"),
    ("企业令牌 gitee-enterprise-token-202601 / 组织 fagai-org", "具体凭据",
     "虚构值，在真实 Gitee 上必然失败。实测当前 orgName=AI-OA、init_status=PENDING、tokenConfigured=false",
     "数据虚构",
     "GR-016 预期「校验失败」；GR-019 需替换真实凭据或改走桩环境（scripts/gitee_stub.py）"),
    ("运维统计 PENDING0/RUNNING0/DONE1836/FAILED1445/Worker aioa-gitee-1", "如上",
     "✅ 与 GET /api/v1/gitee/tasks/stats 实测**逐字一致**：{PENDING:0,RUNNING:0,DONE:1836,FAILED:1445,worker:\"aioa-gitee-1\"}",
     "无差异",
     "可直接作为 GR-005 的预期值使用"),
    ("定时校准开关", "可切换的开关",
     "实测该处为只读标签（el-tag）「定时校准：开启」，页面无开关控件",
     "交互形态不同",
     "GR-006 按「只读标签」断言并标注；若要求可切换，需先确认需求口径"),
    ("删除连仓 = 否", "否",
     "✅ /gitee/config 实测 purgeRepoOnDelete=false，页面标签显示「删除连仓：否」",
     "无差异",
     "可直接断言"),
    ("部门「发改局」", "发改局",
     "「发改局」是**机构**（机构1=某某区发展和改革局）；其下部门为 部门10 办公室 / 部门11 发展规划科 / 部门12 价格管理科 / "
     "部门13 收费管理室 / 部门14 综合收费组 / 部门15 项目审批科 / 部门16 综合科，命名前缀 dept10-…dept16-",
     "粒度不同",
     "【项目与仓库】筛选按「部门」而非「机构」，应选具体部门（如 发展规划科 dept11-）"),
    ("项目编号 PROJ-2026-001 / 002", "PROJ-…",
     "项目编号是自由文本（UI 占位示例为「如 PRJ-2026-001（企业内唯一）」），仅受唯一键 "
     "uk_pm_project_no(tenant_id, project_no, alive) 约束——注意前缀示例是 PRJ 而非 PROJ",
     "无实质差异",
     "用你提供的 PROJ-2026-001 / PROJ-2026-002 即可"),
    ("里程碑", "里程碑计划",
     "无独立里程碑实体；PM 详情页「合同」页签的占位文案里提到「合同、收付款明细与里程碑随批次 4 交付」",
     "功能未实现",
     "本版本无法验证，PM-022 按占位断言"),
    ("数据规模（列表分页）", "按筛选/分页浏览",
     "PM 列表与仓库列表均**无分页**：PM 返回全量数组；仓库侧返回 {items, total}，total=items.size。筛选为服务端过滤后整表返回",
     "环境事实",
     "用例不验证分页；数据量大时无分页属体验问题，不记缺陷"),
    ("执行环境", "—",
     "管理端 http://127.0.0.1:8080/aioa/web/ ；H5 http://127.0.0.1:8080/aioa/h5/ ；接口前缀 /api/v1；"
     "数据库 MySQL8 库名 aioa（root 无密码）；管理端账号 dsj_admin / User@123",
     "环境事实",
     "作为全部用例的统一前置条件（表中简写为「ENV」）"),
    ("已知失败数据（勿当缺陷）", "—",
     "仓库列表中存在历史 FAILED 行（id=77 AIOA 个人令牌验证、id=69 AIOA 真机验证），失败原因均为「配置 Webhook 这一步没成功」；"
     "失败原因文案本身是完整可读的（见 GR-015）",
     "环境事实",
     "GR-015 正是用这些行来验证「失败有终态 + 可重试」，不要把它们当成待修的缺陷"),
]
last4 = write_rows(ws4, 3, ROWS4, len(HEAD4), center_cols=(1, 5))
ws4.freeze_panes = "A3"
ws4.auto_filter.ref = f"A2:{get_column_letter(len(HEAD4))}{last4}"
ws4.conditional_formatting.add(
    f"E3:E{last4}", CellIsRule(operator="equal", formula=['"无差异"'],
                             fill=PatternFill("solid", bgColor=XL_OK_BG), font=Font(color=XL_OK_FG)))
ws4.conditional_formatting.add(
    f"E3:E{last4}", CellIsRule(operator="equal", formula=['"不可实现"'],
                             fill=PatternFill("solid", bgColor=XL_BAD_BG), font=Font(color=XL_BAD_FG)))
ws4.conditional_formatting.add(
    f"E3:E{last4}", CellIsRule(operator="equal", formula=['"功能未实现"'],
                             fill=PatternFill("solid", bgColor=XL_BAD_BG), font=Font(color=XL_BAD_FG)))
ws4.conditional_formatting.add(
    f"E3:E{last4}", CellIsRule(operator="equal", formula=['"数据虚构"'],
                             fill=PatternFill("solid", bgColor=XL_WARN_BG), font=Font(color=XL_WARN_FG)))
ws4.conditional_formatting.add(
    f"E3:E{last4}", CellIsRule(operator="equal", formula=['"枚举不一致"'],
                             fill=PatternFill("solid", bgColor=XL_WARN_BG), font=Font(color=XL_WARN_FG)))

OUT = "C:/Users/刘尖尖/WorkBuddy/aioa/docs/41-项目管理与项目仓库_手工功能测试用例.xlsx"
wb.save(OUT)
print("saved:", OUT)
print("sheets:", wb.sheetnames)
print("rows:", {"重点联动场景对照": last1, "项目管理用例": last2, "项目与仓库用例": last3, "数据对齐说明": last4})
