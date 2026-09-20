# 生产部署（目标机 10.0.0.12）

> 2026-09-19 建立；**2026-09-20 目标机由 192.168.2.130 改为 10.0.0.12**（Milvus `19530`、**无鉴权**）。
> **2026-09-20 第二批：三件套全部落到已有外部实例** —— MySQL `10.0.0.5:13049`（**非默认端口**）/ 库 `aioa` / 用户 `aioa`；
> Redis `10.0.0.7:6379`（**有口令**，与早前「无口令」不同）；Milvus 仍是 `10.0.0.12:19530` 无鉴权。真实口令只在 `deploy/.env`。
> 入口文档 = `deploy/生产部署手册.md`（含「§4.0 填写位置总览」+ 验收 + 故障对照表）。

## 拓扑与「复用而非托管」原则
- 单机 Docker Compose，**边缘 nginx 对外两个端口：80 = 用户端 H5、81 = 管理端**（2026-09-20 由单 80 拆分）；
  server/agent/web 仅内网互访。
- **MySQL / Redis / Milvus 复用机器已有实例**（用户 `docker ps` 已有 `milvus-standalone`/`milvus-minio`/`milvus-etcd`/`redis`/`mysql`），本 compose **不托管**它们。
- compose 只起应用侧：`server / agent / web(shell) / nginx / minio / ollama`（+ 可选 `vllm`）。
- **H5 不是容器**：`user-client/index.html` 由卷挂载进边缘 nginx 静态托管。
  因此 `user-client/serve.py`（本地联调服务器，默认 :5181 只绑 127.0.0.1）**不在生产链路里**，
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
- 文件里共 **12 处真占位**：9 处随机密钥（不同行号，须一次 sed 全改）+ 3 处 DB 口令
  （`MYSQL_PASSWORD` ★生效 / `SPRING_DATASOURCE_PASSWORD`、`MYSQL_ROOT_PASSWORD` ✗compose 不读，
  但一起填同值以免自检残留占位符）；
  另有若干行顶部说明注释含 `CHANGE_ME__` 字样（查残留时必须 `grep -v ':#'` 排除）。

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
- ⇒ 本项目 MinIO 控制台改 **`9011:9001`**；⇒ **禁用 `--profile milvus`**（会起第二套撞端口）。
- nginx 卷挂载 `../user-client/index.html` → `/usr/share/nginx/html/h5/index.html`，
  80 端口用 `root` 直接从该目录托管（`/h5/` 作为兼容路径保留）。
  H5 与管理端都用**同源相对路径**（`/api`、`/api/v1`）⇒ 换 IP / 域名 / 端口**无需重新构建前端**。

## profile 语义（`deploy/docker-compose.yml`）
- 默认（无 profile）：server/agent/web/nginx/minio。
- `--profile ollama`：**只起 Ollama**（KB 语义嵌入的必需项，镜像与模型都小）→ 再 `ollama pull quentinz/bge-small-zh-v1.5`。
- `--profile model`：ollama + vllm（vLLM 镜像很大，非必要别拉）。
- `--profile milvus`：**本项目不用**（复用宿主实例）。`--profile ops`：Prometheus/Grafana。

## 模型网关键名（易错）
- 注册表键 ∈ `echo|deepseek|dashscope|vllm|ollama`（**是 key 不是模型名**），按 `{KEY}_BASE_URL` / `{KEY}_API_KEY` 读取。
- 真实变量名是 `VLLM_BASE_URL` / `OLLAMA_BASE_URL`（**`OLLAMA_BASE_URL` 必须带 `/v1`**）；
  历史上文档里的 `LOCAL_VLLM_BASE_URL` 是**死变量**（agent 代码未消费）。
- 缺对应 `*_API_KEY` ⇒ **静默降级 echo**，不报错、难查。
