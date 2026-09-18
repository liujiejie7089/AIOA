# 支持不同企业创建不同的 Gitee —— 交付概览

> 编制：2026-09-16 · 迁移 **V50** · 验收：4 个套件全绿

## 1. 一句话结论

「每家企业（租户）各自使用一个 Gitee 组织」**已落地并验收通过**：租户可自配组织、未配置时**回落平台默认**，
两个租户的仓库在 Gitee 侧**确实落在不同 owner**（已对桩自身状态取证，非平台自证）。
存量数据、演示租户与既有 116 项 Gitee 套件**零回归**。

## 2. 关键决策（与您确认）

| 维度 | 决策 | 理由 |
|---|---|---|
| 隔离边界 | **按租户 `tenant_id`** | 与既有租户作用域、跨租户 404 口径完全一致；同租户各部门继续用 `dept<id>-` 仓库命名空间 |
| OAuth 应用 | **平台统一**（`clientId`/`clientSecret` 不按租户） | 企业零接入成本；`GiteeClient` 的 OAuth 方法与 `GiteeAccountService` **零改动** |
| 解析方式 | **租户覆盖 → 回落全局默认**（`aioa.gitee.org`） | 存量项目/演示租户/既有套件全部继续可用 |
| 存储 | 新表 `gitee_tenant_config`，`UNIQUE(tenant_id)` | 每租户单行 |

**回落 + 不播种是承重决策**：V50 **故意不为 tenant 9 播种**，因此「回落路径」被存量数据与既有套件**持续验证**；
若改成强制必填，所有存量项目会立刻变成迁移问题。

## 3. 改动清单

### 3.1 新增
| 文件 | 作用 |
|---|---|
| `db/migration/V50__gitee_tenant_org.sql` | `gitee_tenant_config`（`tenant_id` UNIQUE、`org_name`、`enabled`、审计四列；**无软删列**——租户单例表不需要） |
| `entity/GiteeTenantConfig.java` · `mapper/GiteeTenantConfigMapper.java` | 沿用 `GiteeTeam` 的注解与审计填充约定 |
| `service/GiteeTenantConfigService.java` | **org 解析唯一真源**：`effectiveOrg` / `orgConfigured` / `tenantEnabled` / `view` / `save` / `clear` |
| `scripts/e2e_v50_tenant_org.py` | 隔离回归套件 **54** 条（含桩控制段 T0） |
| `scripts/verify_v50_ui.py` | 三角色浏览器渲染校验 **28** 条 |
| 前端「本企业 Gitee 组织」卡片 | 生效组织 + 来源标签 + 配置/恢复默认（**仅租户管理员可见**） |

### 3.2 修改
| 文件 | 改动 |
|---|---|
| `service/GiteeProjectService.java` | 建项目/建团队的组织改走解析器；org 为空或租户被禁用 → **拒绝**，不静默落到共享组织 |
| `service/GiteeRepoTaskHandler.java` | 建仓按租户 org；**反转 webhook owner 优先级**（详见 §4） |
| `controller/GiteeController.java` | `config()` 改为租户感知；新增 `GET/POST/DELETE /api/v1/gitee/tenant-config`，租户管理员限本租户、平台管理员可 `?tenantId=` |
| `client/GiteeClient.java` | 新增 `getOrg(token, org)`，供**只读**可见性探测 |
| `scripts/gitee_stub.py` | 新增 `/_stub/deny-orgs` 控制端点（默认空） |

## 4. 顺带修掉的一个隐患（本次改造**才使它可达**）

`GiteeRepoTaskHandler` 解析 webhook owner 时原本**优先全局 `props.getOrg()`，压过项目行上存的 `giteeOwner`**。
组织一旦可按租户变更，给**旧项目**重配 webhook 就会指向**错误组织**。已反转优先级：**项目 stored `giteeOwner` 优先**，
仅在为空时回落解析器。

## 5. 验收结果（均为实跑，非静态推断）

| 套件 | 结果 | 意义 |
|---|---|---|
| `e2e_v50_tenant_org.py` | **54 / 54** | 新能力全链路 |
| `e2e_v48_gitee.py` | **116 / 116** | **向后兼容证明**：回落路径未破 |
| `e2e_full_system.py --no-browser` | **145 / 145** | 跨层无回归 |
| `verify_v50_ui.py` | **28 / 28** | 三角色页面真实渲染 |

**两个最有分量的断言：**
- **T3.5 隔离证明** —— 两个租户的仓库在**桩自身 state** 里落在不同 owner
  （`['aioa-tenant2-…', 'aioa-tenant9-…']`），检验的是 Gitee 侧事实，而不是平台把自己被告知的内容回显出来。
- **T9 禁用态语义** —— 租户被禁用时新建项目返回业务错误
  `本企业已关闭 Gitee 仓库联动，无法新建项目`，是**拒绝**，不是静默改用共享组织。

**鉴权口径（实测）：** 跨租户 → **404**「租户不存在或无权访问」（不泄露存在性）；同租户非管理员 → **403**。

## 6. 过程中查出并修掉的缺陷（测试照不到，靠代码审查发现）

`buildView` 用 `row != null` 判 `source`，而 `effectiveOrg` 用「行存在 **且** `enabled=1` **且** org 非空」——
两个谓词在 **`enabled=0`** 时漂移：`orgName` 已回落平台默认，`source` 仍报 `TENANT`
→ UI 渲染「企业自配置」却指向**共享**组织。修复方式是抽出 **`tenantSuppliesOrg()` 单一判定**供两条路径共用
（而非在展示层打补丁），并为其补上 **T9（10 条）**。

**根因类型值得记住**：*新增一个可配置维度，会造出旧状态机从未有过的组合*——此处即 `configured=true` + `enabled=0`。
不显式补断言，任何既有套件都照不到这类缺陷。

## 7. 遗留（非缺陷，已记入长期记忆）

`GET /gitee/tenant-config` 不带操作人 → 必然返回 `orgVerified=false` + 「未提供操作人」，
该字段**无法区分「未探测」与「探测失败」**。UI 只在**保存后**读取，无功能影响。
若将来要让 GET 也给出可信结论，需引入三态（`null` = 未探测）。

**本地无法证明的一点**：真实 Gitee 组织名能否解析，取决于平台 Gitee 账号是否为各企业组织的成员/所有者——
本环境用本地桩，只能证明代码路径正确。

## 8. 当前服务与复现

| 服务 | 地址 |
|---|---|
| 后端（含 V50） | `127.0.0.1:8080` |
| Gitee 桩 | `127.0.0.1:8090` |
| 管理端 | `http://localhost:5173/gitee/projects` |

复跑：`python scripts/e2e_v50_tenant_org.py` · `python scripts/verify_v50_ui.py`。
登录：`znkj_admin` / `User@123`（租户 9 管理员）· `znkjyf_admin` / `User@123`（企业管理员，应看不到组织卡片）。
