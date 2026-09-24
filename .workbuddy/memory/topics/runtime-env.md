# 项目与运行环境（原 MEMORY.md §1，2026-09-19 拆分）

## 1. 项目与规格源
- AIOA = 地级市 AI 公共服务平台：Vue3 管理端 shell(`web/apps/shell`) + SpringBoot 3.3.5 单体(`server/` **11** Maven 模块) + MySQL8(库 `aioa`，root 无密码) + FastAPI agent(:8000) + 用户端单文件 H5(`user-client/index.html`)。方向 = **改代码对齐设计文档**（五层架构）。
- 规格源：`docs/10` 职责边界 · `14` 账号 · `15` 权限矩阵 · `16` 组织作用域 · `19` 七项优先事项 · `20` 全链路 E2E · `21` 层级流转 · `22` 登录口径 · `23` 权限审批与组织关联 · `28` 未开工项(§6 收口) · `29/30` Gitee 仓库联动 · `31` 模型网关 · `32` 向量库 Milvus(已落地，§11 收口)。

## 2. 重打包 / 重启
- **先停 :8080** → `cd server && bash mvnw -DskipTests -q clean package` → 启动见下（**必须带静态目录参数**）。
- ★**本机启动后端的完整命令（缺参数 ⇒ `/aioa/h5/`、`/aioa/web/` 全 404，`e2e_v63` 的 C8/C9/C11 必红）**：
  ```
  cd server && "$JAVA" -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar \
    --aioa.web.h5-dir=C:/Users/刘尖尖/WorkBuddy/aioa/user-client \
    --aioa.web.web-dir=C:/Users/刘尖尖/AppData/Local/Temp/aioa-webroot
  ```
  原因：`aioa.web.h5-dir`/`web-dir` 默认值是**容器内**路径 `/app/h5`、`/app/web`（`application.yml` 只给 `${AIOA_WEB_H5_DIR:/app/h5}`，本机没有这俩 env）⇒ 在 Windows 上落到 `C:\app\h5`，不存在。
  **启动期就会打 WARN 指名要 `--aioa.web.h5-dir` 覆盖**（`AioaStaticConfig`），重启后**先 grep 这行确认拿到的是「（存在）」而不是「不可用」**，别等套件红了才回头查。
  管理端临时 webroot（`%TEMP%\aioa-webroot`）会**随系统清理消失**；`ls` 一下，没了就从 `web/apps/*/dist` 重新组装（需含 `index.html`、`assets/`、`subapps/<name>/`）。
- 系统 `mvn` 已损坏只能用 `mvnw`；**勿 `rm -rf target`**（用 `mvnw clean`）。
- fat-jar 判据：正常 ~82–110MB，若 ~20KB = **stripped-jar**（没停 JVM 就重打包，运行中 JVM 随后 `NoClassDefFoundError`）。
- **同一时刻只允许一个 Maven 构建**；`-pl <m>` **必须带 `-am`**。
- 改 `agent/app/**` 必须重启 uvicorn（非 `--reload`）。`bash start-all.sh` 一键起（幂等，日志 `logs/`）。
- **agent 有「两个 venv」且行为不同 —— 起之前先确认用哪个**（2026-09-22 实测）：
  - `agent/.venv`（Python 3.13.14）= 装了 `uvicorn[standard]`（含 httptools 0.8.0 / websockets / watchfiles）；本机最近一次运行的 agent 就是它。
  - `envs/default`（托管 venv，`start-all.sh` 里 `$PY` 指向它）= 原先只有裸 `uvicorn`，**2026-09-22 已补装 httptools**（清华镜像无 cp313 win 轮子，要 `-i https://pypi.org/simple`）。
  - **差异会改变 HTTP 语义**：`--http httptools` 会丢 h2c 升级请求的 body（见 `pitfalls.md` #55/#56），`--http h11` 会保住它。
  - 故 `start-all.sh` **已显式写死 `--http httptools`**（与 `deploy/Dockerfile.agent` 装 `uvicorn[standard]` 的生产口径一致）。改这行前先读 #56。
  - 判别当前实例在跑哪个实现：`python scripts/_probe_agent_h2c.py`（422=httptools / 200=h11）。
- **长驻服务必须作为后台任务的「前台进程」跑**（重定向日志、不加 `&`；`nohup &` / 脚本内 `&` 被沙箱回收 ⇒ 起来又立刻死）。
- 停后端：`PowerShell: Get-NetTCPConnection -LocalPort 8080 -State Listen | Stop-Process -Force`（`taskkill //PID` 在 git bash 下被转义成 `//PID` 必失败）。停 agent 同法换 `-LocalPort 8000`。
- 数据库直连：`/d/dev/mysql/mysql-8.4.10-winx64/bin/mysql.exe -uroot aioa -e "…"`（表结构别猜：`agent_worker_run` 的列是 `error_msg`，不是 `error`）。
- 本环境 **PowerShell 工具不回显 stdout**（返回 `Command completed with exit code 0` 但无输出）⇒ 要取值就 `Set-Content logs/_x.txt` 再 `Read`；**别拿它的输出做判据**。

## 3. 端口与探活
- 8080 / 8000 / 5173(5174/5175)；H5 :5181 **只绑 127.0.0.1**。
- 探端口 `netstat -ano|grep LISTENING|grep ":<port> "`，**不接 `| head`**。
- **单端口入口（docs/33，已落地）**：`:8080` 一个端口服三块 —— `/aioa/h5/`（H5）、`/aioa/web/`（管理端产物）、
  `/aioa/api/`（接口，进安全链前被剥成 `/api`）。**`/api/**` 根路径原样保留**（44 个既有套件 + 现场脚本零改动）。
  两个前缀并存是**刻意的**，不是遗留。
  ⚠️ **2026-09-24 更新：compose 现在有一个「可选」的入口 nginx**（用户要求 `10.0.0.3/web`→管理端、
  `10.0.0.3/user`→用户端）—— 配置 `deploy/nginx/aioa-entry.conf`、compose 服务 `aioa-nginx`（**只监听 80**，
  `81` 仍不存在）。**后端 :8080 的单端口入口照旧独立可用**（nginx 只是短路径别名，去掉它不影响任何套件）。
  口径：`/web` **302 跳** `/aioa/web/`（SPA base 限制，rewrite 会白屏）；`/user/` **rewrite** 到 `/aioa/h5/`
  （H5 自包含、API base 由 `location.pathname` 推）。细节见 `deploy/生产部署手册.md` §0.1。
  静态托管实现：`server/aioa-boot/.../web/AioaStaticConfig.java`（SPA 回退 + 扩展名白名单 + 防 `../` 穿越）；
  前缀剥离：`AioaPathPrefixFilter.java`（`setOrder(Integer.MIN_VALUE)`，**必须早于安全链**，否则登录 401）。
  改这四类东西后必跑：`scripts/_check_single_port.py`（**11** 项含 `c11_nginx_entry` + **21** 项负向自检）、
  `deploy/ops/compose-lint.py`、`scripts/e2e_v63_single_port.py`。

## 4. 账号与口令
- 租户侧全 `User@123`（含 `dsj_admin`）；平台 `admin/Admin@123`。
- 现库（2026-09-20 起）= **`sys_user` 仅 16 行**：t0 `zhangsan` · t2 `dsj_admin`(租户管理员)/`fagai_admin`(inst1 机构管理员)/
  `fagai_liu`(dept10 负责人)/`fagai_li`(dept11 成员)/`shenpi_*`/`chengtou_*` · t3 `wjj_admin`/`wjj_xu`。
- ⚠️ **t9 全链（`znkj_admin`/`znkjyf_admin`/`znsfb_ldr`/`znsfb_m01`/`znsfb_m02`）与 `jyj_*`/`jyfzyjy_*` 已被清除**
  （2026-09-20「批次 4」，连软删行都没有）⇒ 依赖它们的**约 21 个既有套件本地不可运行**（判为「不可运行」，
  不是「通过」）。细节与归因见 `topics/e2e-suites.md`。

## 5. env 两套（★易踩）
- `deploy/.env.development` / `.env.production`，**键序完全一致（当前 101 项）**，对照表 `deploy/ENV.md`，用法 `set -a && . deploy/.env.development && set +a`。
- 占位约定：`CHANGE_ME__`(必替换) / `DEV_ONLY__`(仅本地) / `<xxx>`(按实填) / 留空(能力未启用)。
- ★值含空格 / `&` / `<` / `>` / `*` **必须双引号**，否则 shell 当运算符 ⇒ **整份文件解析中断**（实测只加载 4/78 键）。
- **前端 env 另成一档**：vite 只读各应用自己的 `.env`（`web/apps/shell/.env` 的 VITE_PORT/VITE_API_TARGET、`user-client/.env` 的 PORT/BACKEND_HOST/BACKEND_PORT），写进 `deploy/.env` **无效**；两份已加 `.gitignore` 例外。

## 6. Flyway
- 新增前 `ls server/*/src/main/resources/db/migration | sort -V | tail -3` 取实际最大+1（**当前 V62**：V59 bridge 工具网关 / V60 工作流加签·子流程·定义版本 / V61 模型手动添加+默认模型改 MiniMax / V62 默认 AI（既有专家 `general` + 参数键 `chat.default_expert_key`））。
- 已应用迁移**不可改**(checksum)，只能追加；文档里的版本号只是预测。
- 「平台管理员创建专家模板」（2026-09-22）**无需新迁移** —— `ai_expert` 的 `tenant_id/source_template_id/template_version/visible_scope/kb_scope/default_enabled/category` + V34 审核列已够用。

## 7. Gitee 接线（opt-in）
- `AIOA_GITEE_E2E=1 bash start-all.sh`（内部 source `scripts/gitee-e2e-env.sh`，变量一处维护）。
- **默认（不设）= 真实 `https://gitee.com`**；显式 opt-in 才把服务端接口 + 浏览器授权域一并指向桩 :8090。漏变量 ⇒ 套件全红且难查。
