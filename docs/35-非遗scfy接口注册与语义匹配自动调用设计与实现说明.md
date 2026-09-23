# 35 · 非遗四川 scfy —— 接口注册 · 语义匹配 · 自动调用 设计与实现说明

> 模块：`server/aioa-integration-scfy`（包 `cn.aioa.integration.scfy.agent` + `.tools`）
> 前置文档：`docs/34-非遗四川scfy只读接入设计与实现说明.md`（适配器与契约）、
> `docs/_incoming/非遗scfy-返回结构实测.md`（实测原始数据）
> 状态：已实现并验证（44 个离线单测 + 2 个真实出网端到端 + 3 个装配级验证）

---

## 1. 需求与本轮的交付边界

用户提了三件事，逐条落到具体构件：

| # | 需求原文 | 落地为 | 证据 |
|---|---|---|---|
| ① | 把当前已能正常返回数据的接口注册到 agent，含**名称 / 用途描述 / 参数 / 返回结构** | `ScfyAgentCatalog` + `ScfyToolDescriptor`（四要素载体），`scfy_catalog` 工具对外可见 | `ScfyAgentCatalogTest`（5 例）；启动自检硬失败 |
| ② | 用户提问 → 按接口描述**语义匹配** → 匹配成功则**自动调用并返回数据** | `ToolMatcher` / `LexicalToolMatcher` + `ScfyParamExtractor` + `ScfyAgentService.ask()`，入口工具 `scfy_ask` | `ScfyToolMatcherTest`（6）+ `ScfyParamExtractorTest`（9）+ `ScfyAgentServiceTest`（9）+ `ScfyAgentE2ETest`（2，真实出网） |
| ③ | 设计需**支持可扩展**，新增接口不改动核心匹配与调用逻辑 | 扩展点落在「契约一行 + 注解方法」，匹配层是接口插槽 | `ScfyAutoConfigurationWiringTest`（3，含「换匹配器不改调用方」的实测） |

**仍然生效的硬约束（沿用 docs/34）**：只读（无任何写路径）；不确定的接口不注册；模块不依赖基座业务模块（只依赖 `aioa-tool-sdk` + `aioa-common`）；适配器不含 Controller、不占端口。

关于「已能正常返回数据的接口」这句，本实现取**实测口径**而非文档口径：
`ScfyMatrixTest` 对契约中每个可用接口发起真实请求，只有观测到**非空数据**（`observed=OK_DATA`）才进入自动匹配集合。结论是 **55 个已注册 / 54 个可自动匹配 / 1 个被排除**（`eco_nmch_base` 调用成功但恒返回空集）。

---

## 2. 总体链路

```
用户提问（自然语言）
      │
      │  scfy_ask(question, toolCode?)
      ▼
┌─────────────────────────────────────────────────────────────┐
│ ScfyAgentService.ask()                                      │
│                                                             │
│  ① 取候选：catalog().registered()      ← 54 个（已实测有数据）│
│  ② 语义排序：matcher.rank(q, 候选, 5)   ← 可插拔插槽          │
│        └─ top1.score < matcher.minScore() ⇒ matched=false    │
│           并回「能查什么 + 该怎么问」的提示，不猜一个去调      │
│  ③ 复选：在 top3 内挑「必填参数能被提问满足」的               │
│  ④ 抽参：extractor.extract(q, tool) → args + evidence        │
│  ⑤ 前置校验：validator.validate(ep, args)                    │
│        └─ 缺必填 ⇒ needUserInput=true + askUser 追问话术      │
│  ⑥ 调用：registry.invoke(toolCode, args, system())           │
│  ⑦ 回包：ok / data / returns / argEvidence / 裁剪与截断标记   │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
结构化结果（含可追溯信息：tool、score、matchReasons、endpoint、returns）
```

两个 agent 入口工具的分工：

- **`scfy_ask`** —— 一句话直达数据。服务端承担匹配、抽参、调用、裁剪，模型只需把用户**原话整句**递进来。
- **`scfy_catalog`** —— 先看清单再决定。不传参数看 55 个接口概览；传 `toolCode` 看某个接口的**完整参数表 + 返回字段**。

> 为什么用 `@AioaTool` 两个方法而不是新开一组 HTTP 接口：本模块的既有口径是「适配器不做 Controller、不占端口」，对外通道统一由平台工具网关提供（`/internal/v1/tools` 列表 + `/internal/v1/tools/invoke` 调用）。声明两个注解方法即自动获得清单登记、权限、审计与其余工具一致的调用方式 —— **不改基座一行代码**。

---

## 3. ① 接口注册：四要素从哪里来

### 3.1 三条来源，而不是三份手写文本

「注册」最容易出的问题是**同一条事实写两遍**，然后漂移。本实现在结构上不给它机会 ——
每个要素只有一个来源，且这个来源本身已经是被别处消费的同一份数据：

| 要素 | 唯一来源 | 为什么不另写一份 |
|---|---|---|
| **名称 / 用途描述 / 入参 Schema** | `@AioaTool(name=…, description=…)` + `@AioaToolParam`（经 SDK 注册表 `ToolSpec`） | 这就是模型看到的工具清单本身。分开写必然出现「注册表说三个参数、清单说两个」 |
| **分组 / 真实路径 / 参数契约（必填性、枚举、实测校正）** | `ScfyCatalog`（契约，docs/34 已建） | 接口事实只在契约里判定一处 |
| **返回结构** | `src/main/resources/scfy/return-shape.json`（**矩阵实测生成**） | 手写返回结构等于第二份真相；后端改字段名后它会静默变成误导，而模型会照着它取 null |

`ScfyAgentCatalog` 自己的定位是「**三份事实的联结，自己不产生事实**」。由它拼出 `ScfyToolDescriptor`：

```java
record ScfyToolDescriptor(
    String toolCode,            // scfy_<endpointId>，与契约可机器比对
    String endpointId,          // 契约 id
    String group,               // 能力域：传承人/项目/工坊/保护区/旅游
    String name,                // @AioaTool.name
    String purpose,             // @AioaTool.description（语义匹配主输入）
    String path,                // /show/project/getProjectCountByArea
    List<ScfyParam> params,     // 契约参数（含必填性、枚举）
    Map<String,Object> inputSchema,   // 模型可填的入参 Schema
    Map<String,Object> outputSchema,  // 统一信封 + 本接口 data 的实测形状
    Map<String,Object> dataShape,     // return-shape.json 里的实测形状
    String observed)            // 实测结论（OK_DATA / OK_EMPTY / UNKNOWN）
```

### 3.2 返回结构：为什么必须实测而不能手写

`return-shape.json` 由 `ScfyMatrixTest` 真实调用后写入（`-Dscfy.matrix=true`），
对每个接口记录 `dataKind`、`elementKind`、`fields`（字段名 → 类型；嵌套则递归记录 `{kind, fields}`）。
再由 `ScfyResultEnvelope.schema(dataShape)` 生成对外声明的 `outputSchema`：**统一信封的 17 个固定字段 + `data` 的 `x-scfy-shape` 实测形状**。

于是「声明的返回结构」与「实际返回的东西」是同一份数据的两次投影，而不是两份文档。

### 3.3 四要素齐备性 = 启动硬失败

`ScfyToolDescriptor.missingParts()` 逐项检查，`ScfyAutoConfiguration.ScfyAgentReadinessCheck`
在 `ApplicationReadyEvent` 上执行，**不齐备即拒绝启动**。四要素缺任何一项，模型都会出现一类可预期的失败：

- 缺**名称** ⇒ 匹配到了也没法向用户解释「我查了什么」；
- 缺**用途描述** ⇒ 不知道该不该用它（这是匹配的主输入）；
- 缺**参数** ⇒ 猜参数名或漏传必填。scfy 对错参数是**静默返回空集**而非报错，会伪装成「没有数据」；
- 缺**返回结构** ⇒ 只能看到一大团 JSON，不知道取哪个字段，于是把整个响应体念给用户。

参数一项的判定刻意严格：要求**注解推导出的 Schema 参数个数 == 契约参数个数**，
并且另有 `ScfyCatalogConsistencyChecker` 在 Bean 构造期做**参数名逐一对账**（不一致直接抛异常）。
两个检查一个管「数量」、一个管「名字」，合起来才堵住漂移。

> 为什么挂在 `ApplicationReadyEvent` 而不是构造期：工具是注解，由 SDK 扫描器在
> 「所有单例实例化完成之后」才写进 `LocalToolRegistry`。早一步检查等于检查一张空表，
> 会得出「全都不齐备」的假结论。同理，`catalog()` 采用**惰性双检锁**装配，绕开这个时序陷阱。

---

## 4. ② 语义匹配：确定性词法实现（可替换）

### 4.1 为什么默认给确定性的实现

匹配质量与成本是一对矛盾。纯词法匹配零成本、离线可测、结果可复现，但「换个说法」时不如向量或大模型。
本实现**不预判哪个更好**，而是把匹配做成插槽（见 §6.2），默认填一个能跑、能测、结果稳定的实现。

### 4.2 打分构成

中文按**二元组（bigram）**切分（CJK 区间 `0x4E00–0x9FFF`），英文与数字按整词；对候选集计算 IDF 权重。

| 成分 | 权重/取值 | 作用 |
|---|---|---|
| 名称命中 | `W_NAME = 1.4` | 接口名是最强的语义信号 |
| 返回字段命中 | `W_FIELD = 1.2` | 用户常按**结果字段**提问（「工坊的销售额」），字段名只存在于返回结构里，不纳入必漏配 |
| 用途描述命中 | `W_DESC = 1.0` | 长文本，单位信息量低，权重最低 |
| 分组别名加成 | `+0.22` | 「店铺/门店/作坊」→ 工坊；「大师/手艺人」→ 传承人（`GROUP_ALIASES`） |
| 列表意图 / 计数意图 | `+0.16 / −0.15` | 见 §4.3 |
| 名称整串命中 | `+0.3` | 直接点名接口名 |
| 无城市范围惩罚 | `−0.25` | 提问里明确了城市，但该接口没有 `area/cityName/areaId/cityCode` 参数 ⇒ 它不可能答这个问题 |
| 阈值 | `MIN_SCORE = 0.45` | 低于此值判「没匹配到」 |

排序保留**未截断的原始分**（早期把分数封顶到 1.0 后，三个旅游类接口并列 1.000，
只能靠 code 字典序决定先后 —— 等于把「择优」变成了「按字符串排序」）。

### 4.3 两个来自实测缺陷的修正

**（a）列表 / 计数意图必须只看接口名。**
最初用「名称 + 用途」判意图，结果 `scfy_project_list_by_area` 被误判为计数接口 ——
因为**列表接口的用途描述里交叉引用了计数接口**（「按等级查数量请改用 scfy_project_count_by_area」）。
改为只读**名称**（`LIST_TOOL_MARKERS=["列表","名单","清单"]` / `COUNT_TOOL_MARKERS=["数量","统计","汇总","计数"]`）后消失。
这是「描述写得好反而害了匹配」的典型：**凡是要机器判定的维度，就不能放进面向人的自由文本里。**

**（b）计数接口确实不收城市名。**
`scfy_project_count_by_area`（按地区统计项目数）与 `scfy_inheritor_list_by_area` 都**不接受城市名参数**，
它们只返回全省 21 个地市的横向对比。因此「甘孜州有多少非遗项目」匹配到它们、并由服务端在整表里定位该地市，
**是正确行为**，不是错配 —— 最初的两条测试期望反而是错的，已更正。

### 4.4 匹配不到时的行为

返回 `matched=false` + 候选清单 + 一段提示（当前可查范围 + 示例问法）。
**绝不猜一个接口去调**：猜错的代价是一份看起来正常、实际答非所问的数据，比「我不知道」有害得多。

---

## 5. ③ 自动调用：抽参 → 前置校验 → 调用

### 5.1 两段式选接口：描述决定顺序，参数只用来复选

```
matcher.rank(q, 候选, 5)   ← 按描述排
        │
        ▼  在 top3 窗口内
pick()：挑第一个「必填参数能被提问满足」的接口
        │  都满足不了 ⇒ 回落为第一名（由校验器生成追问话术）
        ▼
```

为什么必须两段：只用描述排，会遇到「描述最像但参数凑不齐」的接口 ——
问「成都有哪些非遗工坊」，最像的可能是 `scfy_shop_detail`（工坊详情），
但它必填 `cityName + id`，而提问里没有 id；硬调只会得到一句追问话术。
而同一句话用 `scfy_shop_table`（只要 `cityName`）就能直接把工坊列表拿出来，
列表里的 `list[].id` 才正是下一次查详情要用的输入。
反过来只按「参数好凑」排，会挑到描述不相关的简单接口。
所以**描述定候选顺序，参数可满足性只在头部窗口里决定「能不能一把调通」，且不越过匹配阈值这道门**。

### 5.2 参数抽取（`ScfyParamExtractor`）

从提问里抽参数并同时产出 `argEvidence`（哪个词抽出哪个参数），让结论可追溯：

- **城市归一化**：`甘孜藏族自治州 → 甘孜州`；长名优先于词干匹配（避免截断错配）。
- **等级词**：`国家级 → country`；`联合国级 / 联合国教科文组织 → un`。
  孤立的「省 / 市」**不**当作等级 —— 它们与地名冲突。
- **areaCode**：只接受 12 位数字，避免把年份、编号误当区划码。
- **数量**：`pageSize / pageNum / topNum` 数值截断（`MAX_PAGE_SIZE=100`）。
- **id 形态**：UUID / `_country` 后缀 / `2-UN-1` / 32 位十六进制 / 带标签数字（`id=140`）。
- **区县**：先 `stripCityNames()` 剥掉市名再匹配（否则「成都市锦江区」会被抽成「都市锦江区」），
  并加否定后顾 `(?<![\u4e00-\u9fa5])` + 连接词过滤。
- **没抽到就不传**：不填默认值 —— 缺必填由下一环节追问，而不是让接口静默返回空集。

### 5.3 前置校验：一个必须由自己做的校验

工具网关的绑定器（`LocalToolRegistry.bind`）在**缺必填参数**时会直接抛
`IllegalArgumentException("缺少必填参数：xxx")` —— **根本进不到工具方法里**，
也就拿不到 `ScfyParamValidator` 生成好的追问话术，最终用户只看到一句技术性报错。

因此服务层在调用前用**同一个校验器实例**先校验一遍：

```java
ScfyParamValidator.Result vr = validator.validate(ep, ex.args());
if (!vr.ok()) {                       // 判定与话术与实际下发完全一致
    out.put("preflightFailure", true);
    if (vr.askUser() != null) { out.put("needUserInput", true); out.put("askUser", vr.askUser()); }
    return out;
}
registry.invoke(tool.toolCode(), vr.normalized(), ToolCallContext.system());
```

### 5.4 调用与回包

`registry.invoke(..., ToolCallContext.system())` —— agent 自发调用，无用户身份，
但**仍走完整治理链**（权限 / 幂等 / 审批 / 审计），与人工触发同一条路径。

调用异常在此被收成**结构化失败**（不向上抛 —— 抛出去模型只会看到「调用失败」四个字）：
`ok=false` + `errors`。回包里附带 `tool / toolName / purpose / endpoint / score / matchReasons /
args / argEvidence / returns`，以及裁剪与截断标记：

- `truncated` + `truncatedField` + `totalItems` + `returnedItems` —— 条目被裁剪，**真实总数一并给出**，让模型知道「这不是全部」；
- `responseTruncated` —— 响应体触发字节上限（与条目裁剪是两件事）；
- `docMismatch` —— 文档与实测不一致的提示，必须让模型看到，否则会照文档传错参数。

---

## 6. 可扩展性（需求 ③）

### 6.1 新增一个接口 = 改两处数据 + 跑一次采集

| 步 | 动作 | 为什么不需要动流程代码 |
|---|---|---|
| 1 | 在 `ScfyCatalog` **加一行契约**（路径、分组、参数、必填性、枚举） | 契约是接口事实的唯一入口；`ScfyAgentCatalog` 按 id 反查自动带上它 |
| 2 | 写一个 `@AioaTool` 方法（调 `ScfyToolSupport`） | 名称 / 用途 / 入参 Schema 由注解推导，SDK 扫描器自动登记 |
| 3 | 跑一次矩阵采集返回结构：<br>`mvn -pl aioa-integration-scfy test -Dtest=ScfyMatrixTest -Dscfy.matrix=true` | `return-shape.json` 重新生成，`outputSchema` 随之更新 |

**`ScfyAgentCatalog` / `ToolMatcher` / `ScfyParamExtractor` / `ScfyAgentService` 一行都不用改。**
漏做第 3 步也不会静默：启动自检会以「返回结构缺失」硬失败。漏做第 1 步则 `ScfyCatalogConsistencyChecker` 报「指向契约中不存在的接口」。

### 6.2 换匹配器 = 声明一个 Bean

`ScfyAutoConfiguration.scfyAgentService(...)` 用
`matchers.getIfAvailable(LexicalToolMatcher::new)` 取用：

- 容器里**恰好一个**自定义 `ToolMatcher` Bean ⇒ 用它；
- **一个都没有** ⇒ 退回默认词法匹配器；
- **出现多个** ⇒ 直接报错，而不是随便挑一个（不确定的选择比明确失败更贵）。

要换成向量检索或大模型选工具，只需实现 `ToolMatcher` 三个方法：

```java
public interface ToolMatcher {
    String name();
    List<Match> rank(String question, List<ScfyToolDescriptor> candidates, int topN);
    double minScore();
    record Match(ScfyToolDescriptor tool, double score, List<String> reasons) { … }
}
```

接口刻意**只收「提问 + 候选集 + 取前几名」**，不暴露任何内部打分细节 ——
一旦把分数语义写进接口，替换实现就会被分数口径绑架。

`ScfyAutoConfigurationWiringTest.matcherIsPluggable()` 就是这句承诺的实测：
注册一个自定义 `ToolMatcher` Bean，`service.matcher().name()` 变为 `test-vector-matcher`，
且注册表与其余能力照旧可用。

### 6.3 这套设计的边界（说清不做什么）

- **不做接口自动发现**：契约是人工维护的「事实表」，因为「这个接口该不该给 agent 用」是业务判断，不是可推断的事实。
- **不做参数自动补全式猜测**：抽不到就问，不填默认值。
- **不做跨接口编排**：一次 `ask` 只调一个接口。多接口汇总属编排层职责，不在本模块。

---

## 7. 异常处理一览

| 情况 | 触发点 | 返回 | 是否向上抛 |
|---|---|---|---|
| 问题为空 | `ask` 入口 | `ok=false, matched=false` + 「请给出问题」提示 | 否 |
| 无相关接口（低于阈值） | 匹配后 | `matched=false` + 候选清单 + 可查范围提示 | 否 |
| 指定了不存在 / 已排除的工具 | `resolvePinned` | `matched=false` + 原因（含 `observed` 值） | 否 |
| 缺必填参数 | 前置校验 | `needUserInput=true` + `askUser` 追问话术 | 否 |
| 调用失败（网络 / 对端错误） | `invoke` | `ok=false` + `errors`（含异常消息） | 否（收成结构化失败） |
| 工具 ↔ 契约参数名不一致 | `ScfyCatalogConsistencyChecker` | 启动异常，列出全部不一致项 | **是**（代码缺陷，拒绝启动） |
| 四要素不齐备 / 悬空工具 / 注册表为空 | `ScfyAgentReadinessCheck` | 启动异常，逐项列出 | **是**（注册没生效，拒绝启动） |
| 返回结构资源缺失 | `readShapeResource` | 启动异常 + 可执行的补救命令 | **是** |
| 结果被裁剪 / 响应超限 | 调用后 | `truncated` / `totalItems` / `responseTruncated` 标记 | 否（真实信息照给） |

原则：**诊断端点回「报告」，动作端点才失败即抛**；凡是"没做到"的事，必须让调用方看出来。

---

## 8. 验证方式（可复跑）

```bash
cd server

# 1) 离线全量（44 例）：注册表 / 匹配器 / 抽参 / 服务 / 装配，均不出网
./mvnw -pl aioa-integration-scfy test
#    ScfyAgentCatalogTest            5   四要素齐备、55/54/1、检索文本含返回字段
#    ScfyToolMatcherTest             6   真实问句命中正确接口、无关问题不命中、结果确定
#    ScfyParamExtractorTest          9   城市归一化、等级、区划码、数量、id、区县
#    ScfyAgentServiceTest            9   成功 / 指定工具 / 追问 / 不匹配 / 拒绝无数据接口 / 清单
#    ScfyAutoConfigurationWiringTest 3   装配成功 + 默认匹配器 + 换匹配器不改调用方
#    （另 ScfyContractTest 4 / ScfyParamValidatorTest 8）

# 2) 真实出网端到端（2 例）：真实提问 → 匹配 → 抽参 → 调用 → 非空数据
./mvnw -pl aioa-integration-scfy test -Dtest=ScfyAgentE2ETest -Dscfy.agent=true

# 3) 重新采集返回结构（改了契约或新增接口后必须跑）
./mvnw -pl aioa-integration-scfy test -Dtest=ScfyMatrixTest -Dscfy.matrix=true
```

端到端实测样例（2026-09-23，生产西昌，`ScfyAgentE2ETest.CASES` 全 6 例均通过）：

| 提问 | 命中接口 | 抽出参数 | 返回叶子数 |
|---|---|---|---|
| 成都有哪些非遗工坊 | `scfy_shop_table` | `cityName=成都市` | 400 |
| 甘孜州有多少非遗项目 | `scfy_project_count_by_area` | `area=甘孜州` | 6 |
| 四川有哪些文化生态保护区 | `scfy_eco_area_top_list` | — | 49 |
| 非遗旅游线路有哪些 | `scfy_travel_route_top_list` | — | 30 |
| 国家级非遗项目的门类分布是怎样的 | `scfy_project_type_data` | `level=country` | 32 |
| 国家级非遗传承人的性别比例 | `scfy_inheritor_gender_data` | `level=country` | 3 |

断言口径是**双条件**：既要求命中预期接口，也要求返回**非空**数据。
只断言「命中」是不够的 —— 对方对错参数不报错、只返回空集，命中却空数据等于参数抽取有问题。

两处值得注意的细节：

- 第 3、4 例的接口只有可选参数 `topNum`，提问里没有数量词，抽取结果就是**空参数表**，
  而不是替用户随便填一个「10」—— 这正是 §5.2「没抽到就不传」的效果。
- 第 5、6 例的等级词「国家级」被稳定映射为 `level=country`（不是 `national`，取值以契约为准）。

---

## 9. 未闭环项

1. **匹配器仍是词法实现**。同义改写（如「巴蜀手艺的店铺数量」这类不含接口用词的说法）仍可能低于阈值。
   插槽已就位，换成向量检索或大模型选工具不需要改调用方。
2. **`eco_nmch_base` 被排除在自动匹配之外**（实测恒返回空集）。它仍在 `scfy_catalog` 清单里可见并标注原因，
   但用户问「文化生态保护区有哪些」时不会命中它。根因在对端数据侧，不在本模块。
3. **多接口汇总未做**（「全省各地区工坊数量对比并排序」需多次调用）。属编排层职责。
4. **对方 Swagger / api-docs 全被 Shiro 拦（code=401）**，接口事实只能靠实测矩阵维持，新增接口需人工补契约。
