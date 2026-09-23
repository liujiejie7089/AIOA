# 非遗域名 `https://szbhpt.tsichuan.com/` 业务前缀探测结论

> 探测时间：2026-09-21（多次复核，结论稳定）
> 探测脚本（全部只发 GET，无任何写操作）：
> - `scripts/_probe_fy_root_domain.py` —— 前缀可达性
> - `scripts/_probe_fy_swagger_enum.py` —— 尝试抓线上接口全量清单
> - `scripts/_probe_fy_show_modules.py` —— 尝试枚举未文档化模块（**方法失效，见 §4**）
>
> 问题：该域名除了已接入的 `/scfy/show/*`，拼上别的业务路径/参数还能不能查到数据？

---

## 1. 结论（一句话）

**不能。整个域名下唯一能匿名查到业务数据的入口只有 `/scfy/show/*`** ——
而这一套（55 个只读查询接口）我们已全部接入并端到端验证过。
其余所有业务前缀要么**未部署（404）**，要么**需要登录（401/500）**，要么**是死代理（502）**。

## 2. 实测矩阵

| 路径 | 状态 | 响应 | 判定 |
|---|---|---|---|
| `/` | 403 | BWS `403 Forbidden` | 根路径被网关直接拒绝 |
| `/scfy`（无斜杠） | 502 | `upstream connect failed: os error 10061` | 网关把该精确路径转发到**已宕机的上游** |
| `/scfy/` | 500 | `{"code":401,"message":"Token失效，请重新登录"}` | 服务在，需登录 |
| **`/scfy/show/ecologicalArea/getAreasNum`** | **200** | `{"code":0,"data":{"country":"1","province":"6"}}` | **免登录，真实数据** |
| **`/scfy/show/project/getProjectCountByArea?area=成都市`** | **200** | 联合国教科文组织 1 / 国家级 26 / 省级 119 | **免登录，真实数据** |
| **`/scfy/show/travel/getRoutesTopFewList?topNum=3`** | **200** | 含 `routesTopFewList[]` 真实记录 | **免登录，真实数据** |
| `/scfy/sso/shiro/ajaxLogin` | 200 | `{"code":500,"message":"登录账号不能为空！"}` | 登录口在，但需账号 |
| `/scfy/swagger-ui.html` | 200 | Swagger UI 静态壳 | 只是前端 bundle，无数据 |
| `/scfy/v3/api-docs`（及 `swagger-config` / `default` / `?group=`） | 500 | `{"code":401,...}` | **被 Shiro 拦**，接口清单不可匿名获取 |
| `/scfy/actuator/health` | 500 | `{"code":401,...}` | 同上 |
| `/show/...`（去掉 `/scfy` 前缀） | 404 | BWS HTML 404 | 前缀必需 |
| `/scfy-zigong/` | 404 | Tomcat 404 HTML | 自贡站未部署在此域名 |
| `/web/`、`/web/api/`、`/zytf/`、`/zytf/api/`、`/nmch/`、`/nmch/ccss/`、`/applet/`、`/sys/`、`/sso/`、`/api/`、`/api/scfy/`、`/fy/`、`/portal/` | 404 | BWS 404 | **接口文档里出现过的其他业务前缀，一个都没部署在这个域名下** |
| `/swagger-ui.html`、`/v2/api-docs`、`/actuator/health`、`/index.html`、`/favicon.ico` | 404 | BWS 404 | 根级探查点均无 |
| `http://szbhpt.tsichuan.com:16060/*` | 502 | `upstream connect failed: os error 10061` | **16060 是死代理**（目标机积极拒绝） |
| `https://szbhpt.tsichuan.com:16060/*` | -1 | `Tunnel connection failed: 502` | 同上 |

## 3. 三个必须说清的判据

1. **`/scfy/show/*` 免登录已验证**：不带任何 token 直接 GET，返回 `code=0` 与真实数据；
   而 `/scfy/` 根路径同域同服务却返回 401。说明**放行规则精确作用在 `/show/**` 前缀上**，
   不是「整个应用免登录」。
2. **UN 级（联合国教科文组织）数据确实存在且可取**：
   `getProjectCountByArea?area=成都市` 明确返回 `联合国教科文组织 num=1` ——
   这坐实了契约里 `level` 枚举必须包含 `un`，不是我们臆测。
3. **16060 端口与生产域名是两条独立链路**：
   域名走 443 由 BWS 网关终结并转发；16060 被网关当作另一个上游，且该上游已死。
   所以「本地测试环境 16060」和「生产域名」不能混为一谈 —— 本地那份是我们自己起的
   Spring Boot（DB 不通），生产 16060 是对方机器上的另一个进程。

## 4. 一次失败的方法（如实登记，避免后人重蹈）

`scripts/_probe_fy_show_modules.py` 想用「模块名 × 假方法名」的响应形态差异来枚举
未文档化的模块。**方法不成立**：基线校准显示，
「已知存在模块 `project` + 假方法」与「已知不存在模块 `zzznope_xyz` + 假方法」
**返回完全相同的 `APP_404`** —— 该应用对任何未映射路径统一回 404，
无法据此区分模块存在与否。该脚本的「全部判定为存在」是**假阳性**，不予采信。

**可靠的模块边界只能来自接口文档**（`docs/_incoming/非违接口文档.txt`），
线上清单又被 Shiro 挡住，因此「是否存在文档外模块」目前**无法证伪，也无法证实** ——
这是当前认知的真实边界，不当成结论用。

## 5. 文档里出现、但实测查不到数据的两类情况（拼参数也救不回来）

这两类我们已按「不确定即废弃」登记在契约里（`ScfyCatalog.deprecated()`，共 12 条），
它们的失败**与参数无关**：

| 组 | 路径 | 实测 |
|---|---|---|
| 工坊 data 口径（8 条） | `/show/data/*` | `code=500`：`relation "t_shop" does not exist`（Kingbase8）。已用真实工坊 id=140 复测仍 500 —— **是该 Controller 查的库表不在当前 schema**，同栏目 `/show/shop/*` 同类数据正常 |
| 工坊 v2（2 条） | `/show/shopv2/*` | 文档只说「与 `/show/shop` 结构相同，作为 v2」，未说明 v1 是否下线 —— 差异与生命周期明确前不接入，避免同一数据两条工具路径 |
| 保护区图片（2 条） | `/show/ecologicalArea/getEcologicalAreaImageUrl`、`/getPagerTravelImageUrl` | 前者 `type` 语义未明且错配即 500；后者只返回分页器、**无任何数据列表字段** |

## 6. 对当前接入工作的影响

- **无需任何代码改动。** 本次探测是对既有事实的复核，不是新需求。
- 已接入能力边界即 `/scfy/show/*` 的 55 个只读查询工具，矩阵实测 **55/55 覆盖、54 有数据、1 恒空、0 失败**。
- 想拿到 `/show/data/*` 与写接口，**依赖对方**：① 修好 Kingbase 里的 `t_shop` 表 / schema；
  ② 提供可登录账号；③ 开放后端写服务。这三项都不在我们可控范围内。
