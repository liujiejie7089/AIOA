# Kubernetes 部署清单

> **状态：未经真机集群验证。** 本仓库的开发与验收都在本机（Docker Compose / 直连进程）
> 完成，这套清单是给需要上 K8s 的场景准备的起点，落地前请按自身环境调整：
> 存储类（StorageClass）、Ingress 控制器、镜像仓库地址、密钥管理方式是四个必改项。

## 应用顺序

```bash
kubectl apply -f 00-namespace-config.yaml
kubectl apply -f 10-server.yaml
kubectl apply -f 20-agent.yaml
kubectl apply -f 30-web-ingress.yaml
# 可选：向量库 Milvus 单机栈（对应 compose 的 profile=milvus，见 docs/32）
kubectl apply -f 40-milvus.yaml
```

## 切到 Milvus 向量库（可选）

默认 `AIOS_KB_STORE=mysql`（切片与向量都在 MySQL，零新增依赖）。要换取向量库：

1. `kubectl apply -f 40-milvus.yaml`，等 `milvus` Pod 的 readiness 通过
   （首次启动要建集合，`initialDelaySeconds` 给了 90s）。
2. 首次切换先补齐切片向量：把 ConfigMap 的 `AIOS_KB_REEMBED_ON_START` 改 `"true"`，
   并配好 `AIOS_KB_EMBEDDING_URL`（未配 http 嵌入时它会退回无语义的本地哈希，
   检索「不出错但也搜不到」）。
3. 再把 `AIOS_KB_STORE` 改成 `"milvus"` 并重启 server。**Milvus 不可达时 server 会直接启动失败**
   （决策 D6 fail-fast：宁可起不来，也不要静默返回空结果），这是预期行为。
4. 存量索引可从 MySQL 重建：`AIOS_MILVUS_BACKFILL=true` 跑一次再改回 `"false"`。
   因此 `etcd-data` / `milvus-minio-data` / `milvus-data` 三个 PVC 都是**可丢的**。
5. 回滚 = 把 `AIOS_KB_STORE` 改回 `"mysql"` 重启，无需改代码。

镜像需先构建推送（`aios/server`、`aios/agent`，Dockerfile 在 `deploy/`）：

```bash
docker build -f deploy/Dockerfile.server -t aios/server:latest .
docker build -f deploy/Dockerfile.agent  -t aios/agent:latest  agent/
```

> **说明（docs/33 单端口改造）**：`aios/web` 镜像**已不再需要**。`aios-server` 镜像在构建期已把
> 用户端 H5（`/app/h5`）与管理端 dist（`/app/web`）一并打进镜像（`deploy/Dockerfile.server` 阶段 1 + 阶段 3，
> `COPY --from=web /out/h5 /app/h5` 与 `/out/web /app/web`），不再有独立的 `aios-web` 容器 / 镜像。
> 相应地，本目录下的 `30-web-ingress.yaml` 已删除 `Deployment aios-web` 与 `Service aios-web`，
> Ingress 三个前缀统一指回 `aios-server:8080`。
> （`deploy/Dockerfile.web` 当前无构建管线引用——`deploy/ops/offline-images.sh` 的 `BUILT_IMAGES`
> 仅剩 `aios-server` / `aios-agent` 两张——仅作为历史遗留文件保留，k8s 路径不再构建它。）

## 五个容易踩的点

1. **Flyway 迁移与滚动更新**：server 用 `strategy: Recreate`，避免两个实例同时抢迁移锁。
   readinessProbe 的 `initialDelaySeconds` 给到 60s（首次冷启动 + 迁移可能很慢）。
2. **SSE 必须关代理缓冲**：本清单的 Ingress annotation 必须关（`proxy_buffering off`，已配在 `30-web-ingress.yaml`）；k8s 路径没有独立的 nginx 层，
   否则流式回答会攒到结束才一次性到达前端——表现为「转圈很久然后突然全出来」。
3. **uploads 必须是 ReadWriteMany**：附件与知识库原文落盘，多副本用 RWO 会调度失败。
4. **agent 多副本前先改幂等缓存**：计划执行的回放缓存在进程内存里，多副本时重连可能
   命中不到缓存而重跑计划。见《docs/adr/ADR-004-计划执行按run_id幂等回放.md》。
5. **ASR 模型必须由节点提供**：`aios/agent` 镜像**不含**语音模型（`deploy/Dockerfile.agent` 只 `COPY app`；
   模型约 483MB，且被 `.gitignore` 忽略，进不了 git）。`20-agent.yaml` 已声明
   `hostPath: /opt/aios/asr-models` 以**只读**方式挂到容器 `/app/.models`
   ⇒ **每个可能被调度到的节点都要在该目录下放好 `<模型名>/`（默认 `small/`，含
   model.bin / config.json / tokenizer.json / vocabulary.txt）**。
   缺了不会让 Pod 起不来（`DirectoryOrCreate` 会建一个空目录），但语音接口会返回 503、
   H5 麦克风按钮会置灰。诊断：
   `kubectl -n aios exec deploy/aios-agent -- curl -s localhost:8000/internal/v1/asr/status` 看 `available`。
   要用集群共享存储，就把那段 `hostPath` 换成已预置模型的 PVC。

## 密钥

`00-namespace-config.yaml` 里的 Secret 是**样例**。真实部署请用：

```bash
kubectl -n aios create secret generic aios-secrets \
  --from-literal=MYSQL_PASSWORD='...' \
  --from-literal=JWT_SECRET='...' \
  --from-literal=SERVICE_JWT_SECRET='...' \
  --from-literal=DEEPSEEK_API_KEY='...'
```

不要把明文 Secret 提交进仓库。
