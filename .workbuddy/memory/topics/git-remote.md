# Git 远端与推送（原 MEMORY.md §6，2026-09-19 拆分）

## 远端
- `origin` = 内网 Gitea `172.16.8.249:3000`：**HTTP 层沙箱可达**；公共接口免认证可读（`/api/v1/version` → 1.26.2），但**仓库/组织/用户级全需令牌**，push-to-create 关闭(403)。
- **契约以实例自述规范为准**：`GET /swagger.v1.json`（已存 `logs/gitea-swagger-1.26.2.json`，gitignored）。

## 沙箱限制（重要）
- ⚠️ **2026-09-17 起本沙箱内推不了** —— 读 `~/.ssh` 被沙箱策略**硬拒**（`dangerouslyDisableSandbox` 同样无效）⇒ **本地提交照做，推送命令原样交给用户在本机终端执行；绝不写成「已推送」，也不要反复重试同一路径。**

## 推 GitHub（换到允许读密钥的环境）
只有 SSH over 443 一条路：
```bash
GIT_SSH_COMMAND='ssh -i "C:/Users/刘尖尖/.ssh/id_rsa" -o IdentitiesOnly=yes \
  -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no' \
  git push ssh://git@ssh.github.com:443/liujiejie7089/AIOA.git main
```
- **必须显式 `-i`**（默认路径会因 HOME 中文用户名被 ssh 展开成乱码而找不到 key）；约 5–8 分钟，**用后台任务**。
- 收口校验**不靠 push 返回码**：比对本地 `git rev-parse HEAD` 与远端 `git ls-remote ssh://… refs/heads/main` 两个 SHA。

## 收口前必查两类脏文件
1. 已跟踪：`git status --porcelain | grep -v '^??'` 应为空（`h5_v33_render.py` / `SMOKE_v48.py` / `gitee_stub.py` 等**老脚本是跟踪文件**）。
2. **未跟踪但属源码**：`grep '^??'` **逐条判过** —— `git diff` **只显示已跟踪文件**，只看它会**整块漏掉新增文件**；`??` 列表**常被 `head` 截断**，必须看全量。
- 按既有约定不入库的 scratch：`scripts/_*` · 根目录 `probe*.txt` · `.workbuddy/artifacts/`。
