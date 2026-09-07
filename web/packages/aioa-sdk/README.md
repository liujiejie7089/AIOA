# @aioa/sdk

AIOA 智能办公基座 **子应用接入 SDK**。框架无关（Vue/React/jQuery 均可），基于 `window.postMessage` 与工作台主应用通信。

**独立运行保障**：不在工作台内（`window === window.parent`）时，全部 API 降级为 no-op，不抛错，子应用可照常单独使用。

## 安装

```bash
pnpm add @aioa/sdk
```

## 三步接入

```ts
// 1. 入口最早期创建桥接实例（按 appCode 幂等）
import { createAioaBridge } from '@aioa/sdk'

const aioa = createAioaBridge({ appCode: 'ticket' })

if (aioa.inWorkbench) {
  console.log('运行在 AIOA 工作台内')
}

// 2. 页面切换 / 筛选变化时上报上下文（增量合并）
aioa.setContext({
  page: 'ticket-list',
  pageTitle: '工单列表',
  entityType: 'ticket',
  entityId: undefined,
  filters: { status: 'OPEN' },
  selection: []
})

// 3. 需要时唤起助手 / 接收反向动作
aioa.openAssistant({ preset: '帮我总结当前筛选下的工单' })

aioa.onAction('refresh', () => loadList())
aioa.onAction('openPage', (p: { path: string }) => router.push(p.path))
```

## API

| API | 说明 |
|---|---|
| `createAioaBridge({ appCode })` | 创建/复用桥接实例 |
| `aioa.inWorkbench` | 是否运行在工作台内 |
| `aioa.setContext(ctx)` | 上报页面上下文（增量合并缓存 + postMessage） |
| `aioa.getContext()` | 读取本地缓存的上下文快照 |
| `aioa.openAssistant({ preset })` | 唤起主应用 AI 助手抽屉并预填问题 |
| `aioa.onAction(type, handler)` | 监听反向动作，返回取消注册函数 |
| `aioa.notify(message, kind)` | 主应用右上角通知，kind: info/success/warning/error |
| `aioa.getToken()` | **M1 恒返回 null**（token 由主应用持有，子应用暂不直连基座 API） |

## 上下文类型

```ts
interface PageContext {
  appCode: string
  page: string               // 英文且稳定，如 ticket-list
  pageTitle?: string
  entityType?: string
  entityId?: string
  filters?: Record<string, unknown>
  selection?: string[]
}
```

## 消息协议

| 方向 | type | 载荷 |
|---|---|---|
| 子 → 主 | `AIOA_SET_CONTEXT` | `{ appCode, context }` |
| 子 → 主 | `AIOA_OPEN_ASSISTANT` | `{ appCode, preset }` |
| 子 → 主 | `AIOA_NOTIFY` | `{ appCode, message, kind }` |
| 主 → 子 | `AIOA_ACTION` | `{ appCode, action: { type, payload } }` |

M1 统一 `postMessage(..., '*')`，M3 收紧为可控 origin 白名单。

## 构建

```bash
pnpm build   # tsc 产出 d.ts + vite 产出 ESM/CJS
```
