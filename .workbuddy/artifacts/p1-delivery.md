# P1 交付与验收报告

> 交付项：**P1-2 统一消息中心（多通道触达）** + **企业主动发起 Gitee 初始化（V51）**
> 验收环境：后端 :8080 / Gitee 桩 :8090 / Vite :5173 / H5 :5181，MySQL8 `aioa`
> 收口时间：2026-09-17

---

## 一、交付范围（如实说明）

| 子项 | 状态 | 说明 |
|---|---|---|
| P1-2 统一消息中心 | **完整交付** | 通道配置 / 投递记录 / 个人偏好 / 异步分发 + 前端消息中心页 |
| 企业主动发起 Gitee 初始化 | **完整交付** | V51：企业令牌、7 步硬校验、verify 诊断、撤销；前端向导 |
| P1-1 | 未开工 | 仅在设计文档 `docs/30` 中给出方案，未落代码 |
| P1-3 | 未开工 | 同上 |
| P1-4 | 未开工 | 同上 |

**为什么只做 P1-2**：P1 共 4 个子项，全量铺开会产生 4 套半成品子系统（每个都编译得过、但都没端到端跑通）。选择把 P1-2 做到底（含迁移、事件解耦、前后端、E2E 验收），其余如实标注未开工，而不是用「已设计」冒充「已交付」。

---

## 二、冻结契约

### 企业 Gitee 初始化（`/api/v1/gitee/init`，租户管理员）
| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/init` | 状态视图（不触发网络）；`initStatus` 恒为 `PENDING\|ACTIVE\|FAILED`，**无配置行也归一化 PENDING，不留 null** |
| POST | `/init/verify` | **诊断**：任一步失败仍 `HTTP200 + code=0`，回 `passed=false` + `failedStep` + 全量 `steps`；永不落库 |
| POST | `/init` | **动作**：失败即 `code≠0` 中止；已存在行仅标 `FAILED + last_error`，不动 `orgName/enabled/令牌` |
| DELETE | `/init` | 撤销令牌 → `PENDING`，保留 `orgName/enabled`；无可撤销内容报错 |

7 步校验顺序（冻结，测试依赖）：`GLOBAL_ENABLED → TENANT_ENABLED → TOKEN_FORMAT → ORG_FORMAT → TOKEN_VALID → ORG_ACCESSIBLE → PERSIST`。
**触发条件**：企业**主动发起**，非建租户自动初始化（`TenantProvisionedEvent` 无 Gitee 监听器，已核实）。

### 统一消息中心（`/api/v1/notifications`）
| 方法 | 路径 | 权限 |
|---|---|---|
| GET | `/channels` | 租户管理员 |
| PUT | `/channels/{code}` | 租户管理员；INAPP 不可配 |
| POST | `/channels/{code}/test` | 租户管理员 |
| GET | `/deliveries` | 租户管理员（`limit` 截断 ≤200，`total` 为真实计数） |
| POST | `/deliveries/{id}/retry` | 租户管理员；跨租户 → 404 |
| GET / PUT | `/preferences` | 本人 |

通道语义：INAPP 恒可用且不可配；EMAIL/SMS/PUSH 默认关闭，须管理员开启并填网关；**SMS/PUSH 数据模型未建模手机号/设备令牌 → 恒 `SKIPPED`（设计预期，非失败）**；EMAIL 取不到邮箱 → `SKIPPED`。

---

## 三、验收结果（全绿）

| 套件 | 结果 |
|---|---|
| `e2e_v51_gitee_init.py` | **49 / 49**（上一轮 PASS=4 / BLOCKED=41） |
| `e2e_v52_message_center.py` | **47 / 47**（新建） |
| `e2e_v48_gitee.py` | 116 / 116 |
| `e2e_v50_tenant_org.py` | 54 / 54 |
| `e2e_leave_flow_notify.py` | 19 / 19（**连跑两次**均绿） |
| `verify_v51_repo_urls.py` | 23 / 23 |
| `verify_v51_repo_urls_ui.py` | 18 / 18 |
| `verify_v50_ui.py` | 28 / 28 |
| `e2e_full_system.py --no-browser` | **145 / 145**（已知缺口 0 项） |
| 前端 `vue-tsc --noEmit` | EXIT=0 |
| 后端 `mvnw -DskipTests clean package` | EXIT=0（fat-jar 82.8 MB） |

Flyway：**V51 + V52 已应用**；二次重启确认 0 条重复迁移。

---

## 四、本轮发现并修复的缺陷（6 项代码 + 4 项测试 + 2 项类型）

### 代码缺陷
1. **`verify` 失败丢 steps**（`GiteeTenantInitService`）：原实现任一步失败即 `throw BizException`，前端只拿到一个字符串 message，**步骤明细随异常一起丢失**，向导无法渲染「卡在哪一步」。改为 `withReport()` 返回诊断报告（`code=0` + `passed` + `failedStep` + `steps`）；`check()` 由「内部抛异常」改为返回 `boolean`，调用点统一 `if (!check(...)) return steps;` 收口。
2. **`initStatus` 无配置行回 `null`**：契约改为恒 `PENDING|ACTIVE|FAILED`，前端不必为「未知状态」写兜底分支。
3. **`NotificationDispatcher` 未闭合的重复 Javadoc**：第 31–34 行 `/**` 缺 `*/`，把两段注释吞成一段（能编译，但是坏注释）。
4. **`NotificationDispatcher.selectPref` 用无 limit 的 `selectOne` 查 `type=NULL` 默认偏好行**：MySQL 唯一键**不约束 NULL**，一旦出现重复默认行，`TooManyResultsException` 会沿 `dispatch` 冒泡并被最外层 `try/catch` 吞掉 → **整轮分发静默中断（连 INAPP 投递记录都不写）**，现象是「通知有记录但无投递」。已加 `limit 1`。
5. **`NotificationPreferenceService.upsert` 同类问题**：默认行重复即接口永久 500。已加 `limit 1`（与 `GiteeTenantInitService.findRow` 同款写法）。
6. **`selectTenantAdminIds` 收件人角色硬编码 `ROLE_ADMIN`（真实功能缺陷，非本次新引入）**：
   - 证据：全库 `ROLE_ADMIN` 用户仅 1 个且挂在 **tenant 0**；tenant 2–9 的管理员角色均为 `ROLE_TENANT_ADMIN`。
   - 后果：叠加 `u.tenant_id = #{tenantId}` 后，**每个真实租户命中 0 人** → `ApprovalService` 的「新审批待处理」通知循环空转，**租户管理员从未收到过该通知**。
   - 修复：`role_code = 'ROLE_ADMIN'` → `IN ('ROLE_ADMIN','ROLE_TENANT_ADMIN')`，**纯增量**（保留 tenant 0 原行为，不摘任何既有收件人），与 `OrgGuard.requireApprover()`（TENANT_ADMIN + ROLE_ADMIN）口径一致。
   - 端到端验证：`fagai_li` 提交审批 → `dsj_admin` 收到「新审批待处理」（通知 id 2241，`refId`=619），且消息中心为其落了 `INAPP/SENT` 投递行。

### 测试缺陷（`e2e_v51_gitee_init.py`）
- **C5.1 是假断言**：`chk("C5.1 verify 失败输入仍 code=0", True, "")` 恒真 → 改为真正校验 `ok(d)`。
- **C5.2 放弃契约**：原「从 steps 推导 passed」→ 改为断言顶层 `passed is False`；新增 C5.5 断言 `failedStep` 与首个失败步一致。
- **C2.2/C2.3/C5 会误诊断**：原用例**不传令牌**，而校验顺序是 `TOKEN_FORMAT`(3) → `ORG_FORMAT`(4)，缺令牌会先卡在第 3 步，message 不可能回显 `bad/org` —— **解除阻塞后必红**。引入 `FMT_TOKEN` 占位令牌使失败点确定落在 `ORG_FORMAT`。
- **C1.2 断言被放宽**为 `∈{null,PENDING}` → 收紧为 `== "PENDING"`。
- 新增成功路径 C5.6–C5.8（`passed=true` / `verifyOnly=true` / 恰 6 步 / 不落库）。

### 前端类型漂移
- `ChannelInfo.config` 原为必填，但后端全局 `non_null` 策略在 `config` 为 null 时**省略该键**（实测 INAPP/未配置通道无 `config`）→ 改为可选 `config?`。
- `RetryResult` 原为 `{status,message}`，后端实际回 `{channelCode,status,message,sentAt}` → 补全。
- 另修正 `GiteeInitStatus.initialized` 的错误注释（原文「ACTIVE 或 FAILED 均为 true」，实际 FAILED 为 false）。

---

## 五、已知缺口（不掩盖、不用放宽断言绕过）

1. **真实网关 `SENT` 成功路径未实测**：EMAIL/SMS/PUSH 仅验证了「死网关 → `FAILED`」与「无收件地址 → `SKIPPED`」。证明真实可达网关能 `SENT` 需要可路由的测试网关。
2. **SMS/PUSH 恒 `SKIPPED`**：数据模型未建模手机号/设备令牌 —— 设计预期，且**如实记录而非静默成功**。
3. **`GET /deliveries?tenantId=<其它>` 跨租户读未单测**：仅验了 `/channels?tenantId=9`→404 与「跨租户重试」→404；`/deliveries` 走同一 `NotificationTenantGuard.resolveTenant()`，逻辑等价但未单独发请求。
4. **历史缺口 D-1～D-9 仍在**（无状态 JWT 无服务端吊销、路径参数类型不匹配 500、孤儿残留数据等），见 `docs/20`。
5. **P1-1 / P1-3 / P1-4 未开工**。

---

## 六、复现方式

```bash
# 起服务（幂等）
bash start-all.sh

# 回归
PY=C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe
$PY scripts/e2e_v51_gitee_init.py
$PY scripts/e2e_v52_message_center.py
$PY scripts/e2e_v48_gitee.py
$PY scripts/e2e_v50_tenant_org.py
$PY scripts/e2e_leave_flow_notify.py
$PY scripts/verify_v51_repo_urls.py
$PY scripts/e2e_full_system.py --no-browser
```

重打包（**必须先停 :8080**，否则 fat-jar 被改名成 20KB stripped-jar，运行中 JVM 崩）：

```bash
cd server && bash mvnw -DskipTests -q clean package
```
