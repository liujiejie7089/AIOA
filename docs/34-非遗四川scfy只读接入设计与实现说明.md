# 34 · 非遗四川 2023（scfy）只读接入设计与实现说明

> 对象：`server/aioa-integration-scfy`（独立模块，3406 行，含测试）。
> 状态：**查询能力已完成并在生产全量实测通过**（55 个查询工具，54 个返回数据、1 个实测恒空）。
> 写操作（增删改）本阶段一律不做；需登录接口等后台测试服务提供账号后再评估。

---

## 1. 本阶段的硬约束

用户给定的三条约束，直接决定了所有设计取舍：

| 约束 | 落点（不是注释，是代码结构） |
|---|---|
| 只能查询，禁止增删改 | `ScfyClient` **只暴露 `get(...)`，不存在任何写方法**。约束落在类型系统里，而不是「记得别调」 |
| 不确定内容的都废弃 | 不可用/不确定的 12 个接口登记进 `ScfyCatalog` 并**写明废弃原因**，不注册工具、调用即抛 |
| 等级枚举包含联合国级 | `ScfyEnums.LEVELS = [un, country, province, city, county]`，`un` 保留 |

另外两条来自项目铁律：
- **展示必须与事实同源**：同一决策只在一处判定。接口清单只存在于 `ScfyCatalog`。
- **管理端配置页 = 能力的唯一入口**：目前开关只在 `application.yml`（见 §7 未闭环项）。

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 语言/运行时 | Java 21 | 与基座一致（`server/pom.xml` → `<java.version>21</java.version>`） |
| 框架 | Spring Boot 3.3.5，但**只依赖 `spring-boot-autoconfigure`** | 适配器不做 Controller、不占端口，不引 `starter-web` |
| 装配 | `@ConfigurationProperties` + `@ConditionalOnProperty` | 开关式装配，见 §5 |
| HTTP 客户端 | **JDK 内置 `java.net.http.HttpClient`，固定 HTTP/1.1** | 刻意不引第三方客户端。与 `common/http/AgentHttpClient` 同口径，避开明文目标 H2C 升级导致的 `upstream connect failed`（本机已踩过） |
| JSON | Jackson（`ObjectMapper` / `JsonNode`） | 解析后立刻转成普通 `Map/List`，**不把 Jackson 类型泄漏**到工具层与审计层 |
| 加解密 | JDK `javax.crypto`（AES/ECB/PKCS5Padding） | 仅用于登录密码，见 §3.3 |
| 测试 | JUnit 5 + `spring-boot-starter-test` | 离线单测 + 可选的真实出网矩阵 |

依赖方向：`aioa-integration-scfy → aioa-tool-sdk + aioa-common`。**不反向依赖基座业务模块。**

---

## 3. 接口对接方式

### 3.1 对方的接入特征（决定我们必须自建适配器）

被接入系统是 Spring Boot + Shiro + JWT + Redis。它与基座现有出网通道不兼容：

| 特征 | 基座 `ToolDispatcher` 的能力 | 结论 |
|---|---|---|
| 鉴权头是自定义 `token: <jwt>` | 只支持标准 `BASIC` / `Bearer` | 不支持 |
| 登录密码需 AES/ECB/PKCS5Padding 加密后提交 | 无加密能力 | 不支持 |
| Token 在**每个响应头**里返回新值，需读取并替换（续期） | 无续期机制 | 不支持 |

所以 `ToolDispatcher` 无法直连，**自建 `ScfyClient` 是必需的**，而不是重复造轮子。这三件事全部收在 `ScfyClient` 内部，换版本/换环境不外溢。

### 3.2 免登录查询通道（本阶段全部能力走这里）

- 上下文路径 `/scfy`，查询接口前缀 `/show/*`。
- **`/show/*` 免登录**：生产与本地测试服务实测一致 —— 不带 token 直接可达业务逻辑（本地测试服务返回的是数据库错误，不是 401，证明已越过鉴权）。
- 实测确认后**可用环境**：
  | 环境 | 地址 | 实测结论 |
  |---|---|---|
  | 生产（西昌） | `https://szbhpt.tsichuan.com/scfy` | 55 个查询接口全部实测通过，本模块默认指向这里 |
  | 本机后台测试服务 | `http://127.0.0.1:16060/scfy` | 服务已起、`/show/*` 同样免登录；**但其数据源取不到连接**，见 §6.4 |

### 3.3 需登录通道（预留，本阶段关闭）

`login-enabled: false` 为默认。置 `true` 时**必须同时提供 username/password，否则启动即失败** —— 不允许静默降级成匿名，那会让需登录接口以 401 伪装成「没有数据」。登录路径 `/sso/shiro/ajaxLogin`（已实测可达，空参会返回「登录账号不能为空！」）。

### 3.4 文档与实测不一致的处理

接口文档（`AI接入接口文档.md`，833 行）与生产实测存在系统性差异：**参数名错、必填漏标、返回结构过简**。这不是靠注释提醒能解决的，所以设计为：

- `ScfyEndpoint` / `ScfyParam` 是「文档 + 实测」**合并后**的契约，凡冲突一律以实测为准；
- 冲突内容存进 `docNote` **字段（是数据，不是注释）**，被三处消费：
  1. 工具 `description`（模型能看到，避免照文档写错参数）；
  2. 工具返回体的 `docMismatch`（调用方能追溯）；
  3. 审计日志（运维能追）。

---

## 4. 模块划分

```
server/aioa-integration-scfy/
├── ScfyIntegrationProperties.java   配置（开关 / 地址 / 超时 / 重试 / 登录）
├── ScfyAutoConfiguration.java        装配 + 启动自检（契约覆盖核对）
├── contract/                         契约层：唯一事实源
│   ├── ScfyCatalog.java     (409)    67 个接口清单（55 可用 + 12 废弃含原因）
│   ├── ScfyEndpoint.java             一个接口：id/分组/路径/摘要/参数/状态/说明
│   └── ScfyParam.java                一个参数：名/必填/类型/说明/枚举/示例/docNote
├── core/
│   └── ScfyEnums.java                枚举常量：五档等级（含 un）、21 个市州简称、十大类
├── adapter/                          协议适配层：唯一与对方通信的地方
│   ├── ScfyClient.java      (339)    只发 GET；token 续期；限长读取；重试
│   ├── ScfyResponse.java             归一化响应：httpStatus/code/message/data/耗时/截断
│   └── JsonNodes.java                JsonNode → Map/List，隔离 Jackson
├── validate/
│   └── ScfyParamValidator.java (213) 出网前校验：未知参数/必填/枚举/类型/静默失效
└── tools/                            工具层：模型看到的能力
    ├── ScfyToolSupport.java  (175)   统一执行路径：查契约→校验→调用→裁剪→组装结果
    ├── ScfyArgs.java                 入参装配（丢弃 null：空值 ≠ 不筛选）
    └── Scfy*Tools.java ×5    (774)   9+8+13+11+14 = 55 个 @AioaTool
```

各层职责边界与「为什么这样切」：

| 层 | 只做 | 不做什么 |
|---|---|---|
| `contract` | 声明接口与参数 | 不发请求、不做校验 |
| `adapter` | 协议、鉴权、解析、重试 | 不懂业务语义、不做校验 |
| `validate` | 判定「会不会静默出错」 | 不调用、不知道响应结构 |
| `tools` | 声明能力 + 组装结果 | 不各自实现失败语义（统一走 `ScfyToolSupport`） |

**为什么工具层必须收成一条路径**：55 个工具若各自实现「调用 + 错误处理」，就会漂移出 55 种失败语义。收进 `ScfyToolSupport.call()` 后，失败永远是同一个结构化形状。

---

## 5. 可插拔设计

### 5.1 开关式装配

```java
@Configuration
@EnableConfigurationProperties(ScfyIntegrationProperties.class)
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyAutoConfiguration { ... }
```

```yaml
aioa.integration.scfy:
  enabled: ${AIOA_SCFY_ENABLED:false}     # 默认关
```

| 状态 | 后果 |
|---|---|
| `enabled=false`（默认） | 不建任何 Bean、不注册任何工具、不出现在模型能力清单里、不产生任何连接。等价于这段代码不存在 |
| `enabled=true` | 注册 55 个工具 + 启动自检 |

每个 `@AioaTool` 方法上也带同样的 `@ConditionalOnProperty`，防止有人只加了装配类。

### 5.2 启动自检：把「两份文本必然漂移」变成启动即失败

`@AioaTool(code=...)` 是编译期注解，**无法引用运行时的 `ScfyCatalog`** —— 所以「接口清单」和「工具声明」必然存在两份文本。设计上不消除重复，而是**让不一致立刻暴露**：

- `ScfyCatalogConsistencyChecker`（启动时反射扫描所有 `scfy_*` 工具）：
  - 工具指向了不存在的接口 / 已废弃接口 → **抛异常，启动失败**；
  - 接口有工具没实现 → 仅告警（可能是刻意只接一部分）。
- `ScfyContractTest` 把同一件事在测试里再判一遍（含参数名与必填性逐项对齐、每个可用接口有且仅有一个工具）。

### 5.3 只读也是可插拔的一部分

`enabled=false` 之外，第二道防线是类型系统：`ScfyClient` 没有 `post/put/delete`。即便未来有人想加写能力，也必须先改适配器接口 —— 这是一次**显式的代码评审动作**，不会被顺手带进来。

---

## 6. 查询功能的输入 / 输出与异常处理

### 6.1 输入：模型看到的是注解推导的 Schema

工具用基座 SDK 声明，`inputSchema` 由注解自动推导，**不手写 JSON Schema**：

```java
@AioaTool(code = "scfy_shop_detail", name = "非遗工坊-详情",
        description = "查询单个工坊/店铺详情。参数名是 id，不是文档里的 shopId。",
        domain = "scfy", riskLevel = "LOW", owner = "integration")
public Map<String, Object> detail(
        @AioaToolParam(name = "cityName", description = "市州简称（如 成都市，不能用全称）", required = true) String cityName,
        @AioaToolParam(name = "id", description = "工坊 id，取自 scfy_shop_table 的 list[].id", required = true) String id) {
    return support.call("shop_detail", ScfyArgs.of("cityName", cityName, "id", id));
}
```

入参三条纪律：
1. **参数名以实测为准**：文档写 `shopId`、实测是 `id`，契约与注解都写 `id`；
2. **`ScfyArgs.of(...)` 丢弃 null 值**：URL 里不出现 `&area=`。后端对空值的处理是「按空串过滤」而非「不筛选」，会静默返回错误结果；
3. **中文取值必须用简称**：`area=甘孜州` → 291 条；`area=甘孜藏族自治州`（文档示例）→ 0 条且不报错。

### 6.2 输出：统一的信封，失败也是结构化数据

`ScfyToolSupport.call()` 的返回恒为 `Map`，关键字段：

| 字段 | 含义 |
|---|---|
| `ok` | 本次调用是否成功（校验通过且对方 code=0） |
| `data` | 业务数据（已转成普通 Map/List） |
| `endpoint` / `source` | 这条结论来自哪个接口 —— 审计可追溯 |
| `errors` | 失败原因（人类可读，含对方的原始 message） |
| `needUserInput` + `askUser` | 缺必填参数时**向用户追问的话术**（说清要什么+给可选项+不替用户默认） |
| `warnings` | 「这次调用成功了，但某个条件没生效」 |
| `truncated` / `truncatedField` / `totalItems` / `returnedItems` | 条目裁剪（上限 50 条）与真实总数 |
| `responseTruncated` | 响应体触发字节上限（与条目裁剪是两件事，分别标注） |
| `docMismatch` | 该接口有哪些「文档与实测不符」的历史 |

两条关键设计：
- **不静默截断**：工坊地图分布一次返回 35 条、传承人列表全省 1821 条。裁剪时必须带 `truncated=true` 和真实总数，否则模型会把「前 50 条」当成全部。
- **失败不抛异常给模型**：抛异常模型只能看到「调用失败」四个字，然后开始瞎试。必须回可读原因 + 下一步建议。

### 6.3 异常处理：四类失败，四种不同的处理

| 类型 | 例子 | 处理方式 |
|---|---|---|
| **① 参数类（出网前拦下）** | 未知参数名、必填缺失、枚举越界、类型/范围错 | `ScfyParamValidator` 在**发出请求之前**拦住，返回 `errors` 或 `askUser`。理由见下 |
| **② 静默失效类（预警但不拦）** | `level=province` 实测不生效、仍返回未过滤结果 | 放行但附 `warnings`，明确告知「这个条件不会被采纳」 |
| **③ 网络/5xx 类（可重试）** | 连接超时、上游 5xx | 按 `max-attempts` 重试，退避 `300ms × 2^(n-1)`；**参数类错误（`is not present`）与业务错误绝不重试** —— 重试只是把同一个错误再犯一遍 |
| **④ 业务类（不重试，转成可读原因）** | 对方 `code != 0`、响应非 JSON、响应被截断 | 归一化成 `ScfyResponse.reason()`，返回 `ok=false` + `httpStatus` + `code` + 原因 |

**为什么①必须在出网前拦**：对方有一类危险行为 —— 参数错了不报错，而是返回空集或未过滤结果。实测已确认三例：

| 现象 | 后果 |
|---|---|
| `area=甘孜藏族自治州`（文档给的全称）→ 返回 0 条，HTTP 200 / code=0 | 模型会把「查不到」当事实回答用户 |
| `level=un` → 返回未过滤的全省数据 | 用户以为筛过了 |
| `area=青羊区`（行政区划编码类参数传了名称）→ 返回全零 | 同上 |

**错误会伪装成结论** —— 这是本模块校验器存在的原因。所以它校验的不是「合不合法」，而是「会不会静默出错」；宁可拦下并要求澄清，也不放行一个注定产生假结论的请求。

对应地，行政区划编码类参数用 `type="areaCode"` 做格式校验（必须 12 位数字），而不是臆造枚举 —— 枚举只登记**实测确认可用**的取值，防止把合法调用拦死（这正是本轮修掉的一个缺陷，见 §6.5）。

### 6.4 目标系统侧的缺陷（不是我们改的范围）

| 缺陷 | 证据 | 我们的处置 |
|---|---|---|
| `/show/data/*` 全组 8 个接口生产 code=500 | `relation "t_shop" does not exist`（人大金仓 Kingbase8），已用真实工坊 id=140 复测仍 500 | 整组登记为废弃，写明原因 |
| `/show/ecologicalArea/getPagerTravelImageUrl` | 只返回 `{pager:{...}}`，**没有任何数据列表字段** | 废弃 |
| `/show/ecologicalArea/getEcologicalAreaImageUrl` | `type` 语义未明确，且错配即 500（`Incorrect result size: expected 1, actual 0`） | 废弃，图片需求由 `eco_all_image` / `eco_details` 覆盖 |
| **本机测试服务数据源不可用** | 任意 `/show/*` 等待约 20s 后返回 `code=500 Could not open JDBC Connection ... GetConnectionTimeoutException (wait millis 10000, active 0, maxActive 20, creating 0)` | 已记录在 `application.yml`；**库修好前切 base-url 无意义**，故默认仍指生产 |

`/show/shopv2/*` 两个接口：文档只说「与 v1 结构相同，作为 v2 版本」，未说明 v1 是否下线 —— 按「不确定即废弃」处理，只接 v1 一套，避免同一数据两条工具路径。

### 6.5 本轮由矩阵实测暴露并修掉的契约缺陷

端到端矩阵（§7）把「只测过 6 个点」变成「55 个点全测」，第一次跑就打出 5 处契约错误：

| 接口 | 原契约 | 实测 | 修正 |
|---|---|---|---|
| `eco/travel_tourist_county_data` | `area` = 市州简称（枚举 21 个市州） | 简称 → **全零**；12 位行政区划编码（`510105000000`=青羊区）→ 真实数据 | 改为 `areaCode` 类型，格式校验 12 位，并说明编码来源 |
| `travel_image` | `type` 可选、无枚举 | 不传或传 1/4/5 → **空**；2=项目图片(155 条)、3=体验基地图片(9 条) | `type` 改必填 + 枚举 `[2,3]` |
| `travel_road_detail` | `dataId` 无说明 | 必须是列表返回的 `project_base_id`；传不存在的 id 返回 `{}` 且 code=0 | 补 `dataId` 来源与「空 ≠ 没有详情」 |
| `eco_details` / `travel_details` | `type` 无说明 | `type=1/5` 有数据、`2/3/4` 返回空对象 | 补说明（不臆造枚举） |
| `eco_area_image` | 可用 | `type` 错配即 500，语义未明 | 废弃，改写替代路径 |

第一次跑还报出 2 个 FAIL，追查后确认是**矩阵自身的参数错**（用了区县名），而不是接口不可用 —— 校验器在出网前拦住，正是它该做的。这条经验写进了 `ScfyParamValidator` 的注释：**报「对方有问题」之前先证伪自己**。

---

## 7. 验证方式（可复跑）

| 层次 | 命令 | 结果 |
|---|---|---|
| 离线单测 | `cd server && ./mvnw -pl aioa-integration-scfy -am test` | 契约 4/4 + 校验器 8/8 = **12/12 通过** |
| 端到端矩阵（真实出网） | `./mvnw -pl aioa-integration-scfy -am test -Dtest=ScfyMatrixTest -Dsurefire.failIfNoSpecifiedTests=false -Dscfy.matrix=true` | **55/55 全部覆盖：54 有数据、1 空集（`eco_nmch_base`，实测该前缀恒空并已在工具描述里注明）、0 失败** |
| 打本地测试服务 | 上条命令追加 `-Dscfy.baseUrl=http://127.0.0.1:16060/scfy` | 待其数据源恢复后复跑 |

矩阵的两条纪律：
- **覆盖数本身是断言**：`探到的接口数 == 契约可用接口数`，少一个就是「有一个接口从未被验证过却已对外可用」；
- **不为转绿而放宽**：矩阵只断言确定性事实（覆盖完整、参数名与契约一致、必填齐备），失败项如实落进报告 `docs/_incoming/非遗scfy-端到端矩阵报告.md`，不写成断言让它「看起来是绿的」。

---

## 8. 未闭环项

1. **管理端配置页**：按项目铁律「管理端配置页 = 能力的唯一入口」，引擎支持但配不出来 = 能力事实上不可用。目前开关只在 `application.yml` / `AIOA_SCFY_ENABLED`，**尚未在有管理端配置页暴露**。
2. **需登录接口（后台 CRUD / 小程序）**：当前阶段业务约束是只读，且 `/show/*` 已覆盖查询需求，故未接入。待后台测试服务可用并提供账号后评估。
3. **测试环境数据源**：`http://127.0.0.1:16060/scfy` 服务在跑但连不上库（§6.4），修复前无法用测试环境复跑矩阵。
4. **反馈对方**：`/show/data/*` 的 `relation "t_shop" does not exist` 是其生产库缺表/schema 不一致，我们改不了，需对方修。
