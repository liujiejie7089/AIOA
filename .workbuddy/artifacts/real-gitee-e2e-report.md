# Gitee 真机端到端测试报告

日期：2026-09-17 · 目标：真实跳转 gitee.com + 在 Gitee 上实际建仓 · 结论：**跳转链路已用真实浏览器证实打通；建仓链路服务端已真实打到 Gitee，但「真正建出仓库」被缺凭据阻断**

---

## 一、结论速览

| 环节 | 是否连通 | 证据强度 |
|---|---|---|
| 浏览器授权跳转 → 真实 gitee.com | ✅ **已证实** | 真实浏览器最终落 `gitee.com/login`，标题「登录 - Gitee.com」 |
| 管理端 UI 点击「绑定 Gitee 账号」→ 真站 | ✅ **已证实** | 未绑定账号真机点击，新标签落 `gitee.com`（10/10） |
| 服务端建仓外呼 → 真实 Gitee API | ✅ **已证实打到真站** | 日志 `POST /api/v5/orgs/aioa-demo-org/repos -> HTTP 401`，Gitee 英文原文错误 |
| **在 Gitee 上真正建出仓库** | ❌ **未达成** | 缺真实凭据（无 OAuth 应用、无令牌）＋ 出口 IP 被 Gitee 限流 |
| 未配置 OAuth 应用时的降级 | ✅ 通过 | `code=400` + 明确文案，未落 500 |
| 测试后环境还原 | ✅ 通过 | 切回桩接线：`SMOKE_v48` 32/32、`e2e_v48_gitee` 116/116 |

**一句话**：授权跳转这一环（正是昨天修复的那条）已经用真实浏览器端到端证实；建仓这一环的**代码路径**也真实打到了 Gitee，但**真正建出仓库需要真实账号与凭据，当前环境不具备** —— 这不是代码问题。

---

## 二、为什么建仓没做成：三重阻断

1. **平台内没有任何真实 Gitee 令牌**
   - `gitee_tenant_config` 仅 1 行（tenant 9）：`access_token = NULL`、`init_status = PENDING` —— 从未配置过企业令牌。
   - `gitee_account` 里的 OAuth 令牌全部是**桩签发的假身份**（`gitee_uid` 42083/42279/42366/42489/42511，用户名形如 `gitee_dev_212`），不是真 Gitee 的令牌。
2. **没有在真站注册的 OAuth 应用**
   - 生产默认 `aioa.gitee.client-id` 为**空**；本次测试用占位值 `aioa-e2e-client` 才能生成授权 URL。真站会在登录后拒绝该 client_id。
3. **本机出口 IP 已被 Gitee 限流**
   - `GET https://gitee.com/api/v5/version` → `403 Forbidden (Rate Limit Exceeded)`
   - 无令牌建仓 `POST https://gitee.com/api/v5/user/repos` → 同样 `403 Forbidden (Rate Limit Exceeded)`
   - ⇒ 即使补上令牌，本机出口也需等限流恢复（或改用带令牌的更高配额）才可能成功。

---

## 三、已完成的真机验证（含原始证据）

### 3.1 授权跳转（生产接线）

启动后端时**不设** `AIOA_GITEE_BASE_URL / WEB_URL / OAUTH_AUTHORIZE_URL`（即全部取默认真站），仅设 client-id/secret/redirect-uri/org：

```
POST /api/v1/gitee/bind/authorize  → HTTP 200
{
  "url": "https://gitee.com/oauth/authorize?client_id=aioa-e2e-client
          &redirect_uri=http%3A%2F%2F127.0.0.1%3A8080%2Fapi%2Fv1%2Fgitee%2Fbind%2Fcallback
          &response_type=code&state=…&scope=user_info+projects+pull_requests+issues+notes",
  "authorizeHost": "gitee.com",  "sandbox": false,  "warning": null
}
```

`authorizeHost = gitee.com`、`sandbox = false`、无警示 —— 与「桩接线」下的 `127.0.0.1` / `true` / 长警示文案形成对照，证明**授权域已与接口域解耦**。

### 3.2 真实浏览器打开该 URL

```
最终 URL : https://gitee.com/login?redirect_to_url=https%3A%2F%2Fgitee.com%2Foauth%2Fauthorize%3Fclient_id%3D…
页面标题 : 登录 - Gitee.com
```

浏览器确实**离开了本机**，到达真站，并被 Gitee 要求先登录（未登录时跳登录页并带 `redirect_to_url` 回跳参数）。

可视证据：`A-real-gitee-authorize.png` —— 画面为**真实 Gitee 登录页**（Gitee logo、「企业级 DevOps 研发管理平台」、
手机/邮箱登录表单、「其他方式登录」、页脚 `© Gitee.com 关于我们 使用条款 帮助文档`）。这是「浏览器真到了 gitee.com」
最直观的证明。

### 3.3 真实 UI 点击（未绑定账号 `znsfb_m02`）

真机登录管理端 → 「项目与仓库」→ 点「绑定 Gitee 账号」：

```
[PASS] B1.Gitee 页渲染（我的 Gitee 账号锚点）
[PASS] B2.未绑定态出现「绑定 Gitee 账号」按钮
[PASS] B3.新标签真实落到 gitee.com   host=gitee.com
[PASS] B4.页面无控制台 error
真机授权跳转验证：10/10 通过
```

截图：`B1-gitee-page.png`（管理端 Gitee 页真机渲染）。
⚠️ `B3-popup-gitee.png` 是**空白图**（弹窗截图早于页面渲染完成），**不作为证据**；B3 的判据是
**程序读取的新标签最终 URL 主机 = gitee.com**。可视证据以 §3.2 的 `A-real-gitee-authorize.png` 为准。

### 3.4 服务端建仓：真实外呼（关键日志）

以 tenant 9 已绑定账号 `znkj_admin` 建项目（dept 101，组织 `aioa-demo-org`）：

```
项目已创建（待建仓）id=63 repo=dept101-1789621559
WARN GiteeClient - Gitee API POST /api/v5/orgs/aioa-demo-org/repos -> HTTP 401 code=0 msg=401 Unauthorized: Access token does not exist
WARN GiteeTaskService - Gitee 任务失败 id=404 type=CREATE_REPO err=401 Unauthorized: Access token does not exist
```

项目详情：`status=FAILED`、`errorMsg=401 Unauthorized: Access token does not exist`；任务表 `gitee_task.id=404`、`attempts=1`。

`401 Unauthorized: Access token does not exist` 是**真实 Gitee API 的英文原文**，桩不可能产出 ⇒ 服务端确实把请求发到了 `gitee.com/api/v5`。**建仓的代码路径是通的，被拒的是凭据。**

### 3.5 行为正确性（真机下未出现退化）

- **同步返回毫秒级**：建仓接口立即返回 `status=CREATING`，真实外网调用走后台任务，不阻塞请求。
- **401 不重试**：`GiteeTaskService` 用 `e.isRetryable()` 判定，`attempts=1` 即终止 —— 认证类错误不重复重试，正确。
- **失败可见**：上游原始错误同时落到项目 `errorMsg` 与 `gitee_task.last_error`，管理端可查，不是静默失败。
- **未配置 OAuth 应用的降级**：纯生产默认（client-id 为空）下 `bind/authorize` 返回 HTTP 200 + `code=400`、`Gitee OAuth 应用未配置（缺 aioa.gitee.client-id / client-secret）`，未落 500。

---

## 四、发现的问题（按影响排序）

### P1 · `/gitee/config` 不回显「OAuth 应用是否已配置」
回显字段只有 `enabled / orgConfigured / webhookBaseUrlConfigured / syncEnabled / purgeRepoOnDelete / roleOptions`，**唯独没有 client-id/secret 是否配置**。后果：管理端无法在点击前预判，管理员点了「绑定 Gitee 账号」才拿到 400。建议增加 `oauthConfigured`，未配置时在绑定卡片上直接给出「去配置」指引。

### P1 · 演示库残留 61 个「桩项目」，生产接线下一屏死链
`gitee_project` 现存 61 条（本次测试行已清理），地址全部是 `http://127.0.0.1:8090/aioa-demo-org/…`（另有 id=58 一条 `https://gitee.com/…`，是桩用 `/_stub/public-base` 造出的**展示值**，并非真实仓库）。切到生产接线后，一进「项目与仓库」就是一屏打不开的链接，且**真假混排无从分辨**。建议：演示数据复位脚本里一并重置 Gitee 项目，或对「地址与当前授权域不一致」的历史项目加显式标记。

### P1 · `webhook-base-url` 生产默认为空 ⇒ Webhook 链路不可能真实联通
本次实测 `webhookBaseUrlConfigured = false`。Webhook 是「Gitee → 平台」的反向回调，必须公网可达；配 localhost 或不配都**静默失效**（不报错）。当前演示环境等于从未真实验证过 Webhook 链路。建议在配置页显式标注「需公网可达，否则 Webhook 静默失效」。

### P2 · `redirect-uri` 默认 `http://localhost:8080/...` 与真站登记值必须逐字一致
真站 OAuth 应用登记的回调地址与平台 `redirect-uri` 必须**完全一致**；`localhost` 与 `127.0.0.1` 的差异会让真站报「回调地址不匹配」。这是接真实 Gitee 时最容易踩的一步，建议在文档与配置页都写清。

### P2 · 真机失败文案透出英文原文
`401 Unauthorized: Access token does not exist` 直接透给管理员。对排查有用，但建议**原文保留 + 附一句中文处置建议**（如「企业令牌或该账号的 OAuth 授权已失效，请重新绑定 / 更新令牌」）。

### P3 · 令牌失效后「重新授权」路径偏绕
已绑定账号的卡片只提供「解绑」（本次实测 `znkj_admin` 即此形态）。当令牌过期想重新授权时，用户需先解绑再绑定。建议在已绑定态增加「重新授权」。

### P3 · 接口路径风格不统一（文档性问题）
租户配置是 `GET /gitee/tenant-config`（连字符），而项目是 `/gitee/projects`、部门是 `/gitee/departments`。写客户端时容易误写成 `/gitee/tenant/config` 并拿到业务 404。（本次侦察时确实误打过一次，属调用方笔误，非产品缺陷，仅建议统一风格或在文档里标注。）

---

## 五、测试方法（可复现）

**接线切换**（把真站与桩互切，只靠环境变量，不改代码）：

```bash
# 真机（生产接线）：只设应用凭据，三个域名变量都不设 ⇒ 全取默认真站
AIOA_GITEE_SYNC_ENABLED=false \
AIOA_GITEE_CLIENT_ID=aioa-e2e-client AIOA_GITEE_CLIENT_SECRET=aioa-e2e-secret \
AIOA_GITEE_REDIRECT_URI=http://127.0.0.1:8080/api/v1/gitee/bind/callback \
AIOA_GITEE_ORG=aioa-demo-org AIOA_GITEE_BIND_RETURN_URL=http://127.0.0.1:5173/gitee/projects \
  C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -jar server/aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar

# 桩接线（回归基线）：source 脚本里的 9 个变量，授权域一并指向 :8090
cd "C:/Users/刘尖尖/WorkBuddy/aioa" && . scripts/gitee-e2e-env.sh && <启动后端>
```

**探针脚本**（本次新增，均为本地 `_` 前缀 scratch，不入库）：
- `scripts/_diag_real_gitee_recon.py` —— 凭据/接线清点
- `scripts/_diag_real_gitee_probe.py authorize|create [账号]` —— 授权响应 / 建仓跟踪
- `scripts/_diag_real_gitee_browser.py [未绑定账号]` —— 真实浏览器跳转 + UI 点击

**判定「跳转是否到了真站」的可靠判据**（比断言 URL 字符串更硬）：看浏览器**最终落点主机**与**页面标题**（真站未登录会到 `gitee.com/login`，标题含 `Gitee.com`），而不是只看平台返回的 URL。

---

## 六、如何把最后一步做完（补齐真实凭据后）

1. 用**本机浏览器**登录 gitee.com，在「设置 → 第三方应用」创建 OAuth 应用，回调地址填 `http://127.0.0.1:8080/api/v1/gitee/bind/callback`（与平台 `redirect-uri` 逐字一致），拿到 client-id / client-secret。
2. 以企业管理员身份在平台「项目与仓库 → 企业令牌」提交一个具备 `projects` 权限的**个人访问令牌**，或直接走 OAuth 绑定。
3. 用上表「真机」接线重启后端，重跑 `scripts/_diag_real_gitee_browser.py`：此时应能真正完成授权并在真站建出仓库。
4. 注意出口 IP 限流：若仍见 `403 Rate Limit Exceeded`，需等限流窗口恢复或换出口。

---

## 七、本次测试对现有代码的改动

**无。** 只切换了启动环境变量（测试后已还原为桩接线），新增的是本地诊断脚本与截图，产品代码一行未动。
