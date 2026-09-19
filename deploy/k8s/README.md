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

默认 `AIOA_KB_STORE=mysql`（切片与向量都在 MySQL，零新增依赖）。要换取向量库：

1. `kubectl apply -f 40-milvus.yaml`，等 `milvus` Pod 的 readiness 通过
   （首次启动要建集合，`initialDelaySeconds` 给了 90s）。
2. 首次切换先补齐切片向量：把 ConfigMap 的 `AIOA_KB_REEMBED_ON_START` 改 `"true"`，
   并配好 `AIOA_KB_EMBEDDING_URL`（未配 http 嵌入时它会退回无语义的本地哈希，
   检索「不出错但也搜不到」）。
3. 再把 `AIOA_KB_STORE` 改成 `"milvus"` 并重启 server。**Milvus 不可达时 server 会直接启动失败**
   （决策 D6 fail-fast：宁可起不来，也不要静默返回空结果），这是预期行为。
4. 存量索引可从 MySQL 重建：`AIOA_MILVUS_BACKFILL=true` 跑一次再改回 `"false"`。
   因此 `etcd-data` / `milvus-minio-data` / `milvus-data` 三个 PVC 都是**可丢的**。
5. 回滚 = 把 `AIOA_KB_STORE` 改回 `"mysql"` 重启，无需改代码。

镜像需先构建推送（`aioa/server`、`aioa/agent`、`aioa/web`，Dockerfile 在 `deploy/`）：

```bash
docker build -f deploy/Dockerfile.server -t aioa/server:latest .
docker build -f deploy/Dockerfile.agent  -t aioa/agent:latest  agent/
docker build -f deploy/Dockerfile.web    -t aioa/web:latest    .
```

## 四个容易踩的点

1. **Flyway 迁移与滚动更新**：server 用 `strategy: Recreate`，避免两个实例同时抢迁移锁。
   readinessProbe 的 `initialDelaySeconds` 给到 60s（首次冷启动 + 迁移可能很慢）。
2. **SSE 必须关代理缓冲**：Ingress 与 nginx 两处都要关（`proxy_buffering off`），
   否则流式回答会攒到结束才一次性到达前端——表现为「转圈很久然后突然全出来」。
3. **uploads 必须是 ReadWriteMany**：附件与知识库原文落盘，多副本用 RWO 会调度失败。
4. **agent 多副本前先改幂等缓存**：计划执行的回放缓存在进程内存里，多副本时重连可能
   命中不到缓存而重跑计划。见《docs/adr/ADR-004-计划执行按run_id幂等回放.md》。

## 密钥

`00-namespace-config.yaml` 里的 Secret 是**样例**。真实部署请用：

```bash
kubectl -n aioa create secret generic aioa-secrets \
  --from-literal=MYSQL_PASSWORD='...' \
  --from-literal=JWT_SECRET='...' \
  --from-literal=SERVICE_JWT_SECRET='...' \
  --from-literal=DEEPSEEK_API_KEY='...'
```

不要把明文 Secret 提交进仓库。
