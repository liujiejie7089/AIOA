# Gitea 账号绑定：`unauthorized_client` 根因定位与修复

> 2026-09-18 · 实例 `http://172.16.8.249:3000`（Gitea 1.26.2）· 组织 `AI-OA`
> 触发线索：你发来的截图 —— 后端自有的绑定结果页显示 `绑定失败 / 原因：unauthorized_client`
> 结论：**「托管方登记的应用密钥无法通过校验」**。已换用新应用修复，只差你点一次授权。

## 1. 现象与第一层判断

截图里的「绑定失败」页是**后端自己渲染的**（`GiteeOauthController.failPage`），
说明**浏览器那半程已经走通了**：你在 Gitea 登录 → 点了授权 → Gitea 带着 `code` 跳回了
`http://localhost:8080/api/v1/gitee/bind/callback`。失败发生在**服务端拿 code 换令牌**这一步。

所以问题不是「跳转地址错」，而是「换令牌被拒」。

## 2. 四个对照实验（这一步决定后面所有结论）

对 `POST {web}/login/oauth/access_token` 做单变量对照，固定其它入参：

| # | 入参差异 | 响应 |
|---|---|---|
| A | 现役 client_id + **登记页显示的密钥**（表单编码） | `unauthorized_client / invalid client secret` |
| B | 同上，但用 JSON 体 | 同上（排除「编码方式」这个干扰项） |
| C | 现役 client_id + **故意写错的密钥**（对照组） | `unauthorized_client / invalid client secret` |
| D | **不存在的 client_id** | `invalid_client / cannot load client with client id: ...` |
| E | 现役 client_id + **空密钥** | `unauthorized_client / invalid empty client secret` |

判读：

- D 与 A 不同 ⇒ **client_id 是被识别的**（应用确实存在）；
- E 与 A 不同 ⇒ **密钥字段被读到了**（不是「没传进去」）；
- **A 与 C 完全相同** ⇒ 拿正确值去比，和拿错值去比，结果无法区分
  ⇒ **库里存的密钥与登记页显示的那串不是同一回事**，怎么传都过不了。

## 3. 决定性实验：换一个「新建的应用」再比

| 应用 | 密钥形态 | 同一条换令牌请求的结果 |
|---|---|---|
| 现役 app（id 4） | `qto_…`，55 字符 | `invalid client secret` ← **凭证校验就挂了** |
| **新建 app（id 6）** | **`gto_…`，56 字符** | `client is not authorized` ← **凭证校验通过**，才轮到授权码被拒 |

两次请求除了凭证以外完全相同。唯一变化的检查项就是凭证检查 ⇒
**Gitea 1.26 生成/校验的是 `gto_` 前缀密钥；id 4 那个 `qto_` 前缀的值永远无法通过校验。**

> 这也解释了「为什么看起来无懈可击」：Gitea 的 OAuth 应用编辑页把库里那个**失效值原样显示**出来，
> 你复制、我粘贴，两边逐字节一致 —— 但一致地无效。

## 4. 为什么这个故障会「看不懂」（第二个缺陷）

Gitea 的换令牌错误体是 `{error, error_description}`，而 `error` **恒为通用码**：

```
正确密钥 + 无效授权码 → {"error":"unauthorized_client","error_description":"client is not authorized"}
错误密钥            → {"error":"unauthorized_client","error_description":"invalid client secret"}
```

而我们的错误提取只取了 `error`（`firstDetail()` 末行 `return n.get("error")`），
**把 `error_description` 整个丢掉** ⇒ 两种截然不同的故障在页面上是同一个字符串
`unauthorized_client`。你的截图看不出方向，根因就在这里。

**修**：`firstDetail()` 改为 `error_description` 优先，并与 `error` 组合保留：
现在页面显示 `client is not authorized（unauthorized_client）`。
`errors[]`（协作方 422 那族）的优先级**保持不变**，避免改坏上一轮的修复。
该形状 Gitee 的 `/oauth/token` 同样适用，故放在托管方无关的公共提取里。

## 5. 本轮实际改动

| 项 | 内容 |
|---|---|
| Gitea OAuth 应用 | 删除失效的 id 4；**新建 id 6**（名称 `AIOA`、重定向 URI 逐字符不变、机密客户端） |
| 新 `client_id` | `a2e8f7bd-8f0b-4a2f-a1e5-345b5741b0cd` |
| 密钥 | 写入 `.env.gitea-real`（已 gitignore；`gto_` 前缀、56 字符），并在该文件注明重建原因 |
| 代码 | `client/GiteaProviderClient.java`：`firstDetail()` 优先 `error_description`；<br>`support/ProviderFailureText.java`：新增 `forOauthBind()`；<br>`controller/GiteeOauthController.java`：两个失败分支改走它 |
| 用户可见文案 | 绑定结果页从**托管方英文短语**改为「中文归因 + 可执行动作」，并保留原文附尾。例：<br>`invalid client secret` → 「平台侧应用密钥与 Gitea 登记的不一致（属平台配置问题，与你的账号无关）：请联系平台运维在 Gitea 重置该 OAuth 应用的密钥……（Gitea 原始返回：invalid client secret……）」<br>判据是**原因短语特征**而非状态码（换令牌失败恒为 400，状态码无区分度） |
| 单测 | 新增 `client/GiteaProviderErrorTextTest.java` 6 条（含「两种故障不得被判成同一字符串」）；<br>`support/ProviderFailureTextTest.java` +6 条（密钥失配 / 授权码 / 回调地址 / 无原因 / label 注入 / 确定性） |
| 清理 | 诊断用的临时应用已删除（未留残留）；最终该账号下**只有一个** `AIOA` 应用 |

## 6. 第二个缺陷：令牌写库被列宽截断（你的第二次截图）

**现象**：浏览器授权这次走到了回调，回调页报 `失败原因：Data too long for column 'access_token'`。

**定位**：日志里被拒的是**一次 INSERT**，不是换令牌 ——

```
### SQL: INSERT INTO gitee_account  ( tenant_id, user_id, provider, gitee_uid, gitee_username,
###        avatar_url, access_token, refresh_token, token_expires_at, bound_at, created_at, updated_at )
### Cause: com.mysql.cj.jdbc.exceptions.MysqlDataTruncation: Data truncation:
###        Data too long for column 'access_token' at row 1
```

（`logs/boot-gitea-v62.log`，**15:01:53** 与 **15:02:05** 各一次，对应你的两次点击；
事务整体回滚，所以 `gitee_oauth_state` 那两行至今仍是 `consumed=0`。）

也就是说：**授权通过了、换令牌通过了、用令牌取身份也通过了**（取身份那行代码在 INSERT 之前），
**失败在最后一步写库**。第一个缺陷（`unauthorized_client`）确实已经消失。

**根因**：列宽是照 Gitee 的令牌形状定的，而托管方换成了 Gitea。

| | Gitee | Gitea 1.26 |
|---|---|---|
| 令牌形状 | 32~40 字符随机串 | **JWT**（RS256 签名本身 ≈342 字符），整串 **600~1000 字符** |
| 入库前处理 | AES-256-GCM：`enc:` + Base64(12B IV ‖ 密文 ‖ 16B Tag) | 同 |
| 入库密文长度 | 56~84（实测现存 97 行：56/60/84） | **≈850~1400** |
| 列定义 | `varchar(1024)` ← 从来没被顶到过 | 1024 **不够** |

严格模式 `STRICT_TRANS_TABLES` 开着，所以表现是**报错**而不是静默截断 —— 这一点帮了忙。

**修**：`V55__gitee_token_columns_widen.sql`

| 表 | 列 | 改前 | 改后 | 依据 |
|---|---|---|---|---|
| `gitee_account` | `access_token` | `varchar(1024)` | `text` | JWT 密文可超 1024 |
| `gitee_account` | `refresh_token` | `varchar(1024)` | `text` | 同为 JWT |
| `gitee_account` | `scope` | `varchar(255)` | `varchar(1024)` | 上界是权限词表（实测最长 106 字符） |
| `gitee_tenant_config` | `access_token` | `varchar(1024)` | `text` | 同一类令牌，同一类缺陷 |
| `gitee_tenant_config` | `token_scope` | `varchar(255)` | `varchar(1024)` | 同上 |

**放宽范围是照证据取的，不是「整表都改成 TEXT」**：`gitee_username`(128，实测 9 字符)、
`gitee_name`(128)、`avatar_url`(512，实测最长 86) **都没动** —— 它们的上界由托管方的身份字段
定义，与令牌形态无关。这几列也都不在建索引里，放宽无副作用。

**顺带两处**：

1. **写库前打一行「只记长度、不记值」的日志**（`GiteeAccountService.callback()`）：
   `Gitea 绑定：令牌长度 token=861 refresh=0 scope=46`。
   托管方令牌的**形态**是会变的；长度打在写库**之前**，下次再遇列宽不足，
   日志里直接就有实际规模，而不是只拿到一句 `Data too long`。
2. **失败文案新增「截断」分支**（`ProviderFailureText.forOauthBind()`）：
   `Data too long for column ...` → 「**平台侧存储列宽不足以保存 Gitea 返回的令牌（属平台缺陷，与你的账号无关）**：
   请把下面原文反馈给平台运维，由其扩充列宽后重试。」
   它必须排在 `scope`/`permission` 分支**之前** —— 列名恰好叫 `scope` 时
   （`Data too long for column 'scope'`）也含 `scope`，顺序错了就会被误判成「用户没勾权限」。
   单测专门钉住这一条，以及「截断时不得引导用户去重新授权」。
   今后同类缺陷**再犯时文案上就指向平台**，而不是把一句 SQL 错误丢给用户。

### 6.1 为什么 21 个套件全绿，却没发现这件事

这是本轮**最值得记下的一条**：用户点「绑定」报错的那一刻，
`e2e_gitea_live` 75/75、`e2e_full_system` 145/145、`e2e_v48_gitee` 116/116 …… 全部绿。

原因不是断言写松了，而是**这条路径压根没有覆盖**：所有套件都不做真实的浏览器授权
（做不到，见 §9），于是「回调 → 换令牌 → 取身份 → **加密 → 写库**」里的**写库那一步**
从来没被任何断言碰过。「没有覆盖」与「覆盖了但写松」是两件事 —— 前者不会让任何断言变红，
所以「全绿」和「能绑定」在这里是两个独立命题。

**补的口子**：`scripts/e2e_gitea_live.py` 新增 `[G0a] 列宽闸门`，4 条断言：

| 断言 | 判据 |
|---|---|
| `G0a.access_token` / `refresh_token` 容量 ≥ 4096 | 容得下 1000 字符 JWT 的密文（≈1372）并留 3 倍余量 |
| `G0a.scope` 容量 ≥ 512 | 上界是权限词表（实测最长 106 字符） |
| `G0a.4` 严格模式开启 | 非严格模式下超长会**静默截断**：密文被截断 ⇒ 解密必失败，且事后查不出是哪一次写坏的，比报错更糟 |

两处设计取舍是刻意的：

- **阈值按证据分别取**（令牌 4096 / scope 512），不为「看起来整齐」一刀切；
- 它**不读任何凭据、不碰 Gitea**，并且**放在 `main()` 最前面**，其余全部 BLOCKED 时它也会说话。
  这次教训恰恰是「闸门依赖的前提不成立时，闸门自己就不跑了」。

## 7. 复验（改完即跑，不是「应该没问题」）

| 验证 | 结果 |
|---|---|
| **绑定真实成功** | `gitee_account` id=98：tenant 0 / user 1（`admin`）→ Gitea `liujiejie`(11)，`bound_at=15:20:50` |
| 成功那一刻的令牌规模 | 日志 `Gitea 绑定：令牌长度 token=858 refresh=858 scope=0`；**入库密文 1188 字符**（旧列 1024 ⇒ 必被拒） |
| 后端健康 + 接线 | `UP` · `provider=gitea` · `providerLabel=Gitea` · `configKey=aioa.gitea` · `enabled=true` |
| 授权地址使用的 client_id | `a2e8f7bd-8f0b-4a2f-a1e5-345b5741b0cd` ≡ 新应用（一致） |
| Flyway 最新版本 | `55` (gitee token columns widen) |
| 列型实测 | `gitee_account.access_token=text` · `refresh_token=text` · `scope=varchar(1024)` · `gitee_tenant_config.access_token=text` · `token_scope=varchar(1024)` |
| 容量实证（真库临时表，严格模式） | 4096 字符密文写入成功且读回等长（未被截断） |
| `scripts/e2e_gitea_live.py` | **79 / 79**（含新增 `G0a` 四条） |
| `scripts/e2e_full_system.py --no-browser` | **145 / 145**（已知缺口 0） |
| `scripts/_check_gitea_ui_provider.py` / `_check_gitea_cfg_failure_ui.py` | **17 / 17** / **16 / 16** |
| `aioa-gitee` 单测（`mvnw clean package` 全量） | **158 / 158**（150 + 设置端 4 + 控制器 4）· BUILD SUCCESS |
| 前端类型检查 | `vue-tsc --noEmit` exit 0 |
| `e2e_v51_gitee_init` / `e2e_v48_gitee`（Gitee 桩接线） | **50 / 50** / **116 / 116** |

### 7.1 顺带修掉一处「套件自己会说谎」的地方（与本缺陷无关，但会掩盖真回归）

首次跑 `e2e_v48_gitee` 时**连续两次稳定红 2 条**（`FR-9.2/FR-9.3`：Gitee 侧手工添加的协作者
未纳入平台成员列表）。**先查库否掉它**，而不是先动断言：

- 库证据：`gitee_repo_member` 里那行**确实写入了** ——
  `gitee_username=gitee_manual_dev`、`source=GITEE`、`sync_status=SYNCED`、`created_at=14:42:36.208`；
- 日志证据：`校准发现 Gitee 侧新增协作者 project=129 login=gitee_manual_dev`；
- 真因：`/gitee/calibrate` 是**租户级全量入队**，目标项目排在既有项目之后；
  该租户已积到 **46 个 ACTIVE 项目**，队列排到目标项目约 **95s**，而套件等的是**固定 90s** ⇒ 差几秒。

**修法**：判据从「等固定 90 秒」换成**确定性信号** —— 先等 `GET /gitee/tasks/stats` 的
`PENDING+RUNNING==0`（队列排空），**再**断言成员在不在；超时只作安全网（600s）。
改完连跑两次 **116/116 · 116/116**。

> 断言覆盖面没有变小：仍然是「成员必须存在、且 `source=GITEE`、`external=true`」。
> 被换掉的是**等待判据本身** —— 由「等固定 90 秒」改为「等队列排空」。
> 验收标准：改完后它仍能拦住「外部协作者不入库」这一类 bug（用移除该入库逻辑来验，会红）。

同一个病在 `e2e_gitea_live` 的 `G9.2 / G9.4 / G9.7` 上也犯了：它们等的是**租户级**队列，
却写死 90s。实测 tenant 2 有 **8 个 ACTIVE 项目** ⇒ 一次 `/gitee/calibrate` 入队 8 条 SYNC_ALL，
每条都要真连 Gitea 拉仓库与成员，90s 正好卡在边缘（跑出过一次 `残留=1`）。
**修法**：等待预算按工作量推导 `budget = 30 + 30 × ACTIVE项目数`，断言不变，
并把预算与实际项目数打进断言明细（`残留=0 预算=270s（ACTIVE项目=8）`），
让下一次「为什么给这么多时间」在输出里就能自证。

## 8. ✅ 闭环达成（2026-09-18 15:20:50）

你在浏览器里完成了授权，后端随即落库成功：

```
Gitea 绑定：令牌长度 token=858 refresh=858 scope=0        ← 这行日志就是新加的「只记长度」诊断
Gitee 绑定成功 tenant=0 user=1 gitee=liujiejie(11)
```

`gitee_account` id=98 的关键字段：`provider=gitea` · `gitee_uid=11` · `gitee_username=liujiejie`
· **`access_token` 密文 1188 字符**（`refresh_token` 同为 1188）。

**1188 这个数字本身就是证据**：旧的 `VARCHAR(1024)` 在这一步必然拒绝，V55 正好把它接住了。
前面两个缺陷至此全部消失 —— 换令牌不再 `unauthorized_client`，写库不再 `Data too long`。

**终验：存进去的令牌是「活的」，不只是「存进去了」** —— 把库里那串密文按
`SHA-256(token-enc-key) → AES-256-GCM` 解出来，拿去真实 Gitea 调接口：

| 检查 | 结果 |
|---|---|
| 密文可解（说明 provider 分段的加密键接线正确） | ✅ |
| 明文长度 | **858**，与入库前那行诊断日志 `token=858` **逐字一致** ⇒ 未被截断 |
| `GET /api/v1/user`（真实 Gitea） | **200** · `id=11` · `login=liujiejie` ⇒ 与库中登记身份一致 |
| `GET /api/v1/user/repos` · `/user/orgs` | **200** · 11 个仓库 · 组织 `['AI-OA']` ⇒ 令牌**可用** |

绑定链路至此端到端闭合。

### 8.1 你随后发来的两个现象：直接成因是我重启了后端

你说「认证通过但解绑刷新失败，还有切换部门时出现[报错]」，截图（**15:23:40**）内容是：

- toast：`无法获取仓库联动配置，模块可能未启用`
- 页头：`项目与仓库（Gitee 联动）`
- 横幅：`仓库联动模块未启用 / 后端尚未配置 aioa.gitee.*…请联系系统管理员开启配置`

**这三句全是错的，而且成因在我**：为了让 V55 生效，我在 **15:21–15:25** 停了后端重建。
v63 日志在 `15:20:50`（你绑定成功那一刻）之后**一条记录都没有** ⇒ 服务不在，
前端经 Vite 代理拿到 500 ⇒ 落到 fallback 文案。
数据库里绑定行至今 `alive=1`、`deleted_at=NULL` ⇒ **那次解绑请求根本没到后端**。
「切换部门时出现」是同一件事：该页每次切换都会重新拉 `GET /gitee/config`。

**换绑很简单**（服务现已恢复）：先在「我的 Gitea 账号」点「解绑」，再点「绑定 Gitea 账号」走一次授权。

### 8.2 但它顺带暴露三个真缺陷（与重启无关，都会再犯）

| # | 缺陷 | 修法 |
|---|---|---|
| D-10 | **把「服务不可达」说成「去改配置」**：`loadConfig()` 的 catch 与 `enabled===false` 共用同一个 `moduleEnabled=false`，于是网络/5xx 也渲染「后端尚未配置 xxx.*」 | 拆出 `configError` 状态 + 专属 error 横幅 + **「重试」按钮**；只有**服务明确回 `enabled=false`** 才显示「未启用」 |
| D-11 | **不知道托管方却自称托管方**：页头用 `pName`（回落 `'Gitee'`）拼串 ⇒ gitea 接线下服务不可达时整页回落成「Gitee 联动」 | 新增 `providerKnown`（= 配置是否真取到）；不知道时页头只写「项目与仓库」，副标题也不指名托管方 |
| D-12 | **成功页反向告警**：「非官方站点」判定**写死比 `gitee.com`**，而自建 Gitea 的真实站点 `172.16.8.249` 本来就不是 gitee.com ⇒ **绑定成功后**显示「⚠ 本次授权未经过真实 Gitea」 | 判定收进随 provider 变的 `RepoProviderSettings.authorizeHostIsSandbox()`（Gitea 侧参照 `web-base-url` 域）；控制器不再自行比较域名 |
| — | `unbind()` 归因混淆：解绑**成功**后的「刷新」失败也报「解绑失败」，用户会以为没解开而反复点 | 拆成两句：「解绑失败」（真失败）与「已解绑，但刷新页面数据失败：…」 |

**新增防回归**：`RepoProviderSettingsTest` +4（真实自建 Gitea 不得判成桩 / 指向桩要判可疑 /
缺参照物按可疑 / Gitee 侧语义不变）；`GiteeOauthControllerTest` 4 条（成功页不得告警、
指向桩仍 fail-loud、解析不出主机名不编造、判据必须来自设置端）；
新增界面探针 `scripts/_check_gitea_cfg_failure_ui.py`：用 Playwright **拦截 `/gitee/config`**
（`abort` 与 HTTP 500 两种形态）重现你截图那个场景，断言**不得**出现
「尚未配置 / aioa.gee* / Gitee 联动」，且点「重试」能自愈 —— **16 / 16**。

## 9. 顺带说明：为什么不是「你密钥复制错了」

三重证据指向托管方侧：① 你截图里登记页显示的串与 `.env.gitea-real` **逐字节相同**；
② 传错值与该正确值返回**完全一致**的错误；③ 新建应用立刻就能通过校验。
唯一动作是**换掉那个已失效的应用登记**，无需你改任何配置。

