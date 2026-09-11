# AIOA V24 企业入驻 / 请假审批 E2E 验证报告

- 验证时间：2026-09-11 23:00 ~ 23:40
- 被测版本：后端 fat-jar（`aioa-boot-0.1.0-SNAPSHOT`），Flyway V1 ~ V26
- 结果：**209 / 209 全绿**（阶段一 114 + 阶段二 95），复位后第二轮复现同样全绿

---

## 一、套件与跑法

| 文件 | 说明 |
|---|---|
| `scripts/reset_v24_demo.py` | 演示数据复位，可重复执行；`--dry-run` 只看不动，`--keep-audit` 保留审计行 |
| `e2e_v24_onboarding.py` | 阶段一：租户端（FR-A~FR-F）+ 企业端（FR-G~FR-K）+ 机构硬隔离渗透 |
| `e2e_v24_leave_flow.py` | 阶段二：多级审批、请假校验、额度联动、入驻 8 步闭环 |

**固定顺序：`reset → 阶段一 → 阶段二`。** 阶段二依赖阶段一造出的机构、扩容单、资源开通单，单独跑会因找不到数据而失败。

```
C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/reset_v24_demo.py
C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe e2e_v24_onboarding.py
C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe e2e_v24_leave_flow.py
```

---

## 二、覆盖范围

**阶段一（114 项）** — 企业入驻 8 步闭环的租户端 1~4 步与企业端 5~8 步：

- FR-A 账户与登录安全（四类角色身份、范围纪律）
- FR-B 机构管理（新建 / 编辑 / 停用 / 恢复 / 注销 / 管理员交接）
- FR-C 资源池与四级配额链路（池扩容、超额护栏、冻结解冻、分配流水留痕）
- FR-D 费用分摊（规则版本、试算不落库、账单序时流水号、账本一致率 100%）
- FR-E 按机构授权与差异化计费倍率
- FR-F 租户级监控与两级审计
- FR-G 组织搭建（5 层部门树、500 人批量导入、失败逐行原因）
- FR-H 机构内额度二次分配与扩容申请
- FR-I 知识库可见范围与条目审核
- FR-J 授权资源可见性与资源开通申请
- FR-K 机构用量看板与机构审计
- **机构硬隔离渗透 10 项**：跨机构/跨租户越权访问全部 0 成功

**阶段二（95 项）**：

- 多级审批：逐级推进、阈值跳级（≤3 天跳过企业管理员）、驳回终止、重复审批幂等、非本节点审批人 403
- 请假校验：最长连续天数、提前申请天数、证明材料、余额不足、假种不存在、日期倒置
- 额度扣减：通过 `used += days / pending -= days`；驳回与撤销仅释放在途
- 业务联动：扩容审批通过 → 机构配额 120 万 → 150 万；资源开通审批通过 → 授权自动生效
- 入驻闭环：第 5~8 步门禁全部通过，一键推进 8/8，进度 100%

---

## 三、修复的 4 个真实缺陷

### 1. 审计哈希链整链误报断裂

`audit_log.created_at` 是 `DATETIME(6)`，早期代码用 `LocalDateTime.now()` 的 **9 位纳秒**参与哈希，回读只剩 6 位微秒，导致该批历史行的 hash 无法复算，整条链被判断裂。

- 写入前用 `microsNow()` 把时间戳截断到微秒，与 `DATETIME(6)` 精度对齐
- 新增 **V25** `hash_algo` 列：`V1` 历史遗留 / `V2` 当前算法。
  `verifyChain` 对 V1 行只做链式链接校验并把它当作信任锚，V2 行做「自哈希 + 链接」双重校验 —— 算法升级不再导致整链误报
- 响应新增 `verifiedRows` / `legacyRows`，可区分「真校验」与「靠锚定放行」
- **实测篡改检出**：改第 88 条 → `intact:false, brokenRecordId:88`；还原后恢复 `intact:true`

### 2. 租户管理员被挡在审批之外（二级审批事实上走不通）

`/workflow/tasks`、`decide`、`timeline` 使用 `requireOrgUser()`，而**额度扩容、资源开通的末级审批人正是 `TENANT_ADMIN`**。租户管理员不属于任何机构成员，因此全部 403 —— 既看不到待办也无法决策。

新增 `OrgGuard.requireApprover()`（机构成员 **或** 租户管理员）并替换三处入口。

### 3. 新机构无审批流定义时静默降级为单级审批

`QUOTA_EXPAND` / `RESOURCE_OPEN` 的流定义只配在机构 1。新机构查不到定义时，代码兜底成「单级 `ORG_ADMIN`」—— 意味着 **30 万词元扩容、模型资源开通只要企业管理员一人同意即生效，静默绕过租户管理员**。

新增 **V26**：为每个租户写入 `institution_id = 0` 的默认流。解析优先级：机构专属 > 租户默认 > 内置单级兜底。

### 4. 0 额度假种绕过余额校验，且可用天数变负数

`LeaveService` 的余额校验带 `quotaDaysPerYear > 0` 前置条件，事假（额度 0）因此完全不校验；同时对它仍累加 pending，返回 `availableAfterPending = -2`。

明确 `quotaTracked` 语义：不占额度的假种跳过 pending 累加，返回 `quotaTracked:false` / `availableAfterPending:null`，余额视图同步带 `quotaTracked`。

> **未改动策略口径**：事假 `quota = 0` 且 `status = ENABLED`，本意就是「不占额度、走审批」，因此保留「可申请」行为。若产品口径应为「事假需单独配额」，需另行确认。

---

## 四、审计链的处理口径

`audit_log` **全程不做任何 UPDATE**（改一行哈希链即断，不可篡改是设计约束）。

唯一例外：复位时**只删 `tenant_id = 2` 的演示审计行**。删除的是上一轮演示运行自己产生的审计数据，目的是让每轮 E2E 都从创世块开始，使 `verifiedRows == count` 是**真校验**而非靠遗留锚定放行。其他租户审计行一律保留，`--keep-audit` 可跳过该步。

当前状态：`{"intact": true, "count": 66, "verifiedRows": 66, "legacyRows": 0}`。

---

## 五、遗留观察（未擅自修改）

- `leave_type` 存在重复种子行（`ANNUAL`/`SICK`/`CASUAL` 各出现 2 次，分属不同租户）。当前按租户隔离读取未暴露问题，但建议确认是否为预期。
- 入驻第 5 步「组织搭建」的门禁未要求部门设置负责人。本次 E2E 显式设置了负责人才能跑通请假审批；若实际业务允许「无负责人部门」，则第一级审批会走 fallback（记录 `fallbackNote`，改由企业管理员审批），属可接受但建议提示。
