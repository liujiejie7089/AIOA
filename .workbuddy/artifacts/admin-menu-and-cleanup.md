# 管理端菜单重构 · 侧栏滚动隔离 · 过程产物清理

> 2026-09-18 · 仓库 `C:/Users/刘尖尖/WorkBuddy/aioa` · 提交 `c212a87`
> 上一轮（Gitea 真机流程）交付档见 `overview.md` / `gitea-live-verification.md`

## 1. 一句话结论

三项要求全部落地并实测通过：**菜单按域分组重构**（21 个一级项 → 5 个一级项 + 6 个分组子菜单）、
**滑动菜单时右侧页面不再跟随滚动**（根因是 flex 高度链断裂，非 `overflow` 一处）、
**清理掉 75 个零引用文件**（70 张走查原图 + 5 个一次性脚本）。

> ⚠ **本轮发生一次误删事故并已完整恢复**（§4），恢复后所有套件复跑全绿。如实记录，供后续避坑。

---

## 2. 三项要求的落地

### 2.1 菜单按相近程度合并 / 增加子菜单

**改前**：21 个一级项 + 2 个子菜单平铺。实测菜单高 **1074px**（视口 720px），
最后一项「租户管理」在首屏完全不可见（`lastItem.visible=false`），必须整页滚动才能点到。

**改后**：收敛为 **5 个一级项 + 6 个按域分组的子菜单**。

| 层级 | 内容 |
|---|---|
| 一级平铺（高频，人人都有） | 首页 · 审批中心（保留待办红点）· 知识库 · 消息中心 · 我的应用（动态子菜单） |
| 一级平铺（高频管理） | 组织与员工 / 系统管理 |
| 子菜单「智能服务」 | 数字员工 · 专家配置 · 业务工具 · 业务系统 |
| 子菜单「成果与项目」 | 成果沉淀 · 项目与仓库 |
| 子菜单「运营管理」 | 经营数据 · 配额管理 |
| 子菜单「租户与机构」 | 机构管理 · 入驻进度 · 资源授权 · 费用分摊 |
| 子菜单「安全与治理」 | 审批流配置 · 操作审计 · 系统参数 · 审核记录 |
| 子菜单「平台管理」 | 内容审核 · 租户管理 |

**关键决策（为什么这样分组）**

1. **高频项不下沉**。审批中心、知识库、消息中心、组织与员工保持一级 —— 分组虽整齐，
   但把每天用的入口塞进「点两次才进」的子菜单是负优化。分组只施加在低频配置类页面上。
2. **分组的可见性 = 子项可见性的「或」**。每个子项仍**保留原有 `v-if` RBAC 守卫**
   （`showTenantMenu` / `showWorkerMenu` / `showExpertMenu` / `showReviewRecordMenu` /
   `showGiteeMenu` / `isPlatformAdmin`），分组只是容器，不引入新的权限口径。
3. **路由完全未改**。所有 `index` 仍是原路径，`router/index.ts` 一行未动 ——
   菜单 / 路由 `meta.allowRoles` / 后端 `PermissionCatalog` 三层同源不受影响
   （历史缺陷「菜单能进但接口 403」正源于三层漂移，这次刻意不碰）。
4. **深链要能展开**。分组后子项默认收起，从书签直接进 `/quotas` 会出现
   「菜单里一项都没高亮」。新增 `PATH_GROUP` 映射 + `initialOpenedGroups`，
   按落地路由展开所属分组；`/gitee/projects/:id`、`/app/:code` 按前缀归组；
   旧深链 `/admin` 继续归并高亮到合并入口。

### 2.2 滑动菜单时右侧页面保持固定

**根因（实测数据）**：不是 `overflow` 一处的问题，而是 **flex 高度链断裂**。

```
.layout-aside  实测 height=1074px   （视口 720px）
document       scrollHeight=1130  clientHeight=720  →  html/body 在滚
在左栏滚轮滚 400px  ⇒  document.scrollTop 0 → 400   （左栏 + 右侧一起被推走）
```

Element Plus 的 `.el-container` 是 `flex:1; flex-basis:auto`，而 flex 项默认
`min-height:auto` —— 内侧 flex 行被整棵菜单撑到 1074px 且**无法收缩**，
溢出 `.layout{height:100%}` 把文档撑高。此时 `.layout-aside{overflow:hidden}`
既是无效的（`scrollHeight == clientHeight`，没有内部可滚空间），
也挡不住溢出（`overflow` 只裁剪自己的盒子，管不了父级被撑高）。

**修法（4 处，缺一不可）**

```css
.layout        { overflow: hidden; }          /* 根布局不向外溢出 */
.layout-body   { flex: 1; min-height: 0; overflow: hidden; }  /* ← 关键：让 flex 行能收缩 */
.layout-aside  { overflow-x: hidden; overflow-y: auto; }       /* 菜单自己在右侧内部滚 */
.layout-menu   { min-height: 100%; }          /* 原 height:100% 会让菜单无法长高、无从滚动 */
```

（`.layout-body` 是给 `MainLayout.vue` 内侧 `el-container` 新加的类。）

**修后实测**：`document.scrollHeight == clientHeight == 720`；展开全部分组把菜单撑到
1488px 后在侧栏滚轮 400px ⇒ `aside.scrollTop 0→400`、**`main` 与 `document` 位移均为 0**；
反向滚右栏侧栏也不动。

### 2.3 清理无用测试文件 / 图片 / 文档

判定依据：**全仓跟踪文本文件的内容级检索**（不是凭文件名猜），加上 `.gitignore` 里
已写明的既有意图。

| 处置 | 对象 | 依据 |
|---|---|---|
| 删除（70 张图） | `ux-review/full-audit/*.png`（53）、`ux-review/admin-audit/*.png`（17） | 全仓检索**零引用**；`.gitignore` 原本就注明「walkthrough 原图不入库」（历史审计轮次的多角色整页截图，可由 `ux-review/walkthrough.py` 重新生成） |
| 保留 | 二者的 `report.json` / `menu-by-role.json` | 审计数据真源，体积小 |
| 删除（5 个脚本） | `_run_regression_v43.sh` · `_smoke_v43.py` · `diag_leave_notify.py` · `stat_org_hierarchy.py` · `_mk_gitee_logo.py` | 零引用 + 不在 `_run_all_regression.sh` 矩阵中；均为被取代的一次性件 |
| 保留 | `.workbuddy/artifacts/**` 全部 | 证据仓（报告按**目录**引用，如 `MEMORY.md` 引 `v50-ui/`），且系统约定为非缓存数据 |
| 保留 | `ux-review/batch1|2|3/*.png` | `.gitignore` 明确「批次改造证据截图……保留入库」 |
| 保留 | 全部 `_check_*.py` | `.gitignore` 刻意排除在忽略之外 —— 它们是要留的回归探针 |
| 新增忽略 | `ux-review/full-audit/*.png`、`ux-review/admin-audit/*.png`（并 `!` 白名单三个 json） | 防止再次误入库 |
| 顺带 | 清理 `scripts/__pycache__` | 字节码缓存 |

**刻意没删**（避免「为清理而清理」）：根目录三份交付报告（`AIOA_*.md`，体积 6–16KB，
属交付物而非过程产物）、`docs/**` 全部规格源、`logs/`（有进程在写）。

---

## 3. 验证

| 验证 | 结果 |
|---|---|
| **新增** `scripts/_check_menu_scroll.py`（27 项回归探针，已纳入 `_run_all_regression.sh`） | **27 / 27 PASS** |
| `e2e_full_system.py --no-browser` | **145 / 145**（已知缺口 0，与基线一致） |
| `e2e_v52_message_center.py` | **47 / 47** |
| `e2e_gitea_live.py` | **81 / 81** |
| `admin_v39_todo_badge.py`（审批中心红点） | **17 / 17** |
| `admin_v34_review_render.py` | **8 / 8** |
| `h5_v33_render.py` | **28 / 28** |
| `check_org_structure_render.py` | **ALL PASS** |
| `vue-tsc --noEmit` | **exit 0** |

新探针覆盖：高度链闭合（文档不出滚动条 + 侧栏高 = 视口 − 顶栏）· `overflow-y` 已放开 ·
展开后菜单确实超出侧栏（否则该段无从检验）· 滚左栏只有左栏动 · 滚右栏左栏不动 ·
6 条深链的分组默认展开与高亮 · 旧深链 `/admin` 归并 · 分组 RBAC 边界（租户管理员看不到「平台管理」）。

---

## 4. ⚠ 误删事故与完整恢复（如实记录）

### 4.1 事故

执行清理时用 `git rm -q -- 'ux-review/.../*.png' '...'` 之后，
**`scripts/` 与 `ux-review/` 两个目录被整体清空**（不只是命中的 png）：
- 被跟踪文件 72 个（全部 tracked 脚本 + ux-review 的脚本/HTML/batch 证据）
- **未跟踪文件**：`scripts/e2e_*.py` 全部回归套件（按仓库约定 gitignore，**不在 git 里**）、
  `ux-review/` 的 `zh-*/ad-*.png` 走查原图与 `before-fix/`、`after-fix/` 归档

> 触发命令的第二次调用被 SIGTERM 中断并留下 `index.lock`；
> 目录被整体删除的确切机制未能复现确认，因此**结论按「`git rm` 在本环境不可信」处理**。

### 4.2 恢复

| 步骤 | 手段 | 结果 |
|---|---|---|
| 1 | 移除 0 字节 `index.lock`，`git restore --worktree -- scripts ux-review` | 72 个被跟踪文件全部回来 |
| 2 | 从 `~/.workbuddy/projects/<conv>.jsonl`（含全部子代理记录）**重放 Write + Edit** | **51 个未跟踪文件还原**（24 个 e2e/校验套件 + 探针 + 诊断件） |
| 3 | 用 `~/.workbuddy/file-history/` 做**内容级校验** | 17/26 目标文件**逐字节一致**；其余经「最近版本比对」确认重建版本**更新**（历史库只留了旧版） |
| 4 | 跟踪文件以 git 为准 `git restore`（重放版本内容一致，仅行尾差异） | 工作区回到干净态 |
| 5 | 全量语法校验 + 套件复跑 | `py_compile` 全过；`e2e_full_system` 145/145、`e2e_v52` 47/47、`e2e_gitea_live` 81/81 |

**未能恢复**（均为 gitignore 的过程产物，可重新生成）：`ux-review/` 的 `zh-*/ad-*.png`
走查原图、`before-fix/`、`after-fix/`、`walkthrough.log`。
需要时重跑 `python ux-review/walkthrough.py`（截图目录用 `WALKTHROUGH_OUT` 指定）即可；
**已入库的交付物**（`用户体验走查报告.html`，12 张图 base64 自包含；batch1/2/3 证据图；两份审计 json）**完好**。

### 4.3 固化下来的纪律

1. **本环境不再使用 `git rm`**：改为 `rm 明确文件列表` + `git add`，每步后核对 `git status`。
2. **清理脚本一律走「先检索引用 → 再删」**，且**逐批小步**、每批后立即核对。
3. **未跟踪文件是唯一副本**：改动 `scripts/` 这类含 gitignore 文件（回归套件）的目录前，
   先确认可恢复来源（本仓的可行来源是 `~/.workbuddy/projects/*.jsonl` 与 `file-history/`）。
4. 误删后**先恢复、再验证、最后才继续**；恢复结果必须用实测（跑套件）而不是文件大小来判定。

---

## 5. 本轮收口

| 项 | 值 |
|---|---|
| 提交 | `c212a87` `feat(admin-shell): 管理端菜单按域分组重构 + 侧栏滚动隔离 + 过程产物清理` |
| 改动面 | 3 改（`MainLayout.vue`、`styles/index.css`、`.gitignore`、`_run_all_regression.sh`）· 1 增（`scripts/_check_menu_scroll.py`）· 75 删 |
| 推送 | GitHub `github/main`（校验 `git rev-parse HEAD` == `ls-remote`，不靠 push 返回码） |
| 运行态 | 后端 :8080 · agent :8000 · 管理端 :5173 · H5 :5181 均在监听 |
| 遗留 | ① 本环境禁用 `git rm`；② `ux-review/` 走查原图未重建（需要时按 §4.2 重跑）；③ 菜单分组后如需调整分组归属，改 `MainLayout.vue` 即可，**记得同步 `PATH_GROUP`** |
