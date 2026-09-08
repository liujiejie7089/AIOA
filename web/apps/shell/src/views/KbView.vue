<template>
  <div>
    <el-alert
      v-if="tenantForbidden"
      type="info"
      :closable="false"
      show-icon
      title="「租户全部资料」仅租户管理员可见"
      description="普通用户可在下方「我的资料」查看与管理自己登记的知识文档。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <el-tabs v-model="tab" class="flex-tabs" @tab-change="reload">
            <el-tab-pane label="租户全部资料" name="tenant" />
            <el-tab-pane label="我的资料" name="mine" />
          </el-tabs>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
            <el-button type="primary" size="small" @click="register">登记资料</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="资料" min-width="280">
          <template #default="{ row }">
            <span class="doc-name"><span class="doc-icon">{{ row.icon || '📄' }}</span>{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="stateTag(row.state)" effect="plain">{{ stateLabel(row.state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ fmtSize(row.sizeBytes) }}</template>
        </el-table-column>
        <el-table-column v-if="tab === 'tenant'" label="归属用户 ID" width="120">
          <template #default="{ row }">{{ row.ownerUserId ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="登记时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="tab === 'tenant' ? '租户内暂无登记资料' : '你还没有登记过资料，点击右上角「登记资料」上传'"
            :image-size="80"
          />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listKbDocs, registerKbDoc, type KbDoc } from '@/api/resource'

const tab = ref<'tenant' | 'mine'>('tenant')
const loading = ref(false)
const tenantRows = ref<KbDoc[]>([])
const mineRows = ref<KbDoc[]>([])
const tenantForbidden = ref(false)

const rows = computed(() => (tab.value === 'tenant' ? tenantRows.value : mineRows.value))

function stateLabel(s: string): string {
  if (s === 'ok') return '已入库'
  if (s === 'failed') return '解析失败'
  return '解析中'
}
function stateTag(s: string): 'success' | 'danger' | 'warning' {
  if (s === 'ok') return 'success'
  if (s === 'failed') return 'danger'
  return 'warning'
}
function fmtSize(b?: number): string {
  if (!b) return '—'
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}
function fmtTime(t?: string): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

async function loadTenant() {
  tenantForbidden.value = false
  try {
    tenantRows.value = (await listKbDocs('tenant')) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      tenantForbidden.value = true
      tenantRows.value = []
    } else {
      ElMessage.error('资料列表加载失败，请确认后端已启动')
    }
  }
}

async function loadMine() {
  try {
    mineRows.value = (await listKbDocs()) || []
  } catch {
    mineRows.value = []
  }
}

async function reload() {
  loading.value = true
  try {
    await Promise.allSettled([loadTenant(), loadMine()])
  } finally {
    loading.value = false
  }
}

async function register() {
  try {
    const { value } = await ElMessageBox.prompt('登记后进入解析队列（M1 记录元信息，状态为「解析中」）', '登记知识文档', {
      confirmButtonText: '登记',
      cancelButtonText: '取消',
      inputPlaceholder: '如：2026年产业扶持政策汇编.pdf',
      inputValidator: (v: string) => !!v?.trim() || '资料名称不能为空'
    })
    const name = value.trim()
    await registerKbDoc(name)
    ElMessage.success(`已登记「${name}」`)
    await reload()
  } catch (e: unknown) {
    if (e === 'cancel' || (e as { message?: string })?.message === 'cancel') return
    ElMessage.error('登记失败：' + ((e as Error)?.message || '后端异常'))
  }
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.flex-tabs {
  flex: 1;
}

.flex-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.doc-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.doc-icon {
  font-size: 16px;
}
</style>
