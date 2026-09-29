# 已知缺口 / 判定「不改」的数据（原 MEMORY.md §4，2026-09-19 拆分）

- `docs/28` 是「未开工项」唯一进度权威，收口见其 §6。
- 已修：D-1 令牌吊销(V46) · D-2 路径参数类型(→400) · D-3 H5 待办 403 · D-4 favicon · D-8 新租户播种 · G-1 无负责人部门 · G-3 `duty_code`(27/116 → 116/116)。**当前缺口桶为空。**
- **判定「有效数据，不改」**：
  - D-5 / D-6 / D-7：tenant 4 假种被 17 条余额 + 35 条申请引用。
  - tenant 2 的 6 条越权部门**已软删** = 审计留痕。
  - G-2：tenant 9 重复昵称 = 同一 `sys_user` 兼多角色。
- ⇒ `e2e_full_system` 的 `GAP` 桶**当前为空**；**修好缺口后必须同步删/升分桶**。
- V50 遗留观察项（非缺陷）：`GET /gitee/tenant-config` 不带操作人 → 必回 `orgVerified=false` + `verifyMessage="未提供操作人"`；若要 GET 也给出可信结论需引入三态。

## 2026-09-28 已闭合：资源授权页的「知识库」类型无候选目录（**已修，登记撤销**）

- 原现象：`GET /api/v1/tenant/grants/catalog` **从不返回 `kb` 键** ⇒ 管理端「知识库」tab 与下拉
  恒空（能选、选项恒空），与「数字员工无法授权」同类症状、不同链路。
- **处置（2026-09-28 二批）**：`catalog()` 补下发 `kb`（`selectGrantableKb`：
  `tenant_id IN (0,本租户) AND institution_id = 0 AND scope = 'TENANT'`）；
  `grant/setEnabled/revoke` 对 `TYPE_KB` 同步 `kb_document.institution_id`（**生效态单一来源**）；
  并加**占用守卫**——资料已被别家机构挂载时直接 400，禁止「授权给 B 就把它从 A 静默搬走」。
- 钉住方式：`scripts/e2e_worker_grant.py` 的 `KNOWN_MISSING_CAT` 已清空为 `set()`，
  且 **A5b 反过来断言 `catalog.kb` 必须存在**（防回退）；另有
  `scripts/_check_scope_kb_guards.py`（K1–K12）+ `scripts/e2e_quota_kb_fix.py`（B/C 组）覆盖正负向。

## 2026-09-28 需求：删除的级联前置校验 + 逐级审核 —— ✅ **已实施**（同日）

用户原话（需求原文，勿改写）：
> 新增级联删除功能：删除部门前必须先删除该部门下的所有成员；删除机构前必须先删除该机构下的所有部门；
> 删除租户前必须先删除该租户下的所有部门。此外，任何一层级的首次删除操作都需要经过上一级审核后方可执行。

**状态**：**已实施并验证**（2026-09-28）。用户问「删除租户的功能怎么没有」后落地。

**实施结果（一句话）**：部门 / 机构 / 租户三层各配 `POST .../delete-request`（申请）→ 上一级审批 →
批准后才真删；三层的「直接删除」端点全部不存在（机构/租户原本**根本没有**删除功能）。
完整清单与证据见 `docs/38 §5.6`。

- **验证**：`scripts/e2e_cascade_delete.py` **76/76 连跑两次**（61 为原三组，下午补 [M] 员工直删组 13 条 + F10）；
  `scripts/_check_delete_guards.py` 正向 **12/12** + 自检 **35/35**（D12 见下）。
- **迁移**：V69（机构/租户删除流）+ V70（部门删除流）；`ApprovalFlowProvisioner.DEFAULTS` 4 → **7 条**。
  ⇒ `scripts/verify_v39_provisioner.py` 的期望值已改为 `len(DEFAULTS)` 推导（原来写死 4）。
- **顺带修的既有缺口**：`TenantController.create` 现在发布 `TenantProvisionedEvent`
  （否则「未入驻租户」一条审批流定义都没有，而删除租户的前提恰恰是未入驻 ⇒ 删除申请无从满足）。
- **层级边界（刻意的）**：门禁覆盖 部门/机构/租户 三层；**员工移除仍是直接操作**
  （需求第一句把员工列为「删部门的前置条件」，即由人先移除；员工是叶子、没有「级联」可言）。
  - **2026-09-28 下午已把这条从「说法」变成「事实 + 断言」**（用户追问「部门可直删员工，不需要上级审核，
    同时我没看到删除员工的地方」）：
    - 后端本就直接删（`DELETE /org/members/{id}`，全程不碰审批引擎），无需改动；
      唯一限制是 `is_org_admin=1` 的行拒绝删除（先交接，FR-B2）。
    - **真缺口是界面**：`api/org.ts` 有 `deleteMember()` 但**没有任何视图调用它** ⇒ 属于死代码，
      能力事实上不可用，而既有套件全绿（`e2e_member_accounts` 直接打接口、不经过界面）。
      已在 `OrgStructureView.vue` 名册行补「移除」按钮（企业管理员行禁用 + tooltip）。
    - 守卫新增 **D12**：直删端点仍在 / `deleteMember` 无审批调用 / 受审层级**恰为**三层 /
      播种器与迁移无 `MEMBER` 流 / **界面真的调用了 `deleteMember(`** / api 走 unwrap。
      自检 6 条突变，D12f 专打「api 函数还在但没人调用」。
    - 活断言（`e2e_cascade_delete.py` [M] 组）：直删成功、**一张审批单都不产生**、绑定被清、
      企业管理员被拒、跨机构 institutionId ⇒ 404。
- **已注意到、未动的可预期行为**：租户删除的前置校验统计**所有未软删**机构行（含 `CLOSED`）。
  演示库因 `e2e_v63_org_feedback.py` 刻意保留证据（只置 `CLOSED`、不软删）而累积约 27 家，
  故本库上删租户需先逐家删除 —— **数据卫生问题，不是代码缺陷**（否则会把机构行变成孤儿）。

**实施前的现状核对（保留，供追溯）**：
- `OrgTreeService.deleteMember`：**已**做「员工必须先移除」这一侧的约束不需要额外加，
  但**没有**反查「部门下还有成员时禁止删部门」；
- `deleteDepartment` / `deleteInstitution` / 租户删除（`AdminController` / `TenantController`）
  当时都是**直接删**（部门）或**根本不存在**（机构/租户），没有级联前置校验，也没有审核闸门；
- 「上一级」在本仓已有确定含义，可复用：员工 → 部门 → 机构 → 租户 四层，
  与 `docs/16 组织作用域` 一致；审批链路复用既有审批引擎
  （`ApprovalFlowService` + `ApproverResolver` 的 7 种策略族，见 `docs/23`），未新造审批表。

**当初的默认假设（实施时按此走，最终即按此落地）**：
1. 「级联删除」= **前置校验**（有下级就拒绝并给出停留在哪一级的明确文案），
   不是"自动连带删除" —— 因为自动连带会不可逆地抹掉审批/通知归属（铁律 #2）。
2. 「首次删除需上级审核」= 为该层级建一条审批单，**批准后**才真正删除；
   未获批准前对象保持原状（不得先软删、后补审批 —— 那是假成功）。
3. 每层级的「上一级」审批人 = 上述四层里紧邻的上一层管理员（员工→部门负责人/机构管理员，
   部门→机构管理员，机构→租户管理员，租户→平台管理员）。

**实施时补的断言（预判最易漏项，均已落地）**：
- 「部门下还有成员」与「机构下还有部门」两种**新增的可选性组合**各造了用例
  （铁律 #5；`e2e_cascade_delete.py` 的 A2/C2）；
- 审核被**驳回**后对象必须仍可读、可再次申请（`A6/A7/C6/C7`，不得静默变灰）；
- 审核**通过**后只删目标对象，不得连带删兄弟节点（每个用例都断言了「有下级的那家未被误伤」）；
- **新增**（预判之外、实施中发现必须补）：审批期间前置条件被破坏时**不得静默跳过删除**
  （`A10/C10` 的 TOCTOU 断言）——申请与批准之间可能隔很久，只信申请那一刻的结论
  会出现「批准的是空对象、删的是有下级的对象」。

## 2026-09-29 新发现（未修，待用户拍板）：审批人「待我审批」把**同一张单显示两遍**

**现象**：以 `wjj_admin`（`ROLE_TENANT_ADMIN`+`ROLE_ORG_ADMIN`，`canApprove=true`）登录，
用户端「待我审批」里同一张请假单出现 **2 行**（标题完全相同，id 相同）；待办**徽标数也被双计**。

**根因**（已定位到行号）：`user-client/index.html` 的 `loadTodoApprovals()` **无条件合并两条引擎**：
```js
if(state.canApprove){ merged.push.apply(merged, tagSource(await API.workflowTodo(), 'workflow')); }
if(state.isAdmin){    merged.push.apply(merged, tagSource(await API.approvalList('todo'), 'legacy')); }
return merged;   // ← 无去重
```
而请假链路会**同时**在两条引擎登记同一 `orderId`。取证（`scripts/_probe_engine_dupes.py` 一次性探针，
2026-09-29 实测）：
- 新单 `orderId=912`（`leaveRequestId=176`，事假，`nodeCount=2`）
- `API.workflowTodo()` → `[{id:912, st:PENDING}]`
- `API.approvalList('todo')` → `[{id:912, st:PENDING}]`
- ⇒ `state.todoApprovals` = `[{id:912,src:'workflow'},{id:912,src:'legacy'}]`（**同 id 两行**）

**影响面**：这是**共用的经典加载器**，**经典形态与 OA 形态都一样**出现双行；
且 `index.html` L2271 `pendingTasks = asArray(state.todoApprovals).filter(a=>a.status==='PENDING')`
会把徽标数**双计**（1 张单 → 徽标 2）。决策本身不受影响（点第一行能正常通过，决策后两行一起消失，
因为两引擎都转终态）。

**为什么不擅自修**：改 `loadTodoApprovals` 会同时改到经典形态，而按本机现状**大部分经典套件不可运行**
（见 `e2e-suites.md §5.3`），无法证明非回归；且 `admin_v39_todo_badge.py` 等断言依赖待办计数。
⇒ 记入台账，**等用户决定**（推荐修法：按 `id` 去重，`workflow` 优先、保留 `legacy` 仅当 `id` 不在集合内；
或改在后端让两条引擎的待办集互斥）。

**复现（两分钟，零额度成本）**：以 `wjj_xu` 调
`API.leaveSubmit({leaveTypeCode:'CASUAL',startDate:'2026-10-07',endDate:'2026-10-08',reason:'x'})`
（事假 `quotaDaysPerYear=0` ⇒ **不消耗额度**），再以 `wjj_admin` 看「待我审批」。
