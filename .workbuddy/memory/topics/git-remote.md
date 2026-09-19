# Git 远端与推送（原 MEMORY.md §6，2026-09-19 拆分）

## 远端（两个，别混）
- `origin` = 内网 Gitea `172.16.8.249:3000/liujiejie/AIOA_System.git`：**HTTP 层沙箱可达**；公共接口免认证可读（`/api/v1/version` → 1.26.2），但**仓库/组织/用户级全需令牌**，push-to-create 关闭(403)。契约以实例自述规范为准：`GET /swagger.v1.json`（已存 `logs/gitea-swagger-1.26.2.json`，gitignored）。
  - ⚠️ **2026-09-20 实测该机不可达**：`git ls-remote origin` 回 `502 / upstream connect failed: connection timed out`。
  - 与本地**已分叉**：`origin/main = 179547e「删除目录 .workbuddy」`，合并基 `42e2aa2`；本地 `main` 相对 origin **ahead 78 / behind 1** ⇒ 对 origin 的推送**不是快进**，需先 merge 或 rebase。
- `github` = `github.com/liujiejie7089/AIOA.git`。**HTTPS 在本机不可用**（schannel 证书吊销检查失败 `CRYPT_E_NO_REVOCATION_CHECK 0x80092012`；加 `-c http.schannelCheckRevoke=false` 同样失败）⇒ **只能走 SSH over 443**。

## 沙箱限制（2026-09-20 更新：旧「推不了」结论已作废）
- ✅ **2026-09-20 实测沙箱内可直接推送成功**：`~/.ssh/id_rsa` 可读、`ssh.github.com:443` 可连，命令经 escalation 放行（工具回 `Sandbox bypassed (escalation-approved)`）。全程 **1 分钟内**完成，无需后台任务。
- ❌ 旧结论（2026-09-17：「读 `~/.ssh` 被沙箱硬拒、必须把推送命令交给用户手推」）**已失效，勿再据此拒绝执行推送**。
- 仍成立：Gitea 仓库/组织/用户级接口需令牌；`push-to-create` 关闭。

## 推 GitHub（2026-09-20 实测通过）
只有 SSH over 443 一条路：
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
