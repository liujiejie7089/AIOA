# 非遗四川 2023（scfy）接入 —— 缺失信息清单与追问

> 依据：`docs/_incoming/非违接口文档.txt`（833 行）+ 2026-09-21 生产西昌环境实测。
> 原则：**只列实测发现或文档确实没写的**，不臆造、不代答。
> 每项标注「阻断级别」：`P0`=不做就无法推进 ｜ `P1`=影响完整性 ｜ `P2`=优化项

---

## 一、环境与连通性

### M1 【P0】接入目标环境未指定 —— 文档 4 套环境，实测只有 1 套可用

文档列了 4 套地址，实测结果：

| 文档声明 | 实测 | 结论 |
|---|---|---|
| 本地 `http://127.0.0.1:7777/scfy` | `502`，响应体 `upstream connect failed: 目标计算机积极拒绝 (os error 10061)` | **不可用**，本机无 scfy 进程 |
| 测试 `http://172.16.9.19:7777/scfy` | 8 秒超时，`HTTP=000` | **不可达**（内网段，需 VPN/专线） |
| 生产西昌 `https://szbhpt.tsichuan.com/scfy` | ✅ `/show/*` 67 个接口全部 HTTP 200 | **唯一可用** |
| 生产自贡 `https://szbhpt.tsichuan.com/scfy-zigong` | `404` | **路径不存在** |

附带实测发现：
- 根路径 `https://szbhpt.tsichuan.com/scfy` 返回 `302` → 跳转到 `http://szbhpt.tsichuan.com:16060/scfy/` → 该地址又返回 `502`。即**门户根路径是坏的**，但 `/show/*` 业务接口正常。
- `swagger-ui.html` 在生产返回 `200`（文档说仅 local 启用，实测生产也开着）。

**需要你回答：**
1. 本次接入的**目标环境**是哪一个？如果目标是测试/本地，请提供可达方式（VPN、跳板机、或把 scfy 部署到本地 7777）。
2. 生产自贡 `/scfy-zigong` 返回 404，是环境已下线还是上下文路径写错？
3. 是否允许端到端测试**直接打生产**？目前 `/show/*` 是只读查询、无需登录，风险可控；但一旦涉及第七章写接口，**我不能在生产上做写测试**。

---

## 二、账号与鉴权

### M2 【P0】没有任何可用账号 —— 第七章全部接口无法测试

文档给了三种登录方式，但都不给账号：

| 方式 | 端点 | 缺什么 |
|---|---|---|
| 本地账号 | `POST /scfy/sso/shiro/ajaxLogin` | `username`、`password` |
| 云多租户 | `POST /scfy/sso/shiro/ajaxLoginCloud` | `tenantCode`、`username`、`password` |
| 慧旅云 SSO | `POST /scfy/sso/shiro/ajaxLoginCloudByToken` | 已签发的 `accessToken` |

密码加密方式已知（AES/ECB/PKCS5Padding，key=`8bd32eeed3d0e0ea`），但**没有明文密码可加密**。

**影响范围（全部无法端到端验证）**：
- 登录 / 登出 / 用户信息（`userInfo`）
- Token 自动续期链路（响应头 `token` → 更新本地 Token）
- 后台管理 CRUD：`/project/`、`/inheritor/`、`/workshop/`、`/ecological/`、`/sys/`、`/upload_image`
- 小程序接口：`/applet/appletexhibition`、`appletpurchase`、`appletvideo`
- 第三方 SSO：`/sso/third/fy/*`

**需要你回答：**提供一组**测试专用账号**（用户名 + 密码 + 租户编码），要求权限覆盖「只读查询 + 至少一个写接口」以便验证权限校验器；如果是生产账号，请明确哪些操作**禁止 AI 执行**。

### M3 【P1】角色枚举与数据权限模型未定义

JWT Payload 示例里 `attr.role = ["fygw_admin"]`、`userType = "WLJ"`、`region = 510104037000`，但文档没给：
- 完整的**角色枚举**有哪些值？（`fygw_admin` 之外还有什么）
- 各角色的**数据可见范围**：是否按 `region` 行政区划代码约束？市级管理员只能看本市州吗？
- `/sys/` 下 role/resource 的权限模型长什么样？

**影响**：无法为工具设计权限校验器——AI 不知道「当前用户能不能查某个市州的数据」。

### M4 【P2·安全提示】JWT 签名密钥为弱密钥

文档附录 B：`BASE64KEY = MTIzNDU2`（明文 `"123456"`），HS256 对称加密。
这意味着**任何人都能自签合法 JWT**。虽不在本次接入范围内，但建议在缺陷记录里备案，并确认是否要向对方反馈。

---

## 三、文档本身的缺口与矛盾

### M5 【P1】等级枚举不全 —— 实测出现文档没有的「联合国级」

文档第十一节写死：等级枚举 = `country`(国家级) / `province`(省级) / `city`(市级) / `county`(县级)。

实测 `/show/project/getProjectListByArea` 返回首条：
```json
{"project_base_id": "2-UN-1", "project_name": "格萨（斯）尔", "project_level": "联合国级"}
```

**存在第五个等级「联合国级」**，文档未列出。校验器若按 4 个枚举做校验，会把合法请求误判为非法参数。

**需要你回答：**完整等级枚举到底是哪些？`level` 参数传什么值能筛出联合国级？

### M6 【P1】`/show/data/*` 与 `/show/shop/*` 职责重叠，且前者全线报错

文档 6.3 同时给了两套前缀，都说查「非遗工坊」，但没说清关系。实测：

- `/show/data/*` 8 个接口**全部** `code=500`，错误为 `relation "t_shop" does not exist`（Kingbase8）。已用真实工坊 ID `140` 复测，仍 500。
- 同期 `/show/shop/shopTable?cityName=成都市` 正常返回 52 条工坊数据。**工坊数据本身是存在的**，只是 `/show/data/*` 这套 Controller 查的 `t_shop` 表不在当前 schema。

**需要你回答：**
1. `/show/data/*` 是**已废弃**接口吗？如果是，请从 AI 可用工具清单里剔除，我不接入。
2. 如果不是废弃而是生产库异常，需要对方修复 —— 这属于**被接入系统的生产缺陷**，我方无法代修。

### M7 【P1】`shopv2` 与 `shop` 的差异未说明

文档只说「同名接口在 `/show/shopv2` 也提供，返回结构相同，作为 v2 版本」。
实测两个前缀的 `shopTable`、`pieChartAndStores` 返回确实一致，但**没说 v1 是否会下线、新接入应该用哪个**。

### M8 【P2】分页参数不统一

- 文档第十一节说：默认 `pageNum=1, pageSize=10`，返回 `{list, total, pageNum, pageSize}`
- 实测 `/show/inheritor/getInheritorListByArea` 返回 `{pageCount, pageNumber, dataList, pageSize, totalCount}` —— **字段名完全不同**
- 文档 7.1 后台管理又用 `pager.pageNumber` / `pager.pageSize`
- `/show/data/shopDetail/{id}` 用 `num` 而不是 `pageSize`

三套分页口径并存，需要逐个接口确认。

### M9 【P2】`area` / `cityName` 的合法取值清单缺失

文档只举例「成都市、绵阳市、甘孜藏族自治州」「不传 cityName 表示全省」。
实测 `/show/ecologicalArea/getTouristCountyList` 返回 28 个地区。需要一个**权威的市州名称清单**做参数校验，否则用户说「成都要」时 AI 无法判断是否合法。

### M10 【P2】生产响应 AES 解密密钥未给实际值

文档 5.4 说 profile=proxc 时 `/web/api/*`、`/zytf/api/*`、`/nmch/ccss/*` 响应需 AES 解密，key 见 `ZytfProject.AES_KEY`。
**但没给出 key 的实际值**。本次接入若不碰这三个前缀可绕过，需确认。

---

## 四、接入约束与风险

### M11 【P0】AI 是否允许写操作？

第七章全是 `save / update / delete`。一旦接入，AI 理论上能改非遗项目、传承人、工坊数据。
**需要你明确**：
- AI 只做**只读查询**，还是允许写？
- 若允许写，哪些表/操作必须走人工审批（HITL）？
- 是否允许在生产环境写？（我的建议：默认全部写操作 `requiresApproval=true`）

### M12 【P1】生产环境的调用配额与限流未知

文档未提 QPS 限制、日调用量上限。`/show/*` 有 Redis 缓存（分钟级延迟），但未说明缓存策略。
若 AI 高频调用，是否会被对方限流或误判为攻击？

### M13 【P1】跨域白名单未确认

文档说「已配置 CORS Filter，AI 前端可直接跨域调用」，但没说允许的 Origin。
OA 基座前端域名是否在白名单内？浏览器直连会不会被拦？（服务端调用不受影响）

---

## 五、汇总：需要你拍板的 5 件事

| # | 问题 | 不回答的后果 |
|---|---|---|
| 1 | **接哪个环境**？（测试不可达，只有生产可用） | 端到端测试只能在生产做，写测试完全无法做 |
| 2 | **给一组测试账号**（用户名/密码/租户码） | 第七章 30+ 需登录接口全部无法验证，权限校验器无法设计 |
| 3 | **AI 能否写数据**？哪些要审批？ | 无法确定工具风险级别，存在误改生产数据风险 |
| 4 | **`/show/data/*` 是否废弃**？ | 8 个接口的缺陷无法定性（是废弃还是待修） |
| 5 | **等级枚举是否含「联合国级」**？市州清单？ | 参数校验器会误判合法请求 |

---

## 六、我已经能确定的（不需要你回答）

- `/show/*` 67 个接口在生产西昌**全部可达**、无需 Token，可作为第一期接入范围。
- 文档 8 处参数错误已实测确认并给出正确参数名（见映射表 D2）。
- 文档 20 处返回结构与实际不符，已实测确认（见映射表 D3）。
- OA 基座已有完整的工具治理骨架（`@AioaTool` 注解即契约 / JSON Schema 自动推导 / `ToolDispatcher` 出网调用 / `ToolPermissionService` 权限 / `ToolInvocationLog` 审计 / 熔断与重试），接入**不需要改基座代码**。
- 唯一必须新写的：**scfy 适配器**（因为它的鉴权是自定义 `token` 头 + AES 加密密码 + 每次响应头续期，基座 `ToolDispatcher` 只支持 BASIC/Bearer）。
