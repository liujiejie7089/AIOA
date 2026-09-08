# AIOA 设计文档 ↔ 运行代码 核对报告

- 生成日期：2026-09-07
- 核对方式：开发者交接包（README + 4 份 docx 设计文档）逐篇读取 + 当前仓库（C:\Users\刘尖尖\WorkBuddy\aioa）本地三端实测
- 结论等级：🔴 高（结构偏离）/ 🟡 中 / 🟢 低（已对齐）

---

## 0. 一句话结论

设计文档描述的是**地级市人工智能公共服务平台**的「市民/企业侧移动端小程序」（uni-app + AgentScope 2.0 Python 后端 + PostgreSQL），而当前仓库运行的是一套**内部 PC Web AI 工作台**（Vue3 微前端 + Java Spring Boot + MySQL）。

两者在**客户端形态、技术栈、架构形态、实体模型、交付形态**上均是**不同的实现**，属于「规格与代码严重偏离」。需尽快与左老师确认：当前仓库究竟是「管理端先行原型 / 早期 PoC」还是「技术栈已正式变更」——这决定了应「改代码对齐文档」还是「改文档反映现状」。

---

## 1. 本次实测：三端整体流程已跑通（代码本身可运行）

> 这一节证明"代码能跑"，问题在于"跑通的东西和文档说的不一样"。

| 端 | 地址 | 状态 |
|---|---|---|
| 前端（Vue3 微前端 shell） | :5173 | ✅ 200 |
| 后端（Spring Boot） | :8080 /actuator/health | ✅ 200 |
| Python Agent（FastAPI，echo SSE） | :8000 | ✅ 监听中 |

**登录链路实测**（admin / Admin@123）：
登录 → JWT 下发 → 跳转 `/home`，菜单正常渲染 **首页 / 我的应用 / 审批中心 / 知识库 / 系统管理** ✅

**本次修复记录（D2/D3 阻塞项已解决）**：
登录后曾一直卡在 `/login?redirect=/home`。根因 = 前端 `web/apps/shell/src/api/index.ts` 的 `unwrap` 只剥了 axios 信封，返回的是 `ApiResponse` 包装体 `{code,message,data}`，而 store 按内层读取 `result.accessToken`（得到 `undefined`）→ 把字符串 `"undefined"` 写进 `localStorage['aioa.token']` → 请求头变成 `Authorization: Bearer undefined` → `/api/v1/apps` 返回 401 → 响应拦截器清空 token 并跳回登录。
修复：让 `unwrap` 在 `body` 同时含 `code`+`data` 时再剥一层取 `body.data`。改后实测登录正常进入 `/home`，该 bug 在 `conversations`/`runs` 等同构接口亦一并修正。

---

## 2. 设计文档要点（"预期是什么"）

| 维度 | 设计文档规定 |
|---|---|
| 客户端 | **uni-app（Vue3+TS）**，微信小程序 + H5 + App 三端，**移动端优先**；管理/运营端用 Vue3+Element Plus+ECharts（PC Web） |
| 后端 | **AgentScope 2.0（Python）** 作 Agent Runtime 内核；FastAPI/Spring 渐进落地；**8 个微服务域独立部署** |
| 数据层 | **PostgreSQL**（主数据）+ 向量库（Milvus/pgvector）+ **Redis**（会话/配额）+ 对象存储 |
| 部署 | 政务云 K8s，信创（麒麟 OS + 国产 CPU），等保三级 |
| 总体架构 | 六横两纵；一套底座 + 四端（用户端/管理端/运营端/开放端） |
| 对象模型 | **五域 41 实体**；一期只交付 **P0 = 12 实体**（租户/个人/权限/会话/专家/技能/知识库/模型/词元/账本/支付/台账） |
| 需求 | P0：4 角色、6 步主链路（注册实名→工作台→会话→流式应答→结算留痕→额度用尽）、**31 条 FR**（FR-A~FR-H，M/O 分级） |
| Agent 运行时 | 感知-规划-执行-反思循环 + HITL 审批卡点 + 工具沙箱 + 三层记忆 + 全程追踪 |
| PoC | 2 周 PoC 验证 AgentScope 2.0 / HITL / 词元计量；超门禁 50% 触发选型复审（LangGraph 备选） |

---

## 3. 运行代码现状（"实际是什么"）

| 维度 | 运行代码（实测） |
|---|---|
| 客户端 | **Vue3 Web 微前端 shell**（`web/apps/shell`，:5173）+ 2 个 demo 子应用（demo-ticket 票务、demo-dispatch 统一调度）；非 uni-app、非移动端 |
| 后端 | **Java Spring Boot 3.x 单体**（`server/` 7 个 Maven 模块：common/security/admin/bridge/chat/tool-sdk/boot），单一可部署；非 Python、非 8 微服务域 |
| 数据层 | **MySQL 8**（本地，Flyway 初始化）；未发现 PostgreSQL / 向量库 / Redis 主存储（全仓 `postgresql` 命中 0 次） |
| 部署 | 本地开发态（pnpm dev / java -jar / uvicorn），非 K8s / 信创 |
| 架构 | 前端微前端（wujie/iframe 嵌子应用）+ 后端单体 + Vite 代理；"四端"未体现 |
| 实体/功能 | `app_registry`（应用注册：ticket/dispatch）、`admin/user`、RBAC（`ROLE_ADMIN`）、菜单树（首页/我的应用/审批中心/知识库/系统管理）；远小于 41 实体 |
| Agent 运行时 | FastAPI **echo SSE 桩**（:8000），未实现 感知-规划-执行-反思 / HITL / 记忆 / 追踪 |
| 需求覆盖 | 仅覆盖"管理端最小版"外壳（菜单、登录、应用列表、审批/知识库入口），**未覆盖 P0 移动端 31 条 FR** |

---

## 4. 差异对照表（结论性）

| 维度 | 设计文档 | 运行代码 | 偏离 |
|---|---|---|---|
| 客户端形态 | 移动端小程序（微信/H5/App） | PC Web 工作台 | 🔴 高 |
| 客户端框架 | uni-app | Vue3 微前端 | 🔴 高 |
| 后端语言 | Python（AgentScope 2.0） | Java（Spring Boot） | 🔴 高 |
| 后端形态 | 8 微服务域独立部署 | 单体（7 Maven 模块） | 🔴 高 |
| 数据库 | PostgreSQL + 向量 + Redis | MySQL 8 | 🔴 高 |
| 部署形态 | 政务云 K8s / 信创 | 本地开发态 | 🟡 中 |
| 对象模型 | 五域 41 实体（P0=12） | app/user/菜单 等少量 | 🔴 高 |
| Agent 运行时 | 完整感知-规划-执行-反思 | echo SSE 桩 | 🔴 高 |
| 需求口径 | P0 31 FR 移动端小程序 | 管理端外壳 | 🔴 高 |
| 鉴权/响应结构 | JWT + `{code,message,data}` + `/v1/` | 一致 ✅ | 🟢 低（已对齐） |
| 功能模块命名 | 审批中心 / 知识库 | 同名入口存在 | 🟢 低（部分对齐） |

---

## 5. 风险与建议

**风险**
1. **选型未走文档 PoC 门禁**：文档明确要求用 2 周 PoC 以真实数据定 AgentScope 2.0 选型；当前代码直接采用 Java 单体，与文档 PoC 结论机制冲突。
2. **交付形态不符验收口径**：一期验收门禁是"移动端小程序 P0 31 FR + 注册用户 1000+"，当前代码是 PC Web 工作台，无法按文档门禁验收。
3. **关键 P0 实体缺失**：账本 / 支付 / 词元计量 / 专家 / 技能等 P0 商业闭环实体均未落地，仅有应用注册与 admin/user。
4. **文档与代码"谁是真相"不清**：README 自称"本仓库承担一期客户端小程序研发"，但代码并非 uni-app，文档与代码来源不一致，易误导后续开发者。

**建议**
- **A（最高优先）**：立即与左老师/产品方确认当前仓库定位——是「管理端先行原型」还是「技术栈已变更」。据此决定 (1) 改代码对齐文档，或 (2) 改文档反映现状。
- **B**：若保留当前栈（Vue3 + Spring Boot + MySQL），应将设计文档降级为"长期蓝图"，并补一份《一期实际技术方案》说明偏离理由 + PoC 结论，否则与文档 PoC 门禁自相矛盾。
- **C**：补齐优先级 —— Agent Runtime（替换 echo 桩）> 词元计量/账本/支付（P0 商业闭环）> 41 实体映射 > 移动端（uni-app）或 PC Web 用户端。
- **D**：本次修复的登录 `unwrap` bug 应加回归测试与前端单测，避免同类"响应体多包一层"问题在 `conversations`/`runs` 等接口复现。

---

## 6. 附件与证据

- 实测截图：`ab_home.png`（登录后 `/home` 工作台）
- 浏览器登录 E2E：`e2e_browser_batch.json` / `e2e_verify.json`
- API 级全链路：`e2e_api.sh`（登录→me→menus→apps 全绿）
- 设计文档文本提取：`.docx_extract/*.txt`
- 修复点：`web/apps/shell/src/api/index.ts` 的 `unwrap`
