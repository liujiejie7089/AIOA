# 项目与运行环境（原 MEMORY.md §1，2026-09-19 拆分）

## 1. 项目与规格源
- AIOA = 地级市 AI 公共服务平台：Vue3 管理端 shell(`web/apps/shell`) + SpringBoot 3.3.5 单体(`server/` **11** Maven 模块) + MySQL8(库 `aioa`，root 无密码) + FastAPI agent(:8000) + 用户端单文件 H5(`user-client/index.html`)。方向 = **改代码对齐设计文档**（五层架构）。
- 规格源：`docs/10` 职责边界 · `14` 账号 · `15` 权限矩阵 · `16` 组织作用域 · `19` 七项优先事项 · `20` 全链路 E2E · `21` 层级流转 · `22` 登录口径 · `23` 权限审批与组织关联 · `28` 未开工项(§6 收口) · `29/30` Gitee 仓库联动 · `31` 模型网关 · `32` 向量库 Milvus(已落地，§11 收口)。

## 2. 重打包 / 重启
- **先停 :8080** → `cd server && bash mvnw -DskipTests -q clean package` → `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`。
- 系统 `mvn` 已损坏只能用 `mvnw`；**勿 `rm -rf target`**（用 `mvnw clean`）。
- fat-jar 判据：正常 ~82–110MB，若 ~20KB = **stripped-jar**（没停 JVM 就重打包，运行中 JVM 随后 `NoClassDefFoundError`）。
- **同一时刻只允许一个 Maven 构建**；`-pl <m>` **必须带 `-am`**。
- 改 `agent/app/**` 必须重启 uvicorn（非 `--reload`）。`bash start-all.sh` 一键起（幂等，日志 `logs/`）。
- **长驻服务必须作为后台任务的「前台进程」跑**（重定向日志、不加 `&`；`nohup &` / 脚本内 `&` 被沙箱回收 ⇒ 起来又立刻死）。
- 停后端：`PowerShell: Get-NetTCPConnection -LocalPort 8080 -State Listen | Stop-Process -Force`（`taskkill //PID` 在 git bash 下被转义成 `//PID` 必失败）。

## 3. 端口与探活
- 8080 / 8000 / 5173(5174/5175)；H5 :5181 **只绑 127.0.0.1**。
- 探端口 `netstat -ano|grep LISTENING|grep ":<port> "`，**不接 `| head`**。

## 4. 账号与口令
- 租户侧全 `User@123`（含 `dsj_admin`）；平台 `admin/Admin@123`。
- `zhangsan`(t0) · `dsj_admin`(t2 租户管理员) · `fagai_admin`(t2 inst1 机构管理员) · `fagai_liu`(t2 dept10 负责人) · `fagai_li`(t2 **dept11** 成员) · t9 全链 `znkj_admin`(3142)/`znkjyf_admin`(3143)/`znsfb_ldr`(3144)/`znsfb_m01`。

## 5. env 两套（★易踩）
- `deploy/.env.development` / `.env.production`，**键序完全一致（当前 101 项）**，对照表 `deploy/ENV.md`，用法 `set -a && . deploy/.env.development && set +a`。
- 占位约定：`CHANGE_ME__`(必替换) / `DEV_ONLY__`(仅本地) / `<xxx>`(按实填) / 留空(能力未启用)。
- ★值含空格 / `&` / `<` / `>` / `*` **必须双引号**，否则 shell 当运算符 ⇒ **整份文件解析中断**（实测只加载 4/78 键）。
- **前端 env 另成一档**：vite 只读各应用自己的 `.env`（`web/apps/shell/.env` 的 VITE_PORT/VITE_API_TARGET、`user-client/.env` 的 PORT/BACKEND_HOST/BACKEND_PORT），写进 `deploy/.env` **无效**；两份已加 `.gitignore` 例外。

## 6. Flyway
- 新增前 `ls server/*/src/main/resources/db/migration | sort -V | tail -3` 取实际最大+1（**当前 V60**：V59 bridge 工具网关 / V60 工作流加签·子流程·定义版本）。
- 已应用迁移**不可改**(checksum)，只能追加；文档里的版本号只是预测。

## 7. Gitee 接线（opt-in）
- `AIOA_GITEE_E2E=1 bash start-all.sh`（内部 source `scripts/gitee-e2e-env.sh`，变量一处维护）。
- **默认（不设）= 真实 `https://gitee.com`**；显式 opt-in 才把服务端接口 + 浏览器授权域一并指向桩 :8090。漏变量 ⇒ 套件全红且难查。
