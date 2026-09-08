<template>
  <div>
    <el-alert
      v-if="todoForbidden"
      type="info"
      :closable="false"
      show-icon
      title="「待我审批」仅租户管理员可见"
      description="普通用户提交的审批由租户管理员处理，可在下方「我发起的」跟踪自己申请的进度。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <el-tabs v-model="tab" class="flex-tabs" @tab-change="reload">
            <el-tab-pane label="待我审批" name="todo" />
            <el-tab-pane label="我发起的" name="mine" />
          </el-tabs>
          <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="单号" width="70" />
        <el-table-column prop="bizType" label="类型" width="110" />
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.title || row.bizType || '（无标题）' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="approver" label="审批人" width="110">
          <template #default="{ row }">{{ row.approver || '—' }}</template>
        </el-table-column>
        <el-table-column prop="decisionNote" label="审批意见" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.decisionNote || '—' }}</template>
        </el-table-column>
        <el-table-column label="申请时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column v-if="tab === 'todo'" label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'PENDING'">
              <el-button size="small" type="primary" @click="decide(row, 'APPROVE')">通过</el-button>
              <el-button size="small" type="danger" plain @click="decide(row, 'REJECT')">驳回</el-button>
            </template>
            <span v-else class="text-sub">已处理</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="tab === 'todo' ? '暂无待你处理的审批单' : '你还没有发起过审批'" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { decideApproval, listApprovals, type ApprovalOrder } from '@/api/resource'

const tab = ref<'todo' | 'mine'>('todo')
const loading = ref(false)
const todoRows = ref<ApprovalOrder[]>([])
const mineRows = ref<ApprovalOrder[]>([])
const todoForbidden = ref(false)

const rows = computed(() => (tab.value === 'todo' ? todoRows.value : mineRows.value))

function statusLabel(s: string): string {
  if (s === 'APPROVED') return '已通过'
  if (s === 'REJECTED') return '已驳回'
  return '待审批'
}
function statusTag(s: string): 'success' | 'danger' | 'warning' {
  if (s === 'APPROVED') return 'success'
  if (s === 'REJECTED') return 'danger'
  return 'warning'
}
function fmtTime(t?: string): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

async function loadTodo() {
  todoForbidden.value = false
  try {
    todoRows.value = (await listApprovals('todo')) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      todoForbidden.value = true
      todoRows.value = []
    } else {
      ElMessage.error('审批列表加载失败，请确认后端已启动')
    }
  }
}

async function loadMine() {
  try {
    mineRows.value = (await listApprovals('mine')) || []
  } catch {
    mineRows.value = []
  }
}

async function reload() {
  loading.value = true
  try {
    // 两个列表并行加载：普通用户对 todo 的 403 已被捕获为提示，不影响「我发起的」
    await Promise.allSettled([loadTodo(), loadMine()])
  } finally {
    loading.value = false
  }
}

async function decide(row: ApprovalOrder, decision: 'APPROVE' | 'REJECT') {
  try {
    const { value } = await ElMessageBox.prompt(
      `单号 ${row.id} · ${row.title || row.bizType}`,
      decision === 'APPROVE' ? '通过审批 — 填写审批意见' : '驳回审批 — 填写驳回原因',
      {
        confirmButtonText: decision === 'APPROVE' ? '确认通过' : '确认驳回',
        cancelButtonText: '取消',
        inputPlaceholder: decision === 'APPROVE' ? '如：内容合规，准予发布' : '如：不符合发布规范',
        inputValue: decision === 'APPROVE' ? '内容合规，准予发布' : '不符合发布规范',
        inputValidator: (v: string) => !!v?.trim() || '请填写意见（将随通知发送给发起人）'
      }
    )
    await decideApproval(row.id, decision, value.trim())
    ElMessage.success(decision === 'APPROVE' ? '已通过，已通知发起人' : '已驳回，已通知发起人')
    await reload()
  } catch (e: unknown) {
    if (e === 'cancel' || (e as { message?: string })?.message === 'cancel') return
    ElMessage.error('操作失败：' + ((e as Error)?.message || '后端异常'))
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

.text-sub {
  font-size: 12px;
  color: var(--aioa-text-sub);
}
</style>
