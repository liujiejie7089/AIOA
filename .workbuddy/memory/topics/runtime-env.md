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
  ✅ **2026-10-02 订正（原文曾误写「两个入口已补齐」，实测只对了一半）**：
  - `start-all.sh` 后端段（第 78 行）**确实**带了 `-Dspring.flyway.validate-on-migrate=false` + 两个静态目录参数。
  - `start-backend.bat` **此前没有** flyway 参数，且挂着 `--spring.profiles.active=local` —— 而 `server/aioa-boot/src/main/resources/` 下**只有 `application.yml`，没有 `application-local.yml`** ⇒ 那是个静默 no-op（不报错、只是误导排障）。
  - 该 bat 在本轮已补齐三处（b1 删掉不存在 profile / b2 补 flyway 参数对齐 `start-all.sh` / b3 加「缺 `index.html` 就 `[WARN]`、缺 jar 就打印构建命令并 `exit /b 1`」的前置检查）；同一组参数换 18083 端口实测启动成功且 `/aioa/web/` 200（详见 `docs/42` §一）。
  - ⚠️ **往 `.bat` 里加 `echo` 一律用英文**：cmd.exe 按 OEM 代码页（中文机常 936）读文件，而文件是 UTF-8 ⇒ 中文 `echo` 必然乱码（`REM` 注释不受影响）。
  ⚠️ **对照实验结论（别再靠推理）**：不传参 ⇒ `/aioa/web/`、`/aioa/h5/` **均 404** 而 `/actuator/health` 200；传参 ⇒ 均 200。日志里报的是 `C:\app\h5` / `C:\app\web`。
  ⚠️ **写进 .sh 的路径必须过 `cygpath -m`**：git bash 的 `pwd` 返回 `/c/Users/...`，Windows 上的 Java **认不出**（会当成当前盘的 `\c\Users\...`）⇒ 目录「不存在」照样 404；jar 若用绝对路径同理（用相对路径则无此问题，因为脚本已 `cd` 到仓库根）。
  ⚠️ `%LOCALAPPDATA%` **不含 `Temp` 这一层**（`C:\Users\..\AppData\Local`）；组装 webroot 要么用 `%TEMP%`，要么拼 `%LOCALAPPDATA%\Temp`。写成 `${LOCALAPPDATA}/Temp` 才是对的。
  管理端临时 webroot（`%TEMP%\aioa-webroot`）会**随系统清理消失**；`ls` 一下，没了就从 `web/apps/*/dist` 重新组装（需含 `index.html`、`assets/`、`subapps/<name>/`）。
  改 shell 源码后**必须重打包 + 同步 webroot 才能在界面上看见**（只改 `src/` 是看不见的）：
  ```bash
  cd web/apps/shell && mv dist .dist-old && npm run build   # 见下「两个坑」，必须先 mv
  cp dist/index.html "$W/index.html" && cp -r dist/assets/. "$W/assets/"
  ```
  - **坑 1**：vite `emptyOutDir` 清理 `dist/assets`（70+ 文件）会撞沙箱
    `SAFE_DELETE_BULK_CONFIRM_REQUIRED`（阈值 50）⇒ **先把 `dist` 改名挪走再 build**
    （`.dist-old/` 已加入 `.gitignore`，勿提交）。
  - **坑 2**：沙箱的批量删除配额**按轮计**（`{"scope":"turn","threshold":50}`）——
    同一轮里连续删到第 40 个就被 SIGTERM，**不是命令写错**。要清 400+ 个陈旧 hash 产物时，
    用 **`mv` 移出服务目录**（如 `%TEMP%\aioa-webroot-stale-<HHMM>`，非删除）而不是硬删。
  核验已生效：`curl /aioa/web/assets/<新 chunk>` 返回 200 且旧入口 `index.html` 已指向新 hash。
- 系统 `mvn` 包装脚本已损坏只能用 `mvnw`；**勿 `rm -rf target`**（用 `mvnw clean`）。
  `server/mvnw` 用的是系统 Maven **3.9.11**（`D:/Program Files/develop/apache-maven-3.9.11`）。
  **`.tools/`（apache-maven-3.9.9 + 老的 `mvnw.sh` 临时启动器）已于 2026-10-09 删除** ——
  它被 `server/mvnw` 取代、全仓无引用，不要再去 `.tools/` 找 maven（见 `2026-10-09.md`）。
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
- ★★ **本机 HTTP 探活不可信（2026-10-10 实测，两次差点误判）**：环境里有沙箱代理
  `http_proxy=http://127.0.0.1:63414`（含大写与 `HTTPS_PROXY`）。它**时好时坏** ——
  同一 URL 经代理可能 200 也可能 **502**；`curl --noproxy '*'` 直连又可能得 **HTTP 000**。
  ⇒ **「服务在不在跑」只认 OS 级 `netstat` 监听 + 服务自身日志**，HTTP 码仅作辅助。
  **502 不代表没起**（多为代理自身坏了）；000 也不代表没起。
  实例：`:8000` 先返回 502（当时确实没起），随后代理整体退化、连 8080 也 502（当时两个服务都正常）。
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
- 新增前 `ls server/*/src/main/resources/db/migration | sort -V | tail -3` 取实际最大+1（**当前 V70**：
  V66 租户层级+域名 / V67 员工↔账号 / V68 移除子租户 / **V69 机构·租户删除审批流** / **V70 部门删除审批流**）。
  更早：V59 bridge 工具网关 / V60 工作流加签·子流程 / V61 模型手动添加+默认模型改 MiniMax / V62 默认 AI。
- 已应用迁移**不可改**(checksum)，只能追加；文档里的版本号只是预测。
- ★★ **血的教训（2026-10-02 实修，`docs/42` §一）**：`V68__remove_sub_tenant.sql` 在**被应用 20 分钟后**
  被改过（文件 mtime 09-28 12:03:17 vs `installed_on` 09-28 11:43:14），改动进了提交 `a259445`；
  加上 `application.yml` 开着 `validate-on-migrate: true` ⇒ **此后任何一次不带 `-D` 的启动都必然失败**：
  ```
  Migration checksum mismatch for migration version 68
  -> Applied to database : 2036569566
  -> Resolved locally    : -1046176694
  ```
  现场之所以还活着，是因为当时那个 8080 进程是**手工**加了 `-Dspring.flyway.validate-on-migrate=false` 起的
  —— **「服务在跑」不等于「启动入口是好的」**，排查启动问题时必须去看进程命令行，而不是看端口通不通。
- **修法**：先证明「改动是非语义的」（比对 `DESC sys_tenant` / `SHOW INDEX` 与 V68 的 DDL 是否一致，
  别一上来就 repair，否则会掩盖真实 schema 漂移），再一次性对齐历史行：
  ```sql
  UPDATE flyway_schema_history SET checksum=-1046176694 WHERE version='68' AND checksum=2036569566;
  ```
  然后**不带**绕过参数起一个临时端口实例，看到 `Schema up to date / No migration necessary` 才算修好。
- ⚠️ **其他环境（生产 10.0.0.3）历史行里同样存的是旧校验和**，升级时会以同样的方式启动失败；
  部署手册的升级步骤里必须包含这一次 repair。
- 「平台管理员创建专家模板」（2026-09-22）**无需新迁移** —— `ai_expert` 的 `tenant_id/source_template_id/template_version/visible_scope/kb_scope/default_enabled/category` + V34 审核列已够用。
- ★ **重打包前必须停掉 :8080**：运行中的 JVM 锁住 `aioa-boot-*.jar`，`repackage` 会以
  `Unable to rename ... .jar.original` 失败（2026-09-28 实测）。产物判据仍是体积 82–110MB。

## 7. Gitee 接线（opt-in）
- `AIOA_GITEE_E2E=1 bash start-all.sh`（内部 source `scripts/gitee-e2e-env.sh`，变量一处维护）。
- **默认（不设）= 真实 `https://gitee.com`**；显式 opt-in 才把服务端接口 + 浏览器授权域一并指向桩 :8090。漏变量 ⇒ 套件全红且难查。
