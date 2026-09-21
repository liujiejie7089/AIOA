# AIOA 环境变量配置说明（本地开发 / 生产）

配套文件：

| 文件 | 环境 | 用途 | 入库 |
|---|---|---|---|
| `deploy/.env.development` | 本地开发（单机） | 本机跑全栈，全部 `127.0.0.1`，无 TLS | ✅ 只含占位值 |
| `deploy/.env.production` | 生产 | docker compose / K8s 部署，真实域名 + TLS | ✅ 只含 `CHANGE_ME__` 占位 |
| `.env`（仓库根，gitignore） | 两者皆可 | 放**真实值**的覆盖文件 | ❌ |
| `deploy/.env.example` | — | 早期单文件模板，**已被上面两份取代**（保留仅为兼容旧脚本） | ✅ |

两份文件**键集合与键序完全一致**（各 78 项，`diff` 为空），可直接逐行对照：

```bash
diff <(grep -oE '^[A-Z_]+=' deploy/.env.development) \
     <(grep -oE '^[A-Z_]+=' deploy/.env.production)   # 无输出 = 结构一致
```

## 1. 使用方式

```bash
# ---- 本地开发 ----
cd <repo 根>
set -a && . deploy/.env.development && set +a
bash start-all.sh

# ---- 生产 ----
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d
# K8s：★敏感 项灌 Secret，其余灌 ConfigMap

# ---- 用真实值覆盖（推荐，模板保持干净）----
cp deploy/.env.development .env      # 在 .env 里填真实密钥；.env 已被 gitignore
```

`start-all.sh` 的 Gitee 端到端回归是**显式 opt-in**，与上面两份文件无关：
`AIOA_GITEE_E2E=1 bash start-all.sh`（内部 source `scripts/gitee-e2e-env.sh`，把服务端接口与用户授权域一并指向桩 `:8090`）。

## 2. 占位约定（两文件共用）

| 写法 | 含义 |
|---|---|
| `CHANGE_ME__xxx` | **必须替换**的敏感值（密钥/密码/凭据）。生产模板里全部敏感项都是这个形态 |
| `DEV_ONLY__xxx` | 仅限本地、**绝不可进生产**的值 |
| `<xxx>` | 按实际环境填写的非敏感值 |
| 留空 | 该能力未启用，代码走内置默认 |

密钥生成：`openssl rand -base64 48`。

## 3. 变量对照表

> 「敏感」列 ★ = 必须替换/保密；— = 非敏感可入库。

### 3.0 运行档位

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `SPRING_PROFILES_ACTIVE` | Spring profile | `dev` | `prod` | — |
| `AIOA_KB_STORE` | 知识库存储实现 | `mysql` | `mysql`（切向量库改 `milvus`） | — |
| `AIOA_REPO_PROVIDER` | 代码托管方，决定读 Gitee 段还是 Gitea 段 | `gitee` | `gitee` | — |

### 3.1 数据库 MySQL 8

> **★ 本部署的 MySQL 在外部主机 `10.0.0.5:13049`（端口非默认），不由 compose 托管** ⇒
> **只改 `.env` 的 §1 那几行**。「生效」列标 ❌ 的键改了不会影响容器里跑的后端。
> ⚠️ 该机口令**以 `$` 结尾** ⇒ 写进 `.env` 时**必须单引号**（`$` 是 compose 插值符）。

| 变量 | 用途 | 本地开发 | 生产（外部实例） | 敏感 | 生效 |
|---|---|---|---|---|---|
| `MYSQL_HOST` / `_PORT` / `_DB` | compose **拼 JDBC 串**用 | `127.0.0.1` / `3306` / `aioa` | `10.0.0.5` / **`13049`** / `aioa` | — | ✅ |
| `MYSQL_USER` / `MYSQL_PASSWORD` | compose 拼 JDBC 串用的凭据 | `root` / 空 | `aioa` / `CHANGE_ME__`（非 root） | ★ | ✅ |
| `SPRING_DATASOURCE_URL` / `_USERNAME` / `_PASSWORD` | 后端 JDBC 串与账号 | `jdbc:mysql://127.0.0.1:3306/aioa?…` | 被上面的 `MYSQL_*` **现拼覆盖** | — | ❌ 仅不经 compose 直跑 jar 时有效 |
| `MYSQL_ROOT_PASSWORD` / `MYSQL_DATABASE` | 仅 compose 自建 mysql 时用 | `DEV_ONLY__` / `aioa` | 本 compose 不读（无 mysql 服务）⇒ 留空 | ★ | ❌ |

### 3.2 Redis

> 同 MySQL：Redis 在外部主机 `10.0.0.7:6379`，**只改 `.env` 的 §2**。本次 Redis **有口令**（含 `!`，建议单引号）。

| 变量 | 用途 | 本地开发 | 生产（外部实例） | 敏感 | 生效 |
|---|---|---|---|---|---|
| `REDIS_HOST` / `REDIS_PORT` | compose 拼后端 Redis 连接用 | `127.0.0.1` / `6379` | `10.0.0.7` / `6379` | — | ✅ |
| `SPRING_REDIS_PASSWORD` | 密码（无 `requirepass` 才留空） | 空 | `CHANGE_ME__`（**本次必填**） | ★ | ✅ |
| `SPRING_REDIS_DATABASE` | 库号 | `0` | `0` | — | ✅ |
| `SPRING_REDIS_HOST` / `_PORT` | `application.yml` 显式读的两个键 | `127.0.0.1` / `6379` | 由 `REDIS_*` 现拼 | — | ❌（被覆盖） |

### 3.3 鉴权密钥 ★

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `AIOA_JWT_SECRET` / `JWT_SECRET` | 用户令牌签名（`AIOA_*` 给后端，无前缀给 compose） | `DEV_ONLY__` | `CHANGE_ME__openssl-rand-base64-48` | ★ |
| `AIOA_SERVICE_JWT_SECRET` / `SERVICE_JWT_SECRET` | 后端↔agent 服务间令牌 | `DEV_ONLY__` | 同上，**与 JWT 不同值** | ★ |

> ⚠️ 带 `AIOA_` 前缀与不带前缀的**必须同值**，否则后端签发的令牌 agent 验不过（表现为 401）。
> ⚠️ 轮换即让所有已签发令牌立刻失效（全员重新登录）。

### 3.4 服务地址与运行参数

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `AIOA_AGENT_BASE_URL` | 后端 → agent | `http://127.0.0.1:8000` | `http://agent:8000` | — |
| `AIOA_SERVER_BASE_URL` | agent → 后端 | `http://127.0.0.1:8080` | `http://server:8080` | — |
| `PUBLIC_BASE_URL` | 对外入口（OAuth 回跳以此为准） | `http://localhost` | `https://aioa.example.com` | — |
| `HOST` / `PORT` | agent 监听 | `0.0.0.0` / `8000` | 同 | — |
| `LOG_LEVEL` | 日志级别 | `INFO` | `INFO` | — |
| `AGENT_STREAM` / `AGENT_PARALLEL_TOOLS` | 流式 / 并行工具 | `true` | `true` | — |
| `AGENT_MAX_CONCURRENCY` | agent 并发上限 | `4` | `8`（按容器规格） | — |
| `PG_DSN` | agent 直连库（当前未用） | 空 | 空 | ★ |

### 3.5 模型

模型网关的注册表键 `KEY` ∈ `echo | minimax | deepseek | dashscope | vllm | ollama`，
另加管理端「模型管理」手动新增的模型（键 = 其 `providerKey`）。
凭据一律走 **`{KEY}_API_KEY` 环境变量**或管理端填写（管理端填写的落库时加密，见 `AIOA_MODEL_KEY_ENC_KEY`）；
**任何 Key 都不写入 `.env.production` 模板**（该文件会被提交）。

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `MODEL_DEFAULT` | 默认模型（系统默认已改为 `minimax`） | `echo`（不配 Key 时自动降级回声） | `minimax` | — |
| `MINIMAX_API_KEY` | MiniMax Key | 填真实值（`agent/.env`） | `CHANGE_ME__`（**只填进 `.env`**） | ★ |
| `DEEPSEEK_API_KEY` | DeepSeek Key | 空 | `CHANGE_ME__` | ★ |
| `DASHSCOPE_API_KEY` | 通义千问 Key | 空 | `CHANGE_ME__` | ★ |
| `VLLM_BASE_URL` | 本地 vLLM（OpenAI 兼容基址） | `http://127.0.0.1:8000/v1` | `http://vllm:8000/v1` | — |
| `VLLM_API_KEY` | vLLM 鉴权；无鉴权也要给非空占位 | `vllm` | `vllm` | ★ |
| `OLLAMA_BASE_URL` | 本地 Ollama，**必须带 `/v1`** | `http://127.0.0.1:11434/v1` | `http://ollama:11434/v1` | — |
| `OLLAMA_API_KEY` | 同上，非空占位 | `ollama` | `ollama` | ★ |
| `AIOA_MODEL_KEY_ENC_KEY` | 管理端填写的 API Key 的落库加密密钥 | 可留空（回退内置，仅开发） | `CHANGE_ME__`（openssl rand -base64 48） | ★ |

> ⚠️ 历史文档里的 `LOCAL_VLLM_BASE_URL` / `LOCAL_MODEL_NAME` **不是**代码读取的变量（agent 只认
> `{KEY}_BASE_URL` / `{KEY}_MODEL`），照抄会导致配置不生效。
> `AIOA_MODEL_KEY_ENC_KEY` 为空时回退 `AIOA_GITEE_TOKEN_ENC_KEY`，两者都空则用内置开发密钥并打印 WARN。

### 3.6 代码托管方（Gitee / Gitea）

**只填 `AIOA_REPO_PROVIDER` 指向的那一段**；另一段保持 `enabled=false` 且留空。两段结构对称。

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `AIOA_{GITEE,GITEA}_ENABLED` | 该托管方总开关 | 仅 gitee=`true` | 仅实际用的=`true` | — |
| `…_BASE_URL` | 服务端 REST 基址 | `https://gitee.com/api/v5` | 同（Gitea **必须带 `/api/v1`**） | — |
| `…_WEB_URL` | 网页域 | `https://gitee.com` | 同 | — |
| `…_OAUTH_AUTHORIZE_URL` | **用户浏览器**授权页基址（与服务端域解耦） | `https://gitee.com` | 同 | — |
| `…_CLIENT_ID` / `…_CLIENT_SECRET` | OAuth 应用凭据 | 空 | `CHANGE_ME__` | ★ |
| `…_REDIRECT_URI` | 回调地址，须与登记页**逐字符一致** | `http://127.0.0.1:8080/…/bind/callback` | `https://aioa.example.com/…/bind/callback` | — |
| `…_SCOPE` | 授权范围 | Gitee 含 `projects hook` | 同 | — |
| `…_ORG` | 建仓所在组织 | 空＝用户名下 | `<gitee-org>` | — |
| `…_WEBHOOK_BASE_URL` | 反向回调基址 | **空**（本地不可达） | `https://aioa.example.com` | — |
| `…_WEBHOOK_SECRET` | 回调签名密钥 | 空＝每仓库随机 | `CHANGE_ME__` | ★ |
| `…_TOKEN_ENC_KEY` | 授权令牌 AES-256 加密密钥 | `DEV_ONLY__` | `CHANGE_ME__` | ★ |
| `AIOA_GITEE_BIND_RETURN_URL` | 授权完成后前端回跳 | `http://localhost:5173/` | `https://aioa.example.com/` | — |
| `AIOA_GITEE_SYNC_ENABLED` / `_SYNC_CRON` | 定时校准开关/表达式 | `true` / `0 17 * * * *` | 同 | — |
| `AIOA_GITEA_REPO_NAME_SOURCE` | 仓库标识来源 `AUTO\|NAME\|PATH` | `AUTO` | `AUTO` | — |
| `AIOA_GITEA_INSECURE_SKIP_VERIFY` | 跳过 TLS 校验 | `false` | **必须 `false`** | — |
| `AIOA_GITEA_TRUST_STORE` / `_PASSWORD` / `_TYPE` | 自签证书信任库 | 空 / 空 / `PKCS12` | `<path>` / `CHANGE_ME__` / `PKCS12` | ★ |

> ⚠️ 切 `AIOA_REPO_PROVIDER` 后，**既有令牌解不开是预期行为**（两段各一个加密密钥），需重新授权绑定，不是 bug。

### 3.7 知识库 / 向量库

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| **`AIOA_KB_STORE`** | 存储实现 `mysql` \| `milvus`（**声明在 §0 档位区，勿重复声明**） | `mysql` | `mysql` | — |
| `AIOA_KB_EMBEDDING_PROVIDER` | 嵌入实现 `local`（256 维 n-gram 哈希，零依赖但**无语义**）\| `http`（语义向量） | `local` | `http` | — |
| `AIOA_KB_REEMBED_ON_START` | 启动时全量重算切片向量（换 provider / 模型后跑一次，跑完改回 `false`） | `false` | `false` | — |
| `AIOA_KB_EMBEDDING_FORMAT` | 协议形态 `ollama`（`/api/embeddings` 或 `/api/embed`）\| `openai`（`/v1/embeddings`） | `ollama` | `ollama` | — |
| `AIOA_KB_EMBEDDING_URL` | 嵌入服务地址（`provider=http` 时必填） | 空 | `<url>` | — |
| `AIOA_KB_EMBEDDING_MODEL` | 模型名 | `bge-small-zh-v1.5` | 同 | — |
| `AIOA_KB_EMBEDDING_DIMS` | 向量维度，**必须与 `AIOA_MILVUS_DIMS` 一致** | `512` | `512` | — |
| `AIOA_KB_EMBEDDING_TIMEOUT_MS` | 嵌入请求超时（ms） | `15000` | `15000` | — |
| `AIOA_KB_EMBEDDING_API_KEY` | 可选 Bearer 令牌（vLLM 网关常需） | 空 | 空 | ★ |
| `AIOA_MILVUS_URI` | Milvus gRPC 地址 | `http://127.0.0.1:19530` | **复用外部实例** `http://10.0.0.12:19530`（`milvus:19530` 只在 `--profile milvus` 自建栈时用，本部署**不开**该 profile） | — |
| `AIOA_MILVUS_TOKEN` | 鉴权令牌（未开鉴权时留空） | 空 | **空** —— 本环境 Milvus 无鉴权，填了会认证失败 | ★ |
| `AIOA_MILVUS_DATABASE` / `_COLLECTION` | 库名 / 集合名（**名字带版本后缀**，换嵌入模型必须新建集合再回填） | `default` / `kb_chunk_v1` | 同 | — |
| `AIOA_MILVUS_DIMS` | 集合维度（**创建后不可改**） | `512` | `512` | — |
| `AIOA_MILVUS_METRIC` / `_INDEX` | 距离度量 `COSINE\|IP\|L2` / 索引 `HNSW\|AUTOINDEX\|FLAT` | `COSINE` / `HNSW` | 同 | — |
| `AIOA_MILVUS_HNSW_M` / `_HNSW_EF` | HNSW 建图/检索参数 | `16` / `200` | 同 | — |
| `AIOA_MILVUS_ENABLE_BM25` | 原生 BM25 混合检索（需 Milvus ≥ 2.5；建集合失败自动退回纯稠密并告警） | `true` | `true` | — |
| `AIOA_MILVUS_BACKFILL` | 启动时从 `kb_chunk` 全量回填（首次接入 / 重建索引，跑完改回 `false`） | `false` | `false` | — |
| `AIOA_MILVUS_TIMEOUT_MS` / `_BATCH` | 超时（ms）/ 回填与 upsert 的批量大小 | `10000` / `200` | 同 | — |
| `MILVUS_IMAGE_TAG` | **仅供 compose / k8s 拉镜像**（升 2.6.x 改这里，注意集合是否需重建） | `v2.5.3` | `v2.5.3` | — |

> **以上 22 个键后端已全部真实读取**（`KbProperties`，前缀 `aioa.kb`），不再是预留项。
> ⚠️ `AIOA_KB_STORE=milvus` 时 **Milvus 必须在线**，否则后端**启动失败**（决策 D6 fail-fast，不静默降级为空结果）。
> 索引可从 MySQL `kb_chunk` 重建 ⇒ `etcd` / `milvus-minio` / `milvus` 三者数据卷都是**可丢的**；
> **回滚 = 把 `AIOA_KB_STORE` 改回 `mysql`**（无需改代码）。
> 首次切换前先 `AIOA_KB_REEMBED_ON_START=true` 补齐切片向量，再 `AIOA_MILVUS_BACKFILL=true` 回填（顺序不能反），
> 详见 `docs/32-向量库迁移Milvus实施计划.md`。

### 3.8 对象存储 MinIO（★★ **当前未被使用** —— 留空即可）

> **2026-09-21 核对结论（可复现）**：应用代码**不使用 MinIO** —— Java / Python / 前端源码里
> 没有 `minio` 字样，也没有 S3 客户端（无 `S3Client` / `amazonaws` / OSS SDK）。
> 文件上传落的是 **server 容器内的本地目录**：`FileController` 的
> `@Value("${aioa.upload.dir:./uploads}")`（compose 已固定为 `/app/uploads` 并挂命名卷
> `serveruploads` 持久化），元数据落 `sys_file` 表。
>
> 因此本组变量**改与不改都不影响功能**；且 compose 自带的 `minio` 服务已归入
> `profile: [minio]`，默认 `docker compose up -d` **不会**再起它（历史上它靠
> `server.depends_on: minio(healthy)` 被强制拉起，该依赖已移除）。
> 目标机上别处已有的 MinIO（本次 `172.16.8.249`，控制台 `:9001`）**与本项目无关，不需要接**。

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | 仅供 `--profile minio` 起**自带** minio 时用 | 留空 | 留空 | ★ |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | server 容器会收到，但**无人读取** | 留空 | 留空 | ★ |
| `MINIO_ENDPOINT` | 同上；真要启用时填 **数据端口** `http://<host>:9000`（**不是**控制台 9001） | 留空 | 留空 | — |

> 想真接入对象存储，必须**同时**做两件事：① 应用侧补 S3 客户端实现 ② `.env` 填上面三个键。
> 只填 `.env` 不会有任何效果（当前没有读取方）。
>
> 若你的本地 `.env.development` 里仍留着旧的 MinIO 值，可以忽略——它不会被任何代码读到。

### 3.9 观测

| 变量 | 用途 | 本地开发 | 生产 | 敏感 |
|---|---|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | Grafana 管理员密码 | `admin` | `CHANGE_ME__` | ★ |

### 3.10 入口与端口（本次「不用边缘 nginx」档）

| 项 | 用自带 nginx（完整档） | **本次 10.0.0.12（后端档）** |
|---|---|---|
| 启动命令 | `docker compose up -d` | `docker compose -f docker-compose.yml -f docker-compose.backend.yml up -d server agent` |
| 服务集合 | server + agent + web + nginx（+minio 不再默认起） | **只有 server + agent** |
| 对外端口 | `80`（用户端 H5）、`81`（管理端） | `8080`（后端 API）、`8000`（agent，排查用） |
| H5 / 管理端静态 | 由 nginx 容器直接提供 | **由宿主已有的 nginx 提供服务并反代 `/api/`** |
| 需要的镜像 | minio + nginx + aioa-server + aioa-agent + aioa-web（5 个） | **aioa-server + aioa-agent（2 个）** |

> 后端档下 `web` 与 `nginx` 容器都不需要：`aioa-web` 的运行底座**本身就是** `nginx:1.27-alpine`，
> 所以连 nginx 镜像也不必搬。宿主 nginx 只要把 `/api/` 反代到 `http://127.0.0.1:8080/`。
> 叠加文件只加 `ports`、不改任何环境变量，因此对「带 nginx」的既有部署零影响。

## 4. 前端 env **不在**上面两份文件

Vite 只读**各应用自己的** `.env`；H5 读 `user-client/.env`。后端 env 里写 `VITE_*` 不会生效，故单列于此：

| 文件 | 变量 | 本地开发 | 生产 |
|---|---|---|---|
| `web/apps/shell/.env` | `VITE_PORT` / `VITE_API_TARGET` | `5173` / `http://localhost:8080` | `5173` / `<对外网关地址>` |
| `web/apps/demo-ticket/.env` | `VITE_PORT` | `5174` | `5174` |
| `web/apps/demo-dispatch/.env` | `VITE_PORT` | `5175` | `5175` |
| `user-client/.env` | `HOST` / `PORT` / `BACKEND_HOST` / `BACKEND_PORT` | `127.0.0.1` / `5181` / `127.0.0.1` / `8080` | 走容器时 `0.0.0.0` / `5181` / `aioa-server` / `8080` |

子应用端口改动**需同步业务应用注册表**（wujie 注册表）。

## 5. 两份文件的差异摘要（除敏感值外，只有这几处真的不同）

| 类别 | 本地开发 | 生产 |
|---|---|---|
| 主机名 | `127.0.0.1` / `localhost` | **外部主机 IP**：MySQL `10.0.0.5:13049` / Redis `10.0.0.7:6379` / Milvus `10.0.0.12:19530`；**容器之间**仍用服务名 `agent` `server` `ollama`（`minio` 已非默认起，见 §3.8） |
| 协议 | `http` | 本次 `http`（内网 80/81 或 8080，未接 TLS）；拿到公网域名后再上 `https` |
| 域名 | 本机端口 | 本次直接用 IP `10.0.0.12`（**本次入口由宿主已有 nginx 提供**，见 §3.10）；有公网域名时替换 |
| 凭据 | `DEV_ONLY__` / 空 | 全部 `CHANGE_ME__` 占位，部署前逐项替换 |
| TLS | 不涉及 | `AIOA_GITEA_INSECURE_SKIP_VERIFY=false` + 自签 CA 信任库 |
| 并发 | `AGENT_MAX_CONCURRENCY=4` | `8`（按容器规格） |
| 模型 | `echo`（零依赖） | 真实云端/本地模型 |

## 6. 安全纪律

1. **两份模板只放占位值**，真实密钥写 `.env`（gitignore）或部署平台 Secret；`.env`、`.env.*` 已被忽略，本目录两份模板通过 `.gitignore` 例外**显式入库**。
2. **改密钥后必须重启**后端（`AIOA_*` 均启动期读取）。
3. `AIOA_JWT_SECRET`、`AIOA_SERVICE_JWT_SECRET`、`*_TOKEN_ENC_KEY`、各 API Key 属**高危**项：轮换 `TOKEN_ENC_KEY` 会导致存量授权令牌不可解密，需重新绑定。
4. 生产交付前自查：
   ```bash
   grep -nE 'DEV_ONLY__|CHANGE_ME__' deploy/.env.production   # 每一条都必须是「已替换」或「该能力未启用」
   grep -nE 'localhost|127\.0\.0\.1'  deploy/.env.production   # 应为空（除 PG_DSN 等空值行）
   ```
