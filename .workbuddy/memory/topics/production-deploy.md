# 生产部署（目标机 10.0.0.3）

> 2026-09-19 建立；**2026-09-20 目标机由 192.168.2.130 改为 10.0.0.12**；
> **2026-09-24 应用机由 `10.0.0.12` 改为 `10.0.0.3`**（用户确认口径：**只换应用机**；
> MySQL `10.0.0.5:13049` / Redis `10.0.0.7:6379` **不动**）。
> ⚠️ **同日更正**：当时我推断「Milvus 随应用机」→ 写成 `10.0.0.3:19530`，**这是错的**。
> 用户随后明确：**Milvus 一直在 `10.0.0.12`（可通）、无密码**，与应用机**不同机**。
> 已全量改回 `http://10.0.0.12:19530`（`docs/33` 里本来就写着 10.0.0.12，可佐证）。
> **2026-09-20 第二批：三件套全部落到已有外部实例** —— MySQL `10.0.0.5:13049`（**非默认端口**）/ 库 `aioa` / 用户 `aioa`；
> Redis `10.0.0.7:6379`（**有口令**，与早前「无口令」不同）；Milvus `19530` 无鉴权（**该行原写 10.0.0.3 有误，见上「同日更正」：Milvus 在 10.0.0.12**）。真实口令只在 `deploy/.env`。
> **2026-09-21 第三批（定案）：五件基础设施全在外部 / 用户不用边缘 nginx / MinIO 被证实未被使用。**
> **2026-09-24 第四批（覆盖上面那条「不用 nginx」）：用户要求短路径入口，compose 重新加入一个
> 「可选」nginx** —— `10.0.0.3/web`→管理端、`10.0.0.3/user`→用户端。见下方「★ 2026-09-24 入口 nginx」。
> 入口文档 = `deploy/生产部署手册.md`（含「§4.0 填写位置总览」+ §0.1 入口 Nginx + §5.2 静态前端放哪 + 验收 + 故障对照表）。

## ★ 定案（2026-09-21）：本次走「后端档」

- 用户口径：`目前不用nginx`；`我目前有mysql,redis,milvus,nginx，但都在其他服务器上，这些就不用下载了，直接连接`。
- ⇒ 叠加 `deploy/docker-compose.backend.yml`（**只加 ports，不改任何环境变量**）：
  `docker compose -f docker-compose.yml -f docker-compose.backend.yml up -d server agent`
- ⇒ **只起 2 个容器、只搬 2 张镜像**（`aioa-server` + `aioa-agent`）；
  不需要 `nginx:1.27-alpine` / `aioa-web` / `minio/minio`。
- 宿主端口 **8080（后端 API）/ 8000（agent，排查用）**；**不再是 80/81**。
- ⚠️ **代价（必须转告用户）**：80=H5、81=管理端 的静态没人托管了。解法见手册 §5.2：
  · H5 = 仓库里的 `user-client/index.html`（**单文件、零构建**）；
  · 管理端 = `aioa-web` 镜像里的 `/usr/share/nginx/html`，**不必跑容器**：
    `docker create _tmpweb aioa-web` + `docker cp _tmpweb:/usr/share/nginx/html/. <root>` + `docker rm _tmpweb`。
  · 宿主 nginx 把 `/api/` 反代到 `http://10.0.0.3:8080/`（抄 `deploy/nginx/api-proxy.conf`）。

## ★ 2026-09-24 入口 nginx（**覆盖** 09-21 的「不用 nginx」）

- 用户口径变更：`我现在的服务器是10.0.0.3，你给我配置一下nginx，我希望用10.0.0.3/web访问管理端，
  10.0.0.3/user访问用户端`。⇒ 从「宿主自带 nginx 反代 `/api/`」升级为**compose 托管一个入口 nginx**。
- `deploy/nginx/aioa-entry.conf`（挂成 `nginx:1.27-alpine` 的 `conf.d/default.conf`），
  compose 服务 `nginx` / 容器 `aioa-nginx`、`ports: ["80:80"]`、`depends_on: [server]`。
- ⚠️ **与 09-21 的「80=H5 / 81=管理端」不是同一套**：现在**只用 80**，两个前端**靠路径区分**
  （`81` 仍然不存在）。旧的 `deploy/nginx/nginx.conf`（双 server 块 80/81）与 `api-proxy.conf`
  是**历史文件**，只有「宿主 nginx 反代」场景还抄 `api-proxy.conf`。
- 路由口径（**必须区分对待，否则白屏**）：
  · `/web`、`/web/` → **302** → `/aioa/web/`（管理端是 `base=/aioa/web/` 的 SPA，地址栏必须落在 base 之下）；
  · `/user/` → **内部 rewrite** → `/aioa/h5/`（H5 自包含单文件，API base 由 `location.pathname` 推）；
  · `/api/`、`/aioa/` → proxy_pass；SSE `location ~ ^/(?:aioa/)?api/v1/runs/[^/]+/events$` + `proxy_buffering off`。
- **可选**：不加该服务、`80` 不通时，`:8080/aioa/web/` 与 `:8080/aioa/h5/` **照旧直接可用**
  ⇒ 既有套件（44 个走 `:8080/api`）与单端口入口**零影响**。
- 守护口径同步：`scripts/_check_single_port.py` 的 nginx 从「禁止出现」名单**移出**，
  新增 `c11_nginx_entry`；现在是 **11 项检查 + 21 项负向 mutation**（全红才算有效）。

## ★★ MinIO 被证实「应用代码不使用」（2026-09-21 全仓核对）

- 判据：全仓 grep（不限扩展名，排除 `node_modules/.git/target/dist`）里 `minio` **只出现在 `deploy/`
  与 `.workbuddy/` 文档**；Java / Python / 前端源码**零命中**，也没有 S3 客户端
  （`S3Client|amazonaws|OSS|ObjectStorage|FileStorage` 同样零命中，仅 venv 版权注释误命中）。
- 实际落盘：`FileController` 的 `@Value("${aioa.upload.dir:./uploads}")` + 元数据落 `sys_file` 表。
- ⇒ ① 别处那台 MinIO（`172.16.8.249`，控制台 `:9001`）**不用接**；② `minio/minio:latest` **不用搬**；
  ③ `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY` 是**死配置**（compose 传了但无人读）⇒ 模板里改**留空**并写明原因。
- ⇒ `minio` 服务归入 **`profiles: ["minio"]`**（默认 `up` 不起）；**`server.depends_on: minio(healthy)` 已删**
  （保留它会把可选服务强拉起来，且 minio 拉不到镜像时 server 直接起不来）。

## ★ 顺手补掉的真缺口：`server` 原先**没挂卷** ⇒ 上传文件会丢

- `server` 在 compose 里 `volumes:` 为空，`./uploads` = `/app/uploads`（Dockerfile.server `WORKDIR /app`）
  **随容器重建即丢**，而 `sys_file` 记录还在 ⇒ 下载 404。
- 已加命名卷 `serveruploads:/app/uploads` + 显式 `AIOA_UPLOAD_DIR=/app/uploads`
  （`@Value("${aioa.upload.dir:…}")` 占位符也能被 `SystemEnvironmentPropertySource` 宽松绑定从环境变量解析）。
- 备份口径随之从「MinIO 卷」改成 **`aioa_serveruploads` 卷**。

## 拓扑与「复用而非托管」原则
- 单机 Docker Compose。
- ⚠️ **2026-09-24 起这句话只在「宿主 nginx 档」成立**：`/api/` 反代 `http://10.0.0.3:8080/`，
  H5 与管理端静态按 §5.2 放。**默认档已改为 compose 自带入口 nginx**（见上方 09-24 段：
  `/web`→管理端、`/user`→用户端，只用 80）。
- **MySQL / Redis / Milvus / MinIO 全在外部**，本 compose **不托管**它们；
  **nginx 例外**（09-24 起 compose 托管一个可选入口 nginx，不加该服务即回到「外部 nginx / 直连 :8080」）。
- **旧「完整档」（自带 nginx，80=H5 / 81=管理端）已不再是默认**：`81` 不存在了；
  `deploy/nginx/nginx.conf`（双 server 块）+ `api-proxy.conf` 保留为**历史/宿主反代参考**。
  两块 `/api/`、SSE、`/openapi/` 都来自**同一份** `deploy/nginx/api-proxy.conf`（`include`，防漂移）。
- **H5 不是容器**：`user-client/index.html`；完整档下由卷挂载进边缘 nginx 静态托管。
  因此 `user-client/serve.py`（本地联调服务器，默认 :5181 只绑 127.0.0.1）**不在生产链路里**
  「serve.py 监听地址 / 它的反代后端地址」都不是生产问题 —— 生产 `/api/` 由 nginx 反代。

## 端口与配置要点（2026-09-20 更新）
- `deploy/nginx/nginx.conf` = 两个 `server` 块：80 用 `root /usr/share/nginx/html/h5` 静态托管 H5；
  81 `proxy_pass http://aioa_web` 托管理端。两块的 `/api/`、SSE、`/openapi/` 都来自
  **同一份** `deploy/nginx/api-proxy.conf`（`include`，防两端漂移）。compose 发布 `80:80` + `81:81`。
- ⚠️ 80 的 `location /` 是 `try_files $uri /index.html` ⇒ **任意路径都回 200**，
  不能拿 200 当「页面正常」的判据，要看内容或改查容器健康。
- 改 `.env` 后用 `docker compose up -d`（会重建）；`restart` **不重读** `.env`。不需要 `--force-recreate`。
- 本机无 nginx / docker / WSL（wsl.exe 在黑名单）⇒ 跑不了 `nginx -t`，
  改用 `python scripts/_check_nginx_conf.py`（自写解析器 + 与 compose 交叉核对，含 7 项负向测试）。
- `deploy/Dockerfile.web` 必须 `COPY web/tsconfig.base.json ./`：4 个 tsconfig 都
  `extends: "../../tsconfig.base.json"`，漏了会导致 strict/esModuleInterop/moduleResolution/skipLibCheck 全丢。

## 关键配置值（`deploy/.env.production`）
| 键 | 值 | 备注 |
|---|---|---|
| `MYSQL_HOST` / `_PORT` / `_DB` / `_USER` / `_PASSWORD` | `10.0.0.5` / `13049` / `aioa` / `aioa` / （见 `.env`） | **★真正生效的库键**：compose 用它们**现拼** `SPRING_DATASOURCE_*`。**13049 不是 3306** —— 写错端口现象是连不上/超时，不是鉴权失败 |
| `REDIS_HOST` / `_PORT` + `SPRING_REDIS_PASSWORD` / `SPRING_REDIS_DATABASE` | `10.0.0.7` / `6379` / （有口令，见 `.env`） / `0` | **★真正生效的 Redis 键**。该实例**有 requirepass** ⇒ 口令漏填现象是 `NOAUTH Authentication required` |
| `AIOA_MILVUS_URI` | `http://10.0.0.12:19530` | **必须宿主 IP，不能 localhost**（容器内 localhost 指向自己）；复用现成实例 |
| `AIOA_MILVUS_TOKEN` | 空 | 该 Milvus **无鉴权** ⇒ 必须留空（填了会认证失败） |
| `AIOA_KB_STORE` | `milvus` | Milvus 不可达 ⇒ 后端**启动失败**（刻意 fail-fast） |
| `AIOA_KB_EMBEDDING_PROVIDER` | `http` | `local`=256 维哈希无语义，生产必须 `http` |
| `AIOA_KB_EMBEDDING_URL` | `http://ollama:11434/api/embeddings` | 容器内互访名 |
| `AIOA_KB_EMBEDDING_MODEL` | `quentinz/bge-small-zh-v1.5` | Ollama 上真实存在的名字（含命名空间） |
| `AIOA_KB_EMBEDDING_DIMS` | `512` | 必须与 `AIOA_MILVUS_DIMS` 一致 |
| `MODEL_DEFAULT` / `MINIMAX_API_KEY` | `minimax` / **必填** | **Key 必须与 `MODEL_DEFAULT` 同名**；留空或不配对 ⇒ **静默降级 echo**（不报错，现象=回答一直回声） |
| `AIOA_GITEE_ENABLED` / `AIOA_GITEE_SYNC_ENABLED` | `false` | 私网 IP 无法被 Gitee 回调，先关（功能自动隐藏） |

### ★ 含特殊字符的口令必须用单引号（2026-09-20 实测）
- MySQL 口令末尾是 `$`，而 `$` 是 **compose 插值字符** ⇒ 双引号/裸写会被吃掉尾部（现象：口令长度少 1、`Access denied`）。
  正确写法 `MYSQL_PASSWORD='…$'`（**单引号**）。
- Redis 口令含 `!` ⇒ bash 历史展开风险，同样**单引号**。
- 自检判据：`source deploy/.env` 后比对**口令长度**，不要只看「变量非空」。

## 哪些文件要改、哪些不用改（★真实值只写 `.env`）
- **真实密钥只写 `deploy/.env`** —— 实测 `git check-ignore deploy/.env` = IGNORED（`.gitignore:33 .env`）。
  本机路径 `C:\Users\刘尖尖\WorkBuddy\aioa\deploy\.env`；服务器路径 `/opt/aioa/deploy/.env`（`cp .env.production .env` 生成）。
- ⚠️ **`deploy/.env.production` 不被 git 忽略**：`.gitignore` 有 `!deploy/.env.production` 反选，
  实测 `git check-ignore` 判 **NOT ignored**，且**已入库**（2026-09-20 起跟踪）。
  ⇒ 它只允许放 `CHANGE_ME__` 占位，**填真实密钥等于把密码提交进仓库**。
  校验：`git ls-files deploy/.env.production`（已跟踪）+ `git ls-files deploy/.env`（应为空）。
- 已改完、**用户不用动**：`deploy/docker-compose.yml` · `deploy/nginx/nginx.conf` · `deploy/.env.production`(模板)。
- 文件里共 **10 处真占位**（2026-09-21 起：原 12 处中的 MinIO 2 处已按「不被使用」清掉）：
  DB 口令 3 处（`MYSQL_PASSWORD` ★生效 / `SPRING_DATASOURCE_PASSWORD` / `MYSQL_ROOT_PASSWORD` ✗compose 不读，
  但一起填同值以免自检残留占位符）+ Redis 1 处 + JWT/服务密钥 4 处 + 令牌加密键 2 处；
  另有若干行顶部说明注释含 `CHANGE_ME__` 字样（查残留时必须 `grep -v ':#'` 排除）。
  `MINIO_*` 五个键**故意留空且不带行尾注释**（免得被 .env 解析当成值的一部分）。

## ★ 环境变量注入路径（2026-09-20 实测，最易搞错的一处）
- compose 里**没有 `env_file`**（`grep -n env_file deploy/docker-compose.yml` 为空）⇒ `deploy/.env`
  **只作为 `${}` 插值源**，不会整份塞进容器；只有 `environment:` 里**显式列出的键**才进容器。
- ⇒ **改 `.env` 里的 `SPRING_DATASOURCE_URL` / `_USERNAME` / `_PASSWORD` 不生效**：server 服务的同名键是
  `jdbc:mysql://${MYSQL_HOST:-…}:${MYSQL_PORT:-…}` / `${MYSQL_USER:-…}` / `${MYSQL_PASSWORD:-…}` 现拼的，
  `environment:` 覆盖同名值。只有**不经 compose、直接 `java -jar`** 时才读 `.env` 这三个键。
- ⇒ **`MYSQL_ROOT_PASSWORD` / `MYSQL_DATABASE` 本 compose 完全不读**（compose 里没有 mysql 服务）。
- 遗留隐患已清：compose 中曾有旧机默认值 `${MYSQL_HOST:-192.168.31.129}`、`${MYSQL_PASSWORD:-yjiud}`
  —— **缺键时会静默连到别的机器**，已改为 `:-10.0.0.5` / `:-13049` / `:-aioa` / `:-10.0.0.7`（口令默认留空，缺了就明确报鉴权失败）。
- 仍未改的两处旧值（**已声明冻结/非本路径**，别照抄）：`deploy/.env.example`（文件头自称
  「已被 .env.development / .env.production 取代，勿再加变量」）与 `deploy/k8s/00-namespace-config.yaml`
  （本部署走 compose，不走 k8s），仍写着 `192.168.31.129`。

## 端口避让（生产机已占用）
- `milvus-minio` 占 **9000/9001**、`milvus-standalone` 占 **19530/9091**（9091 是否发布到宿主**未确认**
  ⇒ 体检以 **19530 在监听且可达**为准，别因 9091 连不上就判定 Milvus 不可用）。
- ⇒ **禁用 `--profile milvus`**（会起第二套撞端口）。
- **本次后端档要的端口是 8080 / 8000（+ 可选 11434）**，与上面全部不冲突。
  9011 只属「完整档自带 minio 控制台」，本次不涉及。
- 完整档下 nginx 卷挂载 `../user-client/index.html` → `/usr/share/nginx/html/h5/index.html`，
  80 端口用 `root` 直接从该目录托管（`/h5/` 作为兼容路径保留）。
  H5 与管理端都用**同源相对路径**（`/api`、`/api/v1`）⇒ 换 IP / 域名 / 端口**无需重新构建前端**。
  ⚠️ 80 的 `location /` 是 `try_files $uri /index.html` ⇒ **任意路径都回 200**，
  不能拿 200 当「页面正常」的判据，要看内容或改查容器健康。

## profile 语义（`deploy/docker-compose.yml`）
- 默认（无 profile）：**server / agent / web / nginx**（`minio` 自 2026-09-21 起**不再默认起**）。
- 后端档：叠加 `docker-compose.backend.yml`，只起 **server / agent**。
- `--profile minio`：起 compose 自带的 minio（**本项目用不上**，见上文）。
- `--profile ollama`：**只起 Ollama**（KB 语义嵌入的必需项，镜像与模型都小）→ 再 `ollama pull quentinz/bge-small-zh-v1.5`。
- `--profile model`：ollama + vllm（vLLM 镜像很大，非必要别拉）。
- `--profile milvus`：**本项目不用**（复用宿主实例）。`--profile ops`：Prometheus/Grafana。

## 模型网关键名（易错）
- 注册表键 ∈ `echo|deepseek|dashscope|vllm|ollama`（**是 key 不是模型名**），按 `{KEY}_BASE_URL` / `{KEY}_API_KEY` 读取。
- 真实变量名是 `VLLM_BASE_URL` / `OLLAMA_BASE_URL`（**`OLLAMA_BASE_URL` 必须带 `/v1`**）；
  历史上文档里的 `LOCAL_VLLM_BASE_URL` 是**死变量**（agent 代码未消费）。
- 缺对应 `*_API_KEY` ⇒ **静默降级 echo**，不报错、难查。

## ★ 2026-09-21 现场排障：两条断链（口令写入 / 镜像获取）

### A. 口令写 `.env`：**禁用 `sed` 拼变量**
- `sed -i "s|^KEY=.*|KEY='${VAR}'|"` 两个陷阱（本地受控实验已复现）：
  值含 **分隔符 `|`** ⇒ `sed: -e expression #1, char NN: unknown option to 's'`，**整条命令失败、值静默没写**
  （屏幕只剩一行报错，极易忽略）；值含 **`&`** ⇒ **不报错但被改坏**（`&` 展开成整段原文，实测 `a&b`→`aMINIMAX_API_KEY=zzzb`）。
- 正解 = **`deploy/ops/set-secrets.py`**：按行整体重写该行（不做模式替换）+ 自动选引号
  （无 `'` 用单引号；有 `'` 只能双引号 + `$$` 转义）+ 回读逐字节校验 + `docker compose config --format json`
  核对**容器真正收到的值**。`--check` / `--only` / `--from-env`（配 `read -rsp`）。
- 陷阱等价物：**`grep -c '^MINIMAX_API_KEY=.\+'`** 是**假通过** —— 模板该行 `=` 后有对齐空格，`.\+` 匹配到空格。
  要用 `grep -nE '^KEY=[^[:space:]]'`，或直接跑 `set-secrets.py --check`。
- **`bash source .env` 不能当自检**：值含 `'` 时只能写双引号 + `$$`，compose 还原成 `$`，
  但 **bash 把 `$$` 当 PID** ⇒ 两边结论不同。以 compose 渲染结果为准。

### B. 口令长度对照表（判断「到底写进去没有」的第一判据）
- `CHANGE_ME__db-password` = **22** 字符；`CHANGE_ME__redis-password` = **25** 字符。
  现场自检报 `22 / 25` ⇒ 就是**占位符本尊**，不是「口令短了」。
- 本机 `deploy/.env.production` 里各键行号（59/60/61/63/64/76/77/78/79/112/115）
  可用来判断服务器那份模板是不是最新（行号能逐行对上 = 代码是当前版本）。

### C. 无外网 ⇒ 镜像怎么进来（`deploy/ops/offline-images.sh`）
- 现场症状：`failed to resolve reference "docker.io/minio/minio:latest" … dial tcp 31.13.94.41:443: i/o timeout`；
  `ping baidu.com` 100% 丢包；`docker run --rm mysql:8.0 …` 卡在 `Unable to find image … locally`。
  ⚠️ 解到的 `31.13.94.41` 是 **Facebook 段** = 典型 **DNS 污染**，**不等于没有外网** ⇒
  必须分开探测「国内站点 / 各加速器」（`deploy/ops/host-check.sh` §⑤ 就是干这个的）。
- **本次后端档只需 2 个镜像**：`aioa-server` + `aioa-agent`（都是本地构建产物）。
  完整档才需 `minio/minio:latest` + `nginx:1.27-alpine` + `aioa-web`。
  可选 `ollama/ollama:latest`（**KB 语义嵌入必需**，模型 `quentinz/bge-small-zh-v1.5`，卷 `aioa_ollamadata`）。
- ★ `docker-compose.yml` 顶层有 **`name: aioa`** ⇒ 任意机器上构建出的应用镜像名**完全一致**
  ⇒ 离线 `docker load` 之后直接 `docker compose up -d`，**绝不要加 `--build`**
  （加了会重新构建，而目标机拉不到基础镜像，必然失败）。
- 构建应用镜像需要 `maven:3.9-eclipse-temurin-21` / `node:22-alpine` / `python:3.13-slim` /
  `eclipse-temurin:21-jre` —— 这些只在**导出机**上需要；搬运只搬**成品镜像**。

### C2. `offline-images.sh` 的三个真 bug 与「假 docker 桩」测法（2026-09-21）

- ① `--backend-only` 下 `EXT_IMAGES` 是**空数组** ⇒ `set -u` + 旧 bash 下 `"${arr[@]}"` 报 unbound：
  一律先判 `[ ${#arr[@]} -gt 0 ]` 再展开，**不写** `("${A[@]}" "${B[@]}")` 混合形式。
- ② `--with-ollama` 曾用 `${EXT_IMAGES[1]}`（取 nginx）当搬运容器 ⇒ 后端档下**越界崩**：
  改为 `docker cp` + **宿主 `tar`**；`import-ollama` 直接写 `${DockerRootDir}/volumes/<vol>/_data`。
- ③ `list --backend-only` **只改了标题、清单仍取完整档** ⇒ 把 nginx/aioa-web 报成「缺」（误导）：
  改为按模式选数组；`import` 支持透传 `--backend-only`。
- **可复用测法**：临时目录放一个 `docker` 桩脚本（记调用日志 + 按子命令返回桩值），
  `PATH="$TMP:$PATH" bash deploy/ops/offline-images.sh ...`。五条链路（export / export --with-ollama /
  import / import-ollama / list）应全 exit 0，且后端档下 `docker pull` **一次都不发**。
  ⚠️ 桩的 PATH 首段**不能带 Windows 反斜杠**（`C:\…` 会让 `command -v docker` 找不到），须转 `/c/…`。

### C3. `deploy/ops/compose-lint.py`（本机无 docker 也能体检 compose）

本机**没装 docker** ⇒ `docker compose config` 用不了。改为纯 pyyaml 静态体检四类「上机才炸」的错：
① `depends_on` 指向 **profile 门控**服务 —— 判据是「依赖的 profiles ⊄ 本服务的 profiles」，
   故 `milvus→etcd` 合法、`server→minio` 才报错；② 挂了未在顶层声明的命名卷；
③ compose 引用但 `.env` 里没有的键（会静默取默认值）；④ `CHANGE_ME__` 残留。
`--override` 可叠加 backend.yml 一起查。**曾抓到 `server.depends_on: minio` 这条真错误。**

### D. 行尾：`core.autocrlf=true` 必须靠 `.gitattributes` 压住
- Windows 检出的 `.sh` 会是 CRLF ⇒ 拷到 Linux 报 `\r: command not found` / `bad interpreter`；
  `.env` 混进 `\r` ⇒ 口令多一个隐藏字符 ⇒ 鉴权失败且极难查。
- 已加 `.gitattributes`：`*.sh` / `deploy/ops/*.py` / `deploy/.env*` / `.env*` 强制 `eol=lf`。

### E. 访问与仓库来源（未决）
- 公网直连 `10.0.0.3:22` **不通**；隧道 `219.151.186.24:22` —— 用户给的写法（`root/Ego2025` 等 5 种变体 ×
  3 个用户名 × password/keyboard-interactive）**全部认证被拒**，其余 7 个常见转发端口也不通
  （仅 22 是 SSH，`OpenSSH_8.9p1 Ubuntu`）⇒ **agent 无法直连该机，只能把脚本交给用户在服务器上跑**。
- `origin` = **Gitea `http://172.16.8.249:3000/liujiejie/AIOA_System.git`**（不是 GitHub），
  与本地 `main` **已分叉**：本地领先 92 个提交，`origin/main` 另有 `179547e 删除目录「.workbuddy」`。
  ⇒ 必须确认服务器代码是**从 Gitea 拉**还是**本地直传**；从 Gitea 拉会拿到旧树。

## ★ 2026-09-21 三机角色与「分两包」的依据

**角色固定**：本地（改码/推码）→ **隧道机 `219.151.186.24`（唯一能碰到真实服务器的跳板）** →
**真实服务器 `10.0.0.3`（无外网）**。任何文件都只能经隧道机中转。

**两个容错事实（决定了 Ollama 可以后补，不必一次搬 2.3G）**：
1. `EmbeddingConfig.embeddingProvider()` 启动时**只装配 Bean、不校验连通性**；
   `HttpEmbeddingProvider` 只在**被调用时**抛 `IllegalStateException("嵌入服务不可达：url=…")`。
2. `KbService.embedAll` 对**单个切片** try/catch：嵌入失败**只告警、不阻断入库**；
   `MilvusKnowledgeStore` 对 `vector.length != info.dims()` 只**跳过 + 告警**，不抛异常。
   ⇒ **缺 Ollama 时后端照常启动、上传照常成功，只是没有向量、检索不命中**（预期，非缺陷）。

**搬运分两包**（`deploy/ops/offline-images.sh`）：
- 包 1 `aioa-images-backend.tar.gz`（`export --backend-only`）= **只有 `aioa-server` + `aioa-agent`**
  ⇒ 先导入先起，跑 §6 验收。
- 包 2 `ollama-image.tar.gz`（约 1.5G，**比包 1 还大**）+ `ollama-models.tar.gz` ⇒ 验收后再补。
- （完整档才需 `aioa-images.tar.gz` = minio + nginx + aioa-server/agent/web）

**先探内网，可能白搬**：`host-check.sh` 会把 `daemon.json` 里的 `registry-mirrors` /
`insecure-registries` 逐个探通断，并读 `docker info` 的生效镜像源、探内网 Gitea（`172.16.8.249:3000`）。
**若内网本来就有 harbor/nexus，直接 `docker compose up -d --build` 即可，整条搬包流程免掉。**

## ★ 真实服务器已有容器（2026-09-21 `docker ps` 实测）

| 容器 | 镜像 | 对 AIOA |
|---|---|---|
| `milvus-standalone` | `milvusdb/milvus:v2.6.14` | ✅ **外挂复用**（在 **10.0.0.12**，`AIOA_MILVUS_URI=http://10.0.0.12:19530`；应用机 10.0.0.3 上**只有 `milvus-attu` 控制台**，没有 19530 在听）；`≥2.5` ⇒ BM25 可开 |
| `milvus-etcd` | `etcd:v3.5.25` | ➖ Milvus 配套，不用单独连 |
| `mongodb` | `mongo:latest` | ❌ 别的系统 |
| `rmqbroker` / `rmqnamesrv` | `apache/rocketmq:4.9.6` | ❌ 别的系统 |

- **已核实 AIOA 不用 Mongo/RocketMQ**：`server/*/pom.xml`、`server/pom.xml`、`agent/requirements*.txt`、
  `deploy/docker-compose.yml` 里搜 `mongo|rocketmq|kafka|amqp|rabbit` **全部零命中**。别去动它们。
- 端口：已有容器占 `10909/10911/9876/19530/2379/2380/27017`；**后端档要 `8080/8000`（+可选 11434）** ⇒ **不冲突**。
- **仍然要构建/搬运**：这 5 个容器一个都不是本项目要的（`aioa-server/agent` 是本项目构建产物）。
  但 `minio/minio` 与 `nginx` **本次不需要**（MinIO 代码不读、边缘 nginx 用户已有）。
- ★ **`docker ps` ≠ 镜像清单**：它只列运行中容器，机器上可能有没在跑的 `nginx`/`minio` 镜像；
  用 `docker ps` 判断齐备会误判成「什么都没有」而白搬整个包。**判断只能用 `docker images`。**
