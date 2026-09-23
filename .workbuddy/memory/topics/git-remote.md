# Git 远端与推送（原 MEMORY.md §6，2026-09-19 拆分）

## 远端（两个，别混）
- `origin` = 内网 Gitea `172.16.8.249:3000/liujiejie/AIOA_System.git`：**HTTP 层沙箱可达**；公共接口免认证可读（`/api/v1/version` → 1.26.2），但**仓库/组织/用户级全需令牌**，push-to-create 关闭(403)。契约以实例自述规范为准：`GET /swagger.v1.json`（已存 `logs/gitea-swagger-1.26.2.json`，gitignored）。
  - ⚠️ **2026-09-20 实测该机不可达**：`git ls-remote origin` 回 `502 / upstream connect failed: connection timed out`。
  - 与本地**已分叉**：`origin/main = 179547e「删除目录 .workbuddy」`，合并基 `42e2aa2`；本地 `main` 相对 origin **ahead 78 / behind 1** ⇒ 对 origin 的推送**不是快进**，需先 merge 或 rebase。
- `github` = `github.com/liujiejie7089/AIOA.git`。HTTPS 默认不可用（schannel 证书吊销检查失败 `CRYPT_E_NO_REVOCATION_CHECK 0x80092012`；`-c http.schannelCheckRevoke=false` 同样失败；换 `-c http.sslBackend=openssl` 报 `unable to get local issuer certificate`）。
  - ✅ **2026-09-23 实测：加 `-c http.sslVerify=false` 后 HTTPS 直接推送成功**（`git -c http.sslVerify=false push github main`），比 SSH over 443 简单，**无需 escalation**。代价是跳过证书校验（有中间人风险），**只对推自己仓库用，不要设成全局**。
  - ❌ **2026-09-23 当日更晚复测：同一条命令已推不动**。诊断：`curl -sS -m 12 https://github.com` 立即失败（`exit 35` SSL connect error，0.02s 返回，非超时）⇒ **到 github.com 的 HTTPS 路径在本环境已不可用**；`git push` 则表现为**几分钟零输出地挂起**（未加 `GIT_TERMINAL_PROMPT=0` 时无法区分「等网络」与「等凭证交互」）。
    应对：① 先 `curl -m 12 https://github.com` 判连通性；② TCP 层其实可连（`/dev/tcp/github.com/443` 通），失败发生在 TLS 之后 —— 沙箱内直接执行 `git push` 会被**强杀（SIGTERM，连 `echo` 的输出都没落盘）**，后台任务则**零输出挂起 9 分钟以上**（`GIT_TERMINAL_PROMPT=0` + `lowSpeedLimit` 也救不回来，因为进程没被正常调度）。
    ⇒ 本环境下推 GitHub 需走 **escalation（沙箱旁路审批）** 或**由用户在自有终端执行**；不要在同一轮里反复重试等它。
    ✅ **同日实测：带 escalation 后一次成功**（`7dfab50..df7429e`，命令即 `GIT_TERMINAL_PROMPT=0 git -c http.sslVerify=false push github HEAD:main`，秒级返回）。
    ⇒ 判据固定为：**沙箱内直连 = 必失败（强杀/挂起），同一命令加沙箱旁路 = 成功**。所以先别试，直接带旁路。
    收口仍按 SHA 比对（`git rev-parse HEAD` vs `git -c http.sslVerify=false ls-remote github refs/heads/main`），不看返回码。
    内网 `origin` 当前可达（`info/refs` 返回 401 = 需凭据，TCP/HTTP 通）⇒ **内网链路与公网链路是两条独立的路径，不能互相推定**。
  - SSH over 443 仍是更安全的备选（见下节）。

## 沙箱限制（2026-09-20 更新：旧「推不了」结论已作废）
- ✅ **2026-09-20 实测沙箱内可直接推送成功**：`~/.ssh/id_rsa` 可读、`ssh.github.com:443` 可连，命令经 escalation 放行（工具回 `Sandbox bypassed (escalation-approved)`）。全程 **1 分钟内**完成，无需后台任务。
- ❌ 旧结论（2026-09-17：「读 `~/.ssh` 被沙箱硬拒、必须把推送命令交给用户手推」）**已失效，勿再据此拒绝执行推送**。
- 仍成立：Gitea 仓库/组织/用户级接口需令牌；`push-to-create` 关闭。

## 推 GitHub

### 首选：HTTPS + 跳过证书校验（2026-09-23 实测通过，最简）
```bash
GIT_TERMINAL_PROMPT=0 git -c http.sslVerify=false push github main
```
- `GIT_TERMINAL_PROMPT=0` 必加：否则凭证缺失时会挂在交互提示上不返回。
- 推送后用 `git -c http.sslVerify=false ls-remote github main` 比对远端 SHA 与本地 `git rev-parse HEAD`（注意 `git log github/main` 在未 fetch 时不可用，会报 ambiguous argument）。
- 不写进全局配置：`git config --get-regexp '^http\.'` 目前只有 `http.schannelcheckrevoke false`（历史遗留，留着无害）。

### 备选：SSH over 443（2026-09-20 实测通过）
```bash
GIT_SSH_COMMAND='ssh -i "C:/Users/刘尖尖/.ssh/id_rsa" -o IdentitiesOnly=yes \
  -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' \
  git push ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git main
```
- **必须显式 `-i`**（默认路径会因 HOME 中文用户名被 ssh 展开成乱码而找不到 key）。
- **推之前先 `git ls-remote <同上地址> refs/heads/main` 取远端 SHA**，再看 `git merge-base --is-ancestor <远端SHA> HEAD`
  是否为真 —— 判明是快进还是分叉，避免盲目 force。
- 收口校验**不靠 push 返回码**：比对本地 `git rev-parse HEAD` 与远端 `git ls-remote ssh://… refs/heads/main` 两个 SHA。

## 收口前必查两类脏文件
1. 已跟踪：`git status --porcelain | grep -v '^??'` 应为空（`h5_v33_render.py` / `SMOKE_v48.py` / `gitee_stub.py` 等**老脚本是跟踪文件**）。
2. **未跟踪但属源码**：`grep '^??'` **逐条判过** —— `git diff` **只显示已跟踪文件**，只看它会**整块漏掉新增文件**；`??` 列表**常被 `head` 截断**，必须看全量。
- 按既有约定不入库的 scratch：`scripts/_*` · 根目录 `probe*.txt` · `.workbuddy/artifacts/`。
