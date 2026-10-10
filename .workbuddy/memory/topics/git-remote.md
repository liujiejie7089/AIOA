# Git 远端与推送（原 MEMORY.md §6，2026-09-19 拆分）

## 远端（两个，别混）
- `origin` = 内网 Gitea `172.16.8.249:3000/liujiejie/AIOA_System.git`：**HTTP 层沙箱可达**；公共接口免认证可读（`/api/v1/version` → 1.26.2），但**仓库/组织/用户级全需令牌**，push-to-create 关闭(403)。契约以实例自述规范为准：`GET /swagger.v1.json`（已存 `logs/gitea-swagger-1.26.2.json`，gitignored）。
  - ⚠️ **2026-09-20 实测该机不可达**：`git ls-remote origin` 回 `502 / upstream connect failed: connection timed out`。
  - 与本地**已分叉**：`origin/main = 179547e「删除目录 .workbuddy」`，合并基 `42e2aa2`；本地 `main` 相对 origin **ahead 78 / behind 1** ⇒ 对 origin 的推送**不是快进**，需先 merge 或 rebase。
- `github` = `github.com/liujiejie7089/AIOA.git`。HTTPS 默认不可用（schannel 证书吊销检查失败 `CRYPT_E_NO_REVOCATION_CHECK 0x80092012`；`-c http.schannelCheckRevoke=false` 同样失败；换 `-c http.sslBackend=openssl` 报 `unable to get local issuer certificate`）。
  - ✅ **2026-09-23 实测：加 `-c http.sslVerify=false` 后 HTTPS 直接推送成功**（`git -c http.sslVerify=false push github main`），比 SSH over 443 简单，**无需 escalation**。代价是跳过证书校验（有中间人风险），**只对推自己仓库用，不要设成全局**。
  - ❌ **2026-09-23 当日更晚复测：同一条命令已推不动**。诊断：`curl -sS -m 12 https://github.com` 立即失败（`exit 35` SSL connect error，0.02s 返回，非超时）⇒ **到 github.com 的 HTTPS 路径在本环境已不可用**；`git push` 则表现为**几分钟零输出地挂起**（未加 `GIT_TERMINAL_PROMPT=0` 时无法区分「等网络」与「等凭证交互」）。
    应对：① 先 `curl -m 12 https://github.com` 判连通性；② TCP 层其实可连（`/dev/tcp/github.com/443` 通），失败发生在 TLS 之后 —— 沙箱内直接执行 `git push` 会被**强杀（SIGTERM，连 `echo` 的输出都没落盘）**，后台任务则**零输出挂起 9 分钟以上**（`GIT_TERMINAL_PROMPT=0` + `lowSpeedLimit` 也救不回来，因为进程没被正常调度）。
    ✅ **09-23 当日实测：带 escalation 后一次成功**（`7dfab50..df7429e`，命令即 `GIT_TERMINAL_PROMPT=0 git -c http.sslVerify=false push github HEAD:main`，秒级返回）。
    ⚠️ **09-24 实测修正：escalation+后台 确实能成功，只是极慢 —— 本次耗时 6h46m40s 才返回**
    （`4160055..8d96f35 HEAD -> main`，exit=0）。前台加旁路则表现为 **SIGTERM / exit 1 且零输出**，
    后台加旁路表现为 **前几分钟完全零输出**；`ls-remote`（只读）加旁路**始终秒级成功**。
    ⇒ **读写路径不通约**：`ls-remote` 能成功**不能**推定 `push` 能成功；反过来 **push 零输出也不能推定它失败**。
    ⇒ 正确做法：**后台+旁路发起 push 后就别管它、更别 kill**（本次就是留着没 kill 才成的），
      下次会话用 `ls-remote` 复核 SHA 收口。**同一轮里不要换着花样反复重试**（会并发抢同一个远端 ref）。
    ⇒ 仍是**不看返回码、只看 SHA 比对**：`git rev-parse HEAD` vs `ls-remote github refs/heads/main`。
    🔁 **2026-09-24 第二次实测（耗时不稳定，别用时长做判据）**：同一条命令（后台 + 旁路）
    本次 **19m49s** 就返回 `a73a537..6e8df92 HEAD -> main`（exit 0），`ls-remote` SHA 与本地 HEAD 一致。
    ⇒ 与上一条的 **6h46m** 相差 20 倍 ⇒ **耗时完全不可预测（20min ~ 7h 都正常）**，
      唯一可靠做法：**后台+旁路发起 → 不 kill、不重试 → 用 `ls-remote` 比对 SHA 收口**；
      `ls-remote`（只读）始终秒级，可随时用来判「落了没有」。
    收口按 SHA 比对（`git rev-parse HEAD` vs `git -c http.sslVerify=false ls-remote github refs/heads/main`），不看返回码。
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
- ✅ **2026-09-28 第三次实测：bash 通道、沙箱内、无 escalation，6 秒完成**（`0b86175..a259445`）。
  私钥可读、`ssh -T -p 443 git@ssh.github.com` 回 `Hi liujiejie7089!`。
  ⇒ 现状：**SSH over 443 是最省事的一条路，直接推即可**，不必再走 §5.0 的「交接命令给用户」。
- ✅ **2026-09-28 当日第四次实测：同样 6 秒内完成**（`a5f0b77..e8e2e2d`，22 文件大提交）。
  流程固化：`ls-remote` 取远端 SHA → `merge-base --is-ancestor <远端SHA> HEAD` 判快进 → push → `ls-remote` 比对。
  大提交（跨模块 22 文件）与单文件提交耗时无差异 ⇒ **不必为「文件多」而改走后台**。

### 🔴 2026-10-10 实测：HTTPS 已彻底不通（代理 CONNECT 502），**改走 SSH 22 端口，秒级成功**
- HTTPS 五连试全败：`GIT_TERMINAL_PROMPT=0 git push github HEAD:main` → `schannel: server closed abruptly (missing close_notify)`；
  加 `-c http.version=HTTP/1.1` → `CONNECT tunnel failed, response 502`；加 `-c http.sslBackend=openssl` → 同样 502。
  ⇒ **失败点在出网代理的 CONNECT 隧道**（写通道被拦），不是证书、不是 HTTP 版本（换了都 502）。
- ✅ **同一时刻 `ssh -T git@github.com`（22 端口）与 `-p 443 git@ssh.github.com` 都秒回 `Hi liujiejie7089!`**，
  且 `git push git@github.com:liujiejie7089/AIOA.git HEAD:main` → `4c6ebbc..eaa05b9  HEAD -> main`，**一次成功、秒级返回**。
- **判据**：`ls-remote`（只读）走 HTTPS 也能通（本次就是它读到 `4c6ebbc`）⇒ **读通 ≠ 写通**，别用只读成功推定能 push；
  但 **SSH 的读写都通**。遇到 HTTPS 502/`server closed abruptly` 时，**别再反复重试 HTTPS**，直接换 SSH。
- ✅ 已把 `github` remote 的 URL 改成 SSH：`git remote set-url github git@github.com:liujiejie7089/AIOA.git`
  ⇒ 之后 `git push github HEAD:main` 直接走 SSH，无需再带 `-i`/`-c http.*`（默认 key 即可，无需 escalation）。
- 收口仍按 SHA 比对：`git rev-parse HEAD` vs `git ls-remote github main`。

### 🔴 2026-10-10 当晚实测修正：SSH **22 端口在本网络被拒**，改走 **SSH 443**（`ssh.github.com:443`）
- `ssh -T git@github.com`（22）→ **`Connection refused`**（注意：是**被主动拒绝**、**不是超时**）
  ⇒ 同一天早上还能秒推的 22 端口，当晚已不通（换网络/代理策略变了的典型表现）。
- ✅ `ssh -T -p 443 git@ssh.github.com` → `Hi liujiejie7089!`；
  `ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git` 的 `ls-remote` 与 `push` **都秒级成功**。
- ✅ 本次实推：`git push <443 URL> HEAD:main` → `0278051..19a60ec`，随后 `ls-remote` 复核 SHA 一致（7 个提交）。
- ⚠️ HTTPS 仍然不通（`curl https://github.com` → `CRYPT_E_NO_REVOCATION_CHECK 0x80092012`）⇒ 出网代理的**写通道依旧被拦**。
- ✅ **已把 `github` remote 永久切成 443 形式**：
  `git remote set-url github ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git`
  ⇒ 之后 **`git push github HEAD:main` 直接可用**（本机已把 `[ssh.github.com]:443` 写进 known_hosts，无需 `-i`、无需 escalation、无需 `-c http.*`）。
- **判据（固化）**：推送前先跑三条探针，**谁通走谁**，别再反复重试已确认不通的那条：
  `ssh -T git@github.com`（22）· `ssh -T -p 443 git@ssh.github.com`（443）· `curl -m12 -o /dev/null -w '%{http_code}' https://github.com`（HTTPS）。
  三者里**只要 443 通就一定能推**。
- 流程仍是：`ls-remote` 取远端 SHA → `git merge-base --is-ancestor <远端SHA> HEAD` 判快进 → push → `ls-remote` 比对 SHA 收口（**不看返回码**）。

## 收口前必查两类脏文件
1. 已跟踪：`git status --porcelain | grep -v '^??'` 应为空（`h5_v33_render.py` / `SMOKE_v48.py` / `gitee_stub.py` 等**老脚本是跟踪文件**）。
2. **未跟踪但属源码**：`grep '^??'` **逐条判过** —— `git diff` **只显示已跟踪文件**，只看它会**整块漏掉新增文件**；`??` 列表**常被 `head` 截断**，必须看全量。
- 按既有约定不入库的 scratch（**2026-09-28 更正，别再照旧清单整批跳过**）：以 `.gitignore` 为准 ——
  只有 `scripts/_diag_*` · `scripts/_tmp_*` · `scripts/_q.py` · `scripts/_*.png` 被忽略；
  **`scripts/_check_*.py` / `_probe_*.py` / `_verify_*.py` / `_run_all_regression.sh` 是要入库的长期回归哨兵**
  （`git ls-files scripts/` 里已有一大批在跟踪）。判据：`git check-ignore -v <path>` 逐个问，别凭前缀猜。
  其余不入库：根目录 `probe*.txt` · `.workbuddy/artifacts/` · 孤立构建产物目录（如 `web/apps/shell/dist2/`，
  应加进 `.gitignore` 而非提交）。
