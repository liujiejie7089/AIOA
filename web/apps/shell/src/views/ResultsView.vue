<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="成果沉淀"
      description="用户在会话中「存为成果」的产出物，可查看正文与审批状态。此处仅管理员可见全部成员成果。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>成果列表</span>
          <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="标题" min-width="220">
          <template #default="{ row }">
            <span class="r-title" @click="view(row)">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column label="归属用户 ID" prop="userId" width="110" />
        <el-table-column label="元信息" prop="meta" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" effect="plain" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="view(row)">查看</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无成果沉淀" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="current?.title || '成果详情'" width="620px">
      <div class="r-meta">{{ current?.meta || '—' }}</div>
      <div class="r-body">{{ current?.body || '（无正文）' }}</div>
      <template #footer>
        <el-button size="small" @click="dlg = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminDeleteResult, adminListResults, type UserResultItem } from '@/api/resource'

const loading = ref(false)
const rows = ref<UserResultItem[]>([])
const dlg = ref(false)
const current = ref<UserResultItem | null>(null)

function statusLabel(s: string): string {
  if (s === 'SUBMITTED') return '审批中'
  if (s === 'APPROVED') return '已通过'
  return '草稿'
}
function statusTag(s: string): 'success' | 'warning' | 'info' {
  if (s === 'APPROVED') return 'success'
  if (s === 'SUBMITTED') return 'warning'
  return 'info'
}
function fmtTime(t?: string): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

async function reload() {
  loading.value = true
  try {
    rows.value = (await adminListResults()) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('成果查看仅租户管理员可操作')
      rows.value = []
    } else {
      ElMessage.error('成果加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

function view(row: UserResultItem) {
  current.value = row
  dlg.value = true
}

async function remove(row: UserResultItem) {
  try {
    await ElMessageBox.confirm(`确认删除成果「${row.title}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await adminDeleteResult(row.id)
  ElMessage.success('已删除')
  await reload()
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.r-title {
  font-weight: 600;
  color: var(--el-color-primary);
  cursor: pointer;
}

.r-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}

.r-body {
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  max-height: 380px;
  overflow: auto;
}
</style>
