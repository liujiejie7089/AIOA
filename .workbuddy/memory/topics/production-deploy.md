# 生产部署（目标机 192.168.2.130）

> 2026-09-19 建立。入口文档 = `deploy/生产部署手册.md`（9 节，含验收与故障对照表）。

## 拓扑与「复用而非托管」原则
- 单机 Docker Compose，**nginx:80 是唯一对外入口**；server/agent/web/H5 仅内网互访。
- **MySQL / Redis / Milvus 复用机器已有实例**（用户 `docker ps` 已有 `milvus-standalone`/`milvus-minio`/`milvus-etcd`/`redis`/`mysql`），本 compose **不托管**它们。
- compose 只起应用侧：`server / agent / web(shell) / nginx / minio / ollama`（+ 可选 `vllm`）。

## 关键配置值（`deploy/.env.production`）
| 键 | 值 | 备注 |
|---|---|---|
| `SPRING_DATASOURCE_URL` | `jdbc:mysql://192.168.2.130:3306/aioa?...&createDatabaseIfNotExist=true` | 库不存在会自动建 |
| `SPRING_REDIS_HOST` / `REDIS_HOST` | `192.168.2.130` | 双键名都传（`application.yml` 显式引用 `SPRING_REDIS_HOST`） |
| `AIOA_MILVUS_URI` | `http://192.168.2.130:19530` | **必须宿主 IP，不能 localhost**（容器内 localhost 指向自己） |
| `AIOA_KB_STORE` | `milvus` | Milvus 不可达 ⇒ 后端**启动失败**（刻意 fail-fast） |
| `AIOA_KB_EMBEDDING_PROVIDER` | `http` | `local`=256 维哈希无语义，生产必须 `http` |
| `AIOA_KB_EMBEDDING_URL` | `http://ollama:11434/api/embeddings` | 容器内互访名 |
| `AIOA_KB_EMBEDDING_MODEL` | `quentinz/bge-small-zh-v1.5` | Ollama 上真实存在的名字（含命名空间） |
| `AIOA_KB_EMBEDDING_DIMS` | `512` | 必须与 `AIOA_MILVUS_DIMS` 一致 |
| `MODEL_DEFAULT` / `DEEPSEEK_API_KEY` | `deepseek` / 留空 | 留空 ⇒ **静默降级 echo**（不报错，现象=回答一直回声） |
| `AIOA_GITEE_ENABLED` / `AIOA_GITEE_SYNC_ENABLED` | `false` | 私网 IP 无法被 Gitee 回调，先关（功能自动隐藏） |

## 哪些文件要改、哪些不用改（★真实值只写 `.env`）
- **真实密钥只写 `deploy/.env`** —— 实测 `git check-ignore deploy/.env` = IGNORED（`.gitignore:33 .env`）。
  本机路径 `C:\Users\刘尖尖\WorkBuddy\aioa\deploy\.env`；服务器路径 `/opt/aioa/deploy/.env`（`cp .env.production .env` 生成）。
- ⚠️ **`deploy/.env.production` 不被 git 忽略**：`.gitignore` 有 `!deploy/.env.production` 反选，
  实测 `git check-ignore` 判 **NOT ignored**（当前未跟踪 `??`，下次 `git add -A` 即入库）。
  ⇒ 它只允许放 `CHANGE_ME__` 占位，**填真实密钥等于把密码提交进仓库**。
- 已改完、**用户不用动**：`deploy/docker-compose.yml` · `deploy/nginx/nginx.conf` · `deploy/.env.production`(模板)。
- 文件里共 **12 处真占位**：9 处随机密钥（不同行号，须一次 sed 全改）+ 3 处同一个 DB 密码
  （`SPRING_DATASOURCE_PASSWORD` / `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD`，**三个必须同值**）；
  另有 3 行顶部说明注释含 `CHANGE_ME__` 字样（查残留时必须 `grep -v ':#'` 排除）。

## 端口避让（生产机已占用）
- `milvus-minio` 占 **9000/9001**、`milvus-standalone` 占 **19530/9091**。
- ⇒ 本项目 MinIO 控制台改 **`9011:9001`**；⇒ **禁用 `--profile milvus`**（会起第二套撞端口）。
- nginx 卷挂载 `../user-client/index.html` → `/usr/share/nginx/html/h5/index.html`，并提供 `location /h5/`。
  H5 与管理端都用**同源相对路径**（`/api`、`/api/v1`）⇒ 换 IP / 域名**无需重新构建前端**。

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
