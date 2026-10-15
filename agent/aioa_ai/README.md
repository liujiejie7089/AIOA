# aioa_ai —— AI 能力内核（统一模块）

> 本包是 AIOA 平台**所有 AI 相关能力**的唯一归属地。
> 目标：职责单一、边界清晰、可按需替换实现、便于后续扩展。

## 1. 与 `agent/app/` 的分工（单向依赖）

| 包 | 角色 | 允许做什么 | 不允许做什么 |
|---|---|---|---|
| `agent/app/` | **服务接入层**（传输壳） | FastAPI 路由、SSE 帧传输、启动装配、健康检查 | **不得**承载 AI 逻辑（提示词、模型调用、工具编排、检索策略） |
| `agent/aioa_ai/` | **AI 能力内核**（本包） | 图运行时、模型接入、工具编排、知识检索、提示词、护栏、意图、事件、语音 | **不得**依赖 `app.*`；不得直接读写 HTTP 响应对象 |

**依赖方向固定为 `app → aioa_ai`（单向）。** 反向 import 视为架构违规，由静态哨兵拦截（见 §6）。

## 2. 目录地图

```
aioa_ai/
├── config.py          # 配置单一入口（.env + 环境变量），含图运行期开关
├── contracts.py       # 与 Java 侧的请求/事件契约类型（原 app/schemas.py）
├── events.py          # SSE 事件序列化（seq/type/data → SSE 帧）
├── guard.py           # 护栏：文本长度、墙钟、注入中和（原 app/core/guards.py）
├── entry.py           # ★ AI 层唯一入口：run(req) —— 按 provider.driver 分派 回声 / 图
│
├── prompt/            # 提示词与回答结构约束
│   ├── builder.py     #   消息构造（system + history + 附件 + KB 参考 + 注入中和）
│   └── answer.py      #   回答风格规则 rules/audit/card（原 answer_shape.py）
│
├── llm/               # 模型接入层（原 app/model_gateway/）
│   ├── __init__.py    #   Provider 注册表 + 三级降级 + 管理端热加载
│   ├── mock.py        #   本地兜底/回声模型
│   ├── upstream.py    #   OpenAI 兼容 /chat/completions 的流式与非流式协议适配
│   └── gateway.py     #   网关门面（re-export）
│
├── knowledge/         # 知识检索
│   ├── retrieval.py   #   参数注入 / KB 工具识别 / 预检索
│   └── kb.py          #   检索结果 → citations 溯源
│
├── tools/             # 工具层
│   ├── client.py      #   Java 工具网关客户端（原 app/tools_client.py）
│   ├── orchestrator.py#   同层并发编排（原 app/core/orchestrator.py）
│   ├── sandbox.py     #   轻量沙箱
│   └── gateway_client.py
│
├── intent/            # 意图识别（纯规则，不调模型）
│   ├── intake.py      #   数字员工类型识别（原 worker_intake.py）
│   └── router.py      #   意图路由（原 intent_router.py）
│
├── speech/            # 语音（ASR）
│   ├── engine.py
│   └── router.py
│
├── runtimes/          # 非图运行时（与「重建」并行保留的能力）
│   ├── echo.py        #   回声运行时（演示/兜底）
│   └── multi_task.py  #   显式计划执行（无模型推理）
│
└── graph/             # ★ LangGraph 运行时（**唯一**允许 import langgraph 的地方）
    ├── state.py       #   图状态定义（TypedDict；只放可序列化数据，运行期对象节点内重建）
    ├── nodes.py       #   节点：prepare / agent / tools / finalize
    ├── builder.py     #   StateGraph 装配（**缺省不挂 checkpointer**；HITL 时再传）
    └── facade.py      #   非回声路径的图入口：run(req) -> AsyncIterator[SseEvent]
```

## 3. 框架耦合边界（关键约束）

**只有 `aioa_ai/graph/` 可以 import `langgraph`。** 其他子包一律保持框架无关：
- 换框架（LangGraph → 其他）只改 `graph/`；
- `graph/` 之外的能力（模型/工具/检索/提示/护栏）可在任意运行时复用。

这条约束让 §7 的「未使用部分删减」成为**结构性保证**，而不是靠人工纪律。

## 4. 一次 run 的执行路径

```
app/main.py  POST /internal/v1/runs
   └─> aioa_ai.entry.run(req)                 # AI 层唯一入口，产出 SseEvent 流
         ├─(provider.driver == "echo")─> aioa_ai.runtimes.echo.run(req)
         └─(其它)─────────────────────> aioa_ai.graph.facade.run(req)
                                            └─> graph.build()   # StateGraph 装配（缺省无 checkpointer）
                                                  START → prepare → agent ⇄ tools → finalize → END
```
- 分派只判定一次（`entry.run`），图内不再判定 echo；对 `graph` 用**延迟导入**，回声路径不加载 langgraph。
- `prepare`：护栏 / 解析 provider / 合并专家配置 / 构造 messages / 拉工具 / 知识库预检索
- `agent`：调模型（流式），产出 `message.delta`，解析 `tool_calls`
- `tools`：执行工具（同层并发），产出 `tool.call` / `tool.result`，结果回注消息
- `finalize`：产出 `message.completed` + `run.completed`

事件序列与既有契约完全一致（`docs/04-接口契约/internal-agent.yaml`），**Java 侧与 H5 侧零改动**。

## 5. 迁移状态

| 子包 | 状态 |
|---|---|
| `graph/` | ✅ 新建（LangGraph 重建主体：prepare / agent / tools / finalize） |
| `entry.py` | ✅ 新建（AI 层唯一入口，回声 / 图分派） |
| `config.py` `contracts.py` `events.py` `guard.py` | ✅ 已迁移 |
| `prompt/` `llm/` `knowledge/` `tools/` `intent/` `speech/` `runtimes/` | ✅ 已迁移（实现只在 `aioa_ai`；`app/**` 对应文件已降级为再导出垫片） |

**垫片策略**：`agent/app/**` 里除服务壳（`main.py` 及若干 `__init__.py`）外的 AI 模块，
一律改成「只再导出、不含实现」的 deprecation shim，指向本包对应模块。
这样做的原因：`ToolClient` 等对象若存在两份副本，**测试打在 A 副本上的补丁不会作用于 B 副本**
（实测踩过：`patch.object(app.tools_client.ToolClient, ...)` 修不了图里用的那个类）。
单一实现 → 补丁、类型、行为只有一份真值。

## 6. 静态哨兵

`scripts/_check_aioa_ai_boundary.py`（本机长期哨兵，随 AI 重建新增）：
- C1 `aioa_ai/**` 不出现反向 `import app`（单向依赖）；
- C2 除 `aioa_ai/graph/` 外不出现**真正的** `langgraph` import（框架耦合边界）；
- C3 `app/**` 中除服务壳白名单外均为纯 shim（无 `def`/`class`/模块级赋值）；
- C4 `app/main.py` 不残留旧 `app.*` 业务导入；
- C5 `aioa_ai.entry` / `graph.facade` / `graph.builder` 可干净导入。
附 `--selftest` 用合成坏输入证明每条判据**确实会红**（防「恒真断言」）。

## 7. 本轮落地边界（已做 / 明确未做）

| 事项 | 状态 |
|---|---|
| 7 × 既有能力全部迁入 `aioa_ai`，门面切到 `entry.run` | ✅ 已做 |
| 框架耦合收敛到 `graph/`（未使用的 langgraph 能力一律未引入） | ✅ 已做 |
| checkpointer | ⛔ **缺省不挂**（见 §2 / builder.py）：当前无暂停续跑需求，挂了即「未使用部件」，且会强制状态可 msgpack 序列化、并使 checkpoint 随 run 数无界驻留内存 |
| HITL（`ask_user` 暂停 / `resume`） | ⏳ **未做**：落地时 `build(checkpointer=PostgresSaver/RedisSaver)` 接上即可，状态已按可序列化约束设计，不需要重构节点 |
| `message.delta` 与 `tool.call` 的严格先后 | ⚠️ **既有约束（非本轮引入）**：模型若在同一轮既流式吐字又返回 tool_calls，delta 会先于 `tool.call`；`_post_stream` 是原样迁出的逻辑，行为与重建前一致 |

## 8. 扩展指引

新增 AI 能力时，按职责放入对应子包；**不要**把逻辑写进 `app/main.py`。
需要新工具 → 在 Java 工具注册表登记（工具权限=用户权限），Python 侧零改动即可被发现。
需要新模型 → 在 `llm/` 注册表登记 provider（OpenAI 兼容协议）。
