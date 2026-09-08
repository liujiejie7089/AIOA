<template>
  <div>
    <el-card class="welcome" shadow="never">
      <div class="welcome-line">
        <div>
          <div class="welcome-title">你好，{{ auth.displayName }}</div>
          <div class="welcome-sub">欢迎使用 AIOA 智能办公基座 · 企业智能办公一体化平台</div>
        </div>
        <el-button type="primary" @click="assistant.openDrawer()">唤起 AI 助手</el-button>
      </div>
    </el-card>

    <div class="stat-row">
      <el-card v-for="item in stats" :key="item.label" shadow="never" class="stat-card">
        <div class="stat-label">{{ item.label }}</div>
        <div class="stat-value">{{ item.value }}</div>
        <div class="stat-foot">实时统计</div>
      </el-card>
    </div>

    <!-- 未接入任何业务应用时不展示该区块 -->
    <el-card v-if="!apps.loading && apps.enabled.length" shadow="never">
      <template #header>
        <div class="card-header">
          <span>我的应用</span>
          <el-button text type="primary" size="small" :loading="apps.loading" @click="apps.list(true)">刷新</el-button>
        </div>
      </template>
      <div class="card-grid">
        <div v-for="item in apps.enabled" :key="item.appCode" class="app-card" @click="openApp(item.appCode)">
          <div class="app-icon">
            <el-icon><Grid /></el-icon>
          </div>
          <div class="app-body">
            <div class="app-name">{{ item.appName }}</div>
            <div class="app-desc">{{ item.description || item.entryUrl }}</div>
          </div>
          <el-tag size="small" :type="item.hostType === 'wujie' ? 'success' : 'warning'" effect="plain">
            {{ item.hostType }}
          </el-tag>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { homeStats } from '@/api/resource'
import { useAuthStore } from '@/stores/auth'
import { useAppsStore } from '@/stores/apps'
import { useAssistantStore } from '@/stores/assistant'

const router = useRouter()
const auth = useAuthStore()
const apps = useAppsStore()
const assistant = useAssistantStore()

const stats = ref([
  { label: '待我审批', value: '—' },
  { label: 'AI 会话', value: '—' },
  { label: 'AI 运行', value: '—' },
  { label: '已接入应用', value: '—' }
])

onMounted(async () => {
  // 真实统计：待审批/会话/运行来自后端，已接入应用取应用注册表实时数据
  apps.list()
  try {
    const s = await homeStats()
    stats.value = [
      { label: '待我审批', value: String(s.todoApprovals) },
      { label: 'AI 会话', value: String(s.aiConversations) },
      { label: 'AI 运行', value: String(s.aiRuns) },
      { label: '已接入应用', value: String(apps.enabled.length) }
    ]
  } catch {
    /* 403 等场景保留占位符，不打断首页 */
  }
})

function openApp(appCode: string) {
  void router.push(`/app/${appCode}`)
}
</script>

<style scoped>
.welcome {
  margin-bottom: 12px;
}

.welcome-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.welcome-title {
  font-size: 18px;
  font-weight: 600;
}

.welcome-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.stat-label {
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  margin: 4px 0;
}

.stat-foot {
  font-size: 11px;
  color: #c0c4cc;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.app-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--aioa-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.app-card:hover {
  border-color: var(--aioa-primary);
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.app-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 6px;
  background: #ecf5ff;
  color: var(--aioa-primary);
  font-size: 18px;
}

.app-body {
  flex: 1;
  min-width: 0;
}

.app-name {
  font-size: 14px;
  font-weight: 600;
}

.app-desc {
  font-size: 12px;
  color: var(--aioa-text-sub);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
