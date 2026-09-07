<template>
  <div class="ticket-app">
    <header class="nav">
      <div class="nav-left">
        <span class="nav-title">票务工单系统</span>
        <span class="nav-sub">demo-ticket · appCode: ticket</span>
      </div>
      <div class="nav-right">
        <el-button size="small" type="primary" @click="onAsk">问 AI</el-button>
      </div>
    </header>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getBridge, REFRESH_EVENT } from './aioa'

const router = useRouter()

function onAsk() {
  const aioa = getBridge()
  aioa.openAssistant({ preset: '帮我总结当前筛选下的工单' })
  aioa.notify('已唤起 AI 助手', 'info')
}

onMounted(() => {
  const aioa = getBridge()

  // 主应用要求刷新列表
  aioa.onAction('refresh', () => {
    console.log('[ticket] 收到 refresh 动作')
    window.dispatchEvent(new Event(REFRESH_EVENT))
    ElMessage.success('已按助手要求刷新列表')
  })

  // 主应用要求跳转到指定页面
  aioa.onAction('openPage', (payload: unknown) => {
    console.log('[ticket] 收到 openPage 动作', payload)
    const path = (payload as { path?: string } | undefined)?.path
    if (!path) {
      console.warn('[ticket] openPage 缺少 path')
      return
    }
    void router.push(path)
  })
})
</script>

<style scoped>
.ticket-app {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: #1f2d3d;
  color: #fff;
  flex: 0 0 48px;
}

.nav-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.nav-title {
  font-size: 16px;
  font-weight: 600;
}

.nav-sub {
  font-size: 12px;
  color: #9fb3c8;
}

.content {
  flex: 1;
  padding: 16px;
  overflow: auto;
}
</style>
