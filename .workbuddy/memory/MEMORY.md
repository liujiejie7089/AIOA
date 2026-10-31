# AIOS 长期记忆（索引）

> 仓库根 `D:\aios`。**≤3000 字节**（超限静默截断）⇒ 只放索引；铁律见 `topics/iron-rules.md`，明细 `topics/`，故事 `YYYY-MM-DD.md`。

## 索引

| 主题 | 文件 |
|---|---|
| **铁律 1–36（引用只报编号）** | **`topics/iron-rules.md`** |
| 功能域要点（H5/OA/表单三道闸/HITL/多租户） | `topics/features.md` |
| 结构·打包·起服务·端口·账号·env·Flyway | `topics/runtime-env.md` |
| 编码·排查（**已修坑勿回退**；禁删清单） | `topics/pitfalls.md` |
| 跑套件·验收·收口（项数/前置） | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 向量库/Gitee/模型/部署 | `topics/vector-store-milvus.md` · `repo-provider-gitea.md` · `model-config.md` · `production-deploy.md` |
| 缺口/git/进度 | `topics/known-gaps.md` · `topics/git-remote.md` · `docs/28 §6` |
| 连接器接入 MCP·企微扫码连接态 | `docs/59 §10` · hub :8099 · V97 三表 · `docs/64 §九` |
| 能力层/日程会议 | `aios_ai/capabilities/` · `docs/65` · `_e2e_portal…`(24) |
| **对话级开关/遮罩渐隐/连接器开关** | `2026-10-31.md` 第七~九轮 · pitfalls 33–46 |

## 最常踩的五条（全文见 iron-rules）

- **7 / 12**：不为转绿放宽断言；「界面展示了 X」须回接口/库再取（不得同源）。
- **14 / 26**：`nohup &` 起的服务会被回收；shell 工具可能恒返空。
- **18 / 24**：看运行实例不看 mtime；**Java 改动必须重启**，打包前停进程。
- **34**：curl 走系统代理，探活加 `--noproxy '*'`。
- **30**：agent pytest/哨兵用 `agent/.venv/Scripts/python.exe`。

## 新增坑（全文见 pitfalls，引用只报编号）

- **29 / 30**：校验失败 **≠ HTTP 400** —— 约定 **HTTP 200 + 信封 `code=400`**（仅 401/403/404 映射）⇒ 断言查 `body.code`。Java 侧禁 `IllegalArgumentException`（落 500），用 `BizException.badRequest`。
- **31 / 32**：起后端加 `-Dspring.flyway.validate-on-migrate=false`；e2e 期望值按真实 uid 动态算。
- **33–39**：对话级开关同 `kb_on` 链路；`.cbtn` 必须写全 `flex:0 0 auto`；`--hd` 渐隐在 scroll 监听器、滚动容器 `#oaDockList`；计数要回接口核来源；e2e 用带 pymysql 的解释器。
- **40**：中文提交信息**不能用 `-m "中文"`**（argv 编码 ⇒ 汉字成 U+FFFD，push 不报错）⇒ 用 heredoc 或 `-F 文件`；改已推送信息先比 `^{tree}` 再 `--force-with-lease`。
- **41**：遮罩让位**只能移 `.dock` 视口**（负 margin-top）+ **实测**遮罩高 `--mask-h`；收 `.assist/.stage` 高度会移走数字人锚点并让 `maxScroll` 变小 ⇒ 翻历史被顶走。
- 其余散项：哨兵快照复位 · 工具描述日志 · trust 快照 V104 · mock 掩盖真机差异 · H5 生效文件 `user-client/index.html` · 禁编禁外发。
