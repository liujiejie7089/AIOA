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
        <el-table-column label="详情" width="90">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">查看</el-button>
          </template>
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

    <el-dialog v-model="detailVisible" title="审批详情" width="520px">
      <template v-if="detailRow">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="单号">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ detailRow.bizType || '—' }}</el-descriptions-item>
          <el-descriptions-item label="标题">{{ detailRow.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="发起人">{{ detailRow.applicantName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detailRow.status)" effect="plain">{{ statusLabel(detailRow.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailRow.approver" label="审批人">{{ detailRow.approver }}</el-descriptions-item>
          <el-descriptions-item v-if="detailRow.decisionNote" label="审批意见">{{ detailRow.decisionNote }}</el-descriptions-item>
          <el-descriptions-item label="申请时间">{{ fmtTime(detailRow.createdAt) }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="formFields.length">
          <div class="dlg-subtitle">申请信息</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-for="f in formFields" :key="f.label" :label="f.label">{{ f.value || '—' }}</el-descriptions-item>
          </el-descriptions>
        </template>

        <div v-if="detailRow.content" class="dlg-content">{{ detailRow.content }}</div>

        <template v-if="attachments.length">
          <div class="dlg-subtitle">附件</div>
          <ul class="att-list">
            <li v-for="(a, i) in attachments" :key="i">
              <el-link type="primary" :href="a.url" target="_blank">{{ a.name }}</el-link>
            </li>
          </ul>
        </template>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detailRow && tab === 'todo' && detailRow.status === 'PENDING'"
          type="primary"
          @click="decide(detailRow, 'APPROVE')"
        >通过</el-button>
      </template>
    </el-dialog>
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

const detailVisible = ref(false)
const detailRow = ref<ApprovalOrder | null>(null)
const formFields = ref<{ label: string; value: string }[]>([])
const attachments = ref<{ name: string; url: string }[]>([])

const LEAVE_FIELDS: Record<string, string> = {
  leaveType: '请假类型',
  start: '开始日期',
  end: '结束日期',
  reason: '请假事由'
}

function openDetail(row: ApprovalOrder) {
  detailRow.value = row
  formFields.value = []
  attachments.value = []
  try {
    if (row.formData) {
      const data = JSON.parse(row.formData)
      const isLeave = /请假/.test(row.bizType || '') || Object.keys(LEAVE_FIELDS).some((k) => k in data)
      const map = isLeave ? LEAVE_FIELDS : null
      formFields.value = Object.keys(data).map((k) => ({
        label: (map && map[k]) || k,
        value: typeof data[k] === 'object' ? JSON.stringify(data[k]) : String(data[k])
      }))
    }
  } catch {
    /* 非法 JSON 忽略 */
  }
  try {
    if (row.attachment) {
      const arr = JSON.parse(row.attachment)
      if (Array.isArray(arr)) attachments.value = arr.map((x) => ({ name: x.name, url: x.url }))
    }
  } catch {
    /* 忽略 */
  }
  detailVisible.value = true
}

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

.dlg-subtitle {
  font-size: 13px;
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--aioa-text);
}

.dlg-content {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 10px 12px;
}

.att-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}

.expand-box {
  padding: 4px 16px 12px 48px;
}

.expand-label {
  font-size: 12px;
  color: var(--aioa-text-sub);
  margin-bottom: 6px;
}

.expand-content {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 10px 12px;
}
</style>
