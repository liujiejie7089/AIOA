# AIOS 长期记忆（索引）

> 根 `D:\aios`。**≤3000 字节**⇒只放索引；铁律 `iron-rules.md`，故事 `YYYY-MM-DD`。

## 索引

| 主题 | 文件 |
|---|---|
| **铁律 1–36（引用只报编号）** | **`topics/iron-rules.md`** |
| 功能域要点（H5/OA/表单闸/HITL/多租户） | `topics/features.md` |
| 结构·打包·起服务·端口·账号 | `topics/runtime-env.md` |
| 编码·排查（已修坑勿回退；禁删清单） | `topics/pitfalls.md` |
| 跑套件·验收（项数/前置） | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 向量库/Gitee/模型/部署 | `vector-store-milvus` · `repo-provider-gitea` · `model-config` · `production-deploy` |
| 缺口/git/进度 | `known-gaps` · `git-remote` · `docs/28 §6` |
| 连接器/MCP·企微扫码态 | `docs/59 §10` · hub :8099 · V97 · `docs/64 §九` |
| 能力层/日程会议 | `aios_ai/capabilities/` · `docs/65` |
| **对话级开关/渐隐/连接器** | `2026-10-31.md` 第七~九轮 · pitfalls 33–48 |
| **模型配置/热更新/回滚/目录** | `docs/72` · V106 · `model_config_snapshot` |
| **依赖/落盘（禁 /opt）** | `docs/67` · deps(28)/reap(26)/sandbox(21) · `deploy/ops/` |
| **知识库检索** | `docs/74–76` · pitfalls 67–75 |
| **H5/OA 五项交互** | `docs/77` · pitfalls 76–79 |
| **评审 11 项/会话列表** | `docs/78`·`docs/79`·pitfalls 80–89 |
| **越界建议/挑人卡（表单分离）** | `docs/81`–`83`·pitfalls 90–98 |

## 最常踩（全文见 iron-rules）

- **7 / 12**：不为转绿放宽断言；「界面展示了 X」须回接口/库再取（不得同源）。
- **14 / 26**：`nohup &` 起的服务会被回收；shell 工具可能恒返空。
- **18 / 24**：看运行实例不看 mtime；**Java 改动必须重启**，打包前停进程。
- **34**：curl 走系统代理，探活加 `--noproxy '*'`。
- **30**：agent pytest/哨兵用 `agent/.venv/Scripts/python.exe`。

## 新增坑（见 pitfalls）

- **29 / 30**：校验失败 **≠ 400** ⇒ 200 + 信封 `code=400`，断言查 `body.code`；Java 用 `BizException.badRequest`。
- **31 / 32**：起后端加 `-Dspring.flyway.validate-on-migrate=false`；e2e 期望值按真实 uid 动态算。
- **33–41**：对话级开关同 `kb_on` · `.cbtn` 写全 `flex:0 0 auto` · `--hd` 渐隐在 scroll 监听器（容器 `#oaDockList`）· 遮罩让位只移 `.dock` 视口 · 中文提交信息禁用 `-m "中文"`（argv 编码坏）⇒ heredoc/`-F`。
- **80–87**：软删复活只能裸 SQL（wrapper 也够不到）· MCP 适配器默认吞 isError · `sitecustomize` 不自动加载 · `503` 落 502 · `java -jar` 必带 `--aios.web.h5-dir` · hub 缺密钥 `/health` 503 · `nohup &` 被 SIGTERM 带走 · 守卫计扫描行。
- 散项：哨兵快照复位 · trust V104 · mock 掩盖真机差异 · H5 生效 `user-client/index.html` · 禁编禁外发。
