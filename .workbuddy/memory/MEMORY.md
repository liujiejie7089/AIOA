# AIOA 长期记忆（索引 + 铁律）

> 只放「每次都要遵守的」+ 索引。明细在 `topics/`（功能域要点 `topics/features.md`），故事 `YYYY-MM-DD.md`。

## 0. 索引

| 主题 | 文件 |
|---|---|
| **功能域要点**（H5 双形态 / OA 43 模块 / 表单三道闸 / HITL / 服务间令牌 / KB 降级 / 多租户 / kb_on） | **`topics/features.md`** |
| 结构·打包·起服务·端口·账号·env·Flyway | `topics/runtime-env.md` |
| 编码·排查（**已修坑清单勿回退**；含**禁删清单**） | `topics/pitfalls.md` |
| 跑套件·验收·收口 | `topics/e2e-suites.md` |
| 接口·登录·角色·权限链 | `topics/api-permissions.md` |
| 知识库·检索·向量库 | `topics/vector-store-milvus.md` |
| Gitee/Gitea 联动 | `topics/repo-provider-gitea.md` |
| 模型管理（V61，默认 MiniMax） | `topics/model-config.md` |
| 生产部署（10.0.0.3） | `topics/production-deploy.md` + `deploy/生产部署手册.md` |
| 已知缺口 /「判定不改」 | `topics/known-gaps.md` |
| git 推送 | `topics/git-remote.md` |
| 进度口径 | `docs/28 §6`（未开工项唯一权威）· `docs/19` |

## 1. 铁律

1. **展示与事实同源**：一个决策点只在一处判定；回填文案不得照抄历史原文。
2. **每步失败都要有终态**；不可逆动作绝不静默成功。
3. 前端 `unwrap` 必须校验 `code`，否则失败信封被当业务数据 ⇒ 页面空白。
4. **管理端配置页 = 能力唯一入口**：配不出来 = 事实上不可用；须无损往返。
5. **新增可配置维度 ⇒ 必须为该维度造出旧状态机没有的组合并断言**。
6. 诊断端点回「报告」（恒 200 + `code=0` + `steps`），动作端点才失败即抛；`passed` 与 `steps` 同源。
7. **绝不为转绿放宽断言**；恒真断言比没断言更危险；新「同源」断言先跑负向测试证它会红。
8. 改权限/可见性/生效态/登录口径后：全局搜旧口径断言 + 连跑两次；历史遗留行 ≠ 代码 bug。
9. 管理端测试逐角色分进程；长驻服务绝不交给子代理启动。
10. **禁用 `git rm`**：用 `rm 明确列表` + `git add`，每批核对 `git status`。
11. 「与基线一致」≠ 干净：残留数按命名前缀断言为 0；造数据收尾要让数据退出业务可见面。
12. 断言「界面展示了某事实」时，判据不得与被测对象同源（回接口/库再取一次）。
13. **清理前先过禁删清单**（引用即保留）——完整清单见 `topics/pitfalls.md`。
14. **`nohup X &` 起的进程随该次 Bash 调用被回收**（日志末尾正常、进程突然消失 = 被外部回收，别翻日志）。长期运行只能由用户终端启动。
15. 跑套件前先验 fixture；环境漂移不许换账号硬跑，如实记「本环境跑不起来」。
16. JDK `HttpClient` 默认 HTTP/2，对明文 http 会发 h2c 升级 ⇒ 明文客户端必须钉 HTTP/1.1。
17. 共享消费者对可选回调必须逐一守存在（`if(h.onXxx)`）。
18. **「源码里有」≠「运行实例里有」**：判据看 jar 内嵌 class / `/openapi.json` / `flyway_schema_history`。就绪判据不得用 `/aioa/actuator/health`（恒 401）。
19. 元素改成默认隐藏 ⇒ 只挑可见元素的测试会静默缩水；`el.click()` 证明不了「用户点得到」。
20. 推 github 先探 HTTPS / SSH22 / ssh.github.com:443；`ls-remote` 通 ≠ 能 push；按 SHA 比对。
21. **「兜底写在 `isEmpty()` 上而容器永远非空 ⇒ 永不触发」**是高频反模式；同族：**显式传空串覆盖字段默认值**（`os.getenv(K,"")` ⇒ 默认密钥永不生效 ⇒ 全站 401）。断言须落到键级。
22. **诊断顺序：复现 → traceId → 日志栈 → A/B 对照**，不是读代码猜；字段口径不一致必查前端请求体。
23. MySQL `INSERT...SELECT` + `ON DUPLICATE KEY UPDATE` 必须写目标表全名；Flyway 失败留 `success=0` 行，不清掉每次启动都失败。
24. 改后端先确认「跑着的产物」含本次改动（比 mtime）；无侵入验证 = tar 源码到临时目录另起端口。
25. 「缓存+复用」必须带失效条件（以当初绑定的 worker/项目为条件），并固化成静态指纹。
26. PowerShell 工具在本机可能恒返回空输出 ⇒ 别用它杀进程（用 `python -c "os.kill(pid,SIGTERM)"`）；腾端口优先换端口。
27. ★禁用 `git commit --amend`/`rebase`/`reset --hard`/`gc`/`stash`/`git add -A`；证「测试会红」→ 改临时拷贝。
28. **`agent/aioa_ai/` 是 AI 唯一归属地，单向 `app → aioa_ai`**；只有 `graph/` 可 import langgraph；判据 `_check_aioa_ai_boundary.py`。
29. 改 `graph/` 时运行期对象绝不进图状态（httpx/WallClock/ToolClient）；**`clarify` 必须独立节点**（恢复时整节点重跑）。
30. 跑 agent 侧 pytest/哨兵**必须用 `agent/.venv/Scripts/python.exe`**（托管 venv 没 langgraph ⇒ 假性全红）。
31. 新增 `settings.X` 前先查有没有哨兵把 `settings` 换成 shim；双管：shim 补字段 + `getattr(settings,"X",默认)`。
32. 迁移文件绝不能出现「美元符号 + 左花括号」（含注释）⇒ Flyway 占位符；用 `§` + `REPLACE(...,CHAR(36))`。
33. 对比两链路口径时先找有没有第二份手写实现：这类漂移不报错、只静默退化。
34. 本机 `curl` 走系统代理：探活一律 `--noproxy '*'`，否则没起的服务回 502，像「半死不活」。
35. **内部端点签了令牌后，脚本/测试必须带票**：脚本 `scripts/_svc_token.py`，pytest `agent/tests/_svc.py`。漏票的失败很像「服务挂了」。
