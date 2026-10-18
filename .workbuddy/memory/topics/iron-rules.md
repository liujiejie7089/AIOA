# 铁律 21–35（续 `MEMORY.md` §1，按编号承接）

> 前 20 条在 `MEMORY.md`（那份必须 ≤3000 字节，否则注入时被截断）。
> 编号全仓唯一，引用铁律时直接说编号即可。

21. **「兜底写在 `isEmpty()` 上而容器永远非空 ⇒ 永不触发」**是高频反模式；同族：**显式传空串覆盖字段默认值**（`os.getenv(K,"")` ⇒ 默认密钥永不生效 ⇒ 全站 401）。断言须落到键级。
22. **诊断顺序：复现 → traceId → 日志栈 → A/B 对照**，不是读代码猜；字段口径不一致必查前端请求体。
23. MySQL `INSERT...SELECT` + `ON DUPLICATE KEY UPDATE` 必须写目标表全名；Flyway 失败留 `success=0` 行，不清掉每次启动都失败。
24. 改后端先确认「跑着的产物」含本次改动（比 mtime）；无侵入验证 = tar 源码到临时目录另起端口。
25. 「缓存+复用」必须带失效条件（以当初绑定的 worker/项目为条件），并固化成静态指纹。
26. PowerShell 工具在本机可能恒返回空输出 ⇒ 别用它杀进程（用 `python -c "os.kill(pid,SIGTERM)"`）；腾端口优先换端口。
27. ★禁用 `git commit --amend`/`rebase`/`reset --hard`/`gc`/`stash`/`git add -A`；证「测试会红」→ 改临时拷贝。
28. **`agent/aios_ai/` 是 AI 唯一归属地，单向 `app → aios_ai`**；只有 `graph/` 可 import langgraph；判据 `_check_aios_ai_boundary.py`。
29. 改 `graph/` 时运行期对象绝不进图状态（httpx/WallClock/ToolClient）；**`clarify` 必须独立节点**（恢复时整节点重跑）。
30. 跑 agent 侧 pytest/哨兵**必须用 `agent/.venv/Scripts/python.exe`**（托管 venv 没 langgraph ⇒ 假性全红）。
31. 新增 `settings.X` 前先查有没有哨兵把 `settings` 换成 shim；双管：shim 补字段 + `getattr(settings,"X",默认)`。
32. 迁移文件绝不能出现「美元符号 + 左花括号」（含注释）⇒ Flyway 占位符；用 `§` + `REPLACE(...,CHAR(36))`。
33. 对比两链路口径时先找有没有第二份手写实现：这类漂移不报错、只静默退化。
34. 本机 `curl` 走系统代理：探活一律 `--noproxy '*'`，否则没起的服务回 502，像「半死不活」。
35. **内部端点签了令牌后，脚本/测试必须带票**：脚本 `scripts/_svc_token.py`，pytest `agent/tests/_svc.py`。漏票的失败很像「服务挂了」。
36. **大目录批量写有沙箱闸门**：对万级小文件目录 `cp -a` / `robocopy` 可能被静默 SIGTERM（无报错、只半份）。
    判据：目标体积远小于源（`du -sh` 对比）+ 目录数齐但文件不全。要拷先 `/MT:16`，仍失败就换策略而不是重试。
