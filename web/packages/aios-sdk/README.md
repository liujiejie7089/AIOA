# @aios/sdk

AIOS 智能办公基座 **子应用接入 SDK**。框架无关（Vue/React/jQuery 均可），基于 `window.postMessage` 与工作台主应用通信。

**独立运行保障**：不在工作台内（`window === window.parent`）时，全部 API 降级为 no-op，不抛错，子应用可照常单独使用。

## 安装

```bash
pnpm add @aios/sdk
```

## 三步接入

```ts
// 1. 入口最早期创建桥接实例（按 appCode 幂等）
import { createAiosBridge } from '@aios/sdk'

const aios = createAiosBridge({ appCode: 'ticket' })

if (aios.inWorkbench) {
  console.log('运行在 AIOS 工作台内')
}

// 2. 页面切换 / 筛选变化时上报上下文（增量合并）
aios.setContext({
  page: 'ticket-list',
  pageTitle: '工单列表',
  entityType: 'ticket',
  entityId: undefined,
  filters: { status: 'OPEN' },
  selection: []
})

// 3. 需要时唤起助手 / 接收反向动作
aios.openAssistant({ preset: '帮我总结当前筛选下的工单' })

aios.onAction('refresh', () => loadList())
aios.onAction('openPage', (p: { path: string }) => router.push(p.path))
```

## API

| API | 说明 |
|---|---|
| `createAiosBridge({ appCode })` | 创建/复用桥接实例 |
| `aios.inWorkbench` | 是否运行在工作台内 |
| `aios.setContext(ctx)` | 上报页面上下文（增量合并缓存 + postMessage） |
| `aios.getContext()` | 读取本地缓存的上下文快照 |
| `aios.openAssistant({ preset })` | 唤起主应用 AI 助手抽屉并预填问题 |
| `aios.onAction(type, handler)` | 监听反向动作，返回取消注册函数 |
| `aios.notify(message, kind)` | 主应用右上角通知，kind: info/success/warning/error |
| `aios.getToken()` | **M1 恒返回 null**（token 由主应用持有，子应用暂不直连基座 API） |

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
| 子 → 主 | `AIOS_SET_CONTEXT` | `{ appCode, context }` |
| 子 → 主 | `AIOS_OPEN_ASSISTANT` | `{ appCode, preset }` |
| 子 → 主 | `AIOS_NOTIFY` | `{ appCode, message, kind }` |
| 主 → 子 | `AIOS_ACTION` | `{ appCode, action: { type, payload } }` |

M1 统一 `postMessage(..., '*')`，M3 收紧为可控 origin 白名单。

## 构建

```bash
pnpm build   # tsc 产出 d.ts + vite 产出 ESM/CJS
```
