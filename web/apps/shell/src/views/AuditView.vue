<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="操作审计"
      description="租户内操作日志留痕倒序展示（谁在什么时间做了什么、结果如何），覆盖登录、审批、知识库、配额等关键操作，满足权限变更审计要求。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>操作日志</span>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-input v-model="kw" placeholder="按操作 / 操作人筛选" clearable size="small" style="width: 200px" />
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="filtered" stripe size="small">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ String(row.createdAt).replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作人" prop="userName" width="110" />
        <el-table-column label="操作" prop="action" min-width="220" show-overflow-tooltip />
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="tagType(row.status)" effect="plain" size="small">{{ tagLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明" prop="label" min-width="160" show-overflow-tooltip />
        <template #empty><el-empty description="暂无操作记录" :image-size="70" /></template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listAuditLogs, type AuditRow } from '@/api/resource'

const loading = ref(false)
const rows = ref<AuditRow[]>([])
const kw = ref('')

const filtered = computed(() => {
  const k = kw.value.trim()
  if (!k) return rows.value
  return rows.value.filter((r) => (r.action || '').includes(k) || (r.userName || '').includes(k))
})

async function reload() {
  loading.value = true
  try {
    rows.value = (await listAuditLogs(200)) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('操作审计仅租户管理员可查看')
      rows.value = []
    } else {
      ElMessage.error('审计日志加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

function tagType(s?: string): 'success' | 'danger' | 'warning' | 'info' {
  if (s === 'ok' || s === 'SUCCESS') return 'success'
  if (s === 'fail' || s === 'FAILED') return 'danger'
  if (s === 'wait') return 'warning'
  return 'info'
}

function tagLabel(s?: string): string {
  if (s === 'ok' || s === 'SUCCESS') return '成功'
  if (s === 'fail' || s === 'FAILED') return '失败'
  if (s === 'wait') return '进行中'
  return s || '—'
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
