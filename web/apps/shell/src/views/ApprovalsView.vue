<template>
  <div>
    <el-alert
      v-if="todoForbidden"
      type="info"
      :closable="false"
      show-icon
      title="当前账号不是审批人"
      description="多级审批的待办按「节点指派人」下发（部门负责人 / 企业管理员 / 租户管理员）。你可在下方「我发起的」跟踪自己申请的流转进度。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <el-tabs v-model="tab" class="flex-tabs" @tab-change="reload">
            <el-tab-pane :label="`待我审批${todoRows.length ? `（${todoRows.length}）` : ''}`" name="todo" />
            <el-tab-pane label="我发起的" name="mine" />
          </el-tabs>
          <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="单号" width="70" />
        <el-table-column prop="bizType" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ bizLabel(row.bizType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.title || row.bizType || '（无标题）' }}</span>
          </template>
        </el-table-column>
        <!-- #211：流转路径 —— 当前流转到哪一级、由谁审核 -->
        <el-table-column label="流转" min-width="190">
          <template #default="{ row }">
            <div v-if="row.status === 'PENDING' && currentNode(row)" class="flow-cur">
              <b>{{ currentNode(row)?.approverName || '—' }}</b>
              <span class="flow-sub">{{ approverTypeLabel(currentNode(row)?.approverType) }} · 第 {{ currentNode(row)?.seq }}/{{ row.totalNodes || row.timeline?.length || 1 }} 级</span>
            </div>
            <div v-else-if="(row.timeline || []).length" class="flow-cur done">
              <b>{{ (row.timeline || []).length }} 级流程</b>
              <span class="flow-sub">{{ statusLabel(row.status) }}</span>
            </div>
            <span v-else class="text-sub">单级审批</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="申请时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="详情" width="80">
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

    <el-dialog v-model="detailVisible" title="审批详情" width="640px">
      <template v-if="detailRow">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="单号">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ bizLabel(detailRow.bizType) }}</el-descriptions-item>
          <el-descriptions-item label="标题" :span="2">{{ detailRow.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="发起人">{{ detailRow.applicantName || detailRow.creatorName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detailRow.status)" effect="plain">{{ statusLabel(detailRow.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="申请时间" :span="2">{{ fmtTime(detailRow.createdAt) }}</el-descriptions-item>
        </el-descriptions>

        <!-- #211：完整流转路径 -->
        <template v-if="(detailRow.timeline || []).length">
          <div class="dlg-subtitle">
            流转路径（共 {{ (detailRow.timeline || []).length }} 级）
            <span v-if="currentNode(detailRow)" class="cur-hint">
              当前流转到 {{ currentNode(detailRow)?.approverName || '—' }}
            </span>
          </div>
          <el-timeline class="flow-timeline">
            <el-timeline-item
              v-for="n in detailRow.timeline"
              :key="n.taskId"
              :type="nodeType(n)"
              :hollow="n.status === 'SKIPPED'"
              :timestamp="nodeTime(n)"
            >
              <div class="node-head">
                <b>第 {{ n.seq }} 级 · {{ n.approverName || '—' }}</b>
                <span class="node-type">{{ approverTypeLabel(n.approverType) }}</span>
                <el-tag size="small" :type="statusTag(n.status)" effect="plain">{{ statusLabel(n.status) }}</el-tag>
                <el-tag v-if="currentNode(detailRow)?.taskId === n.taskId" size="small" effect="dark">当前节点</el-tag>
              </div>
              <div v-if="n.note" class="node-note">审批意见：{{ n.note }}</div>
              <div v-if="n.skipReason" class="node-note">跳过原因：{{ n.skipReason }}</div>
            </el-timeline-item>
          </el-timeline>
        </template>
        <el-alert
          v-else
          type="info"
          :closable="false"
          show-icon
          title="单级审批单据"
          description="该单据未配置多级审批流，由租户管理员直接处理。"
          style="margin: 12px 0"
        />

        <template v-if="formFields.length">
          <div class="dlg-subtitle">申请信息</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-for="f in formFields" :key="f.label" :label="f.label">{{ f.value || '—' }}</el-descriptions-item>
          </el-descriptions>
        </template>

        <template v-if="detailRow.content">
          <div class="dlg-content" :class="{ clamped: !contentExpanded }">{{ detailRow.content }}</div>
          <button v-if="isLongText(detailRow.content)" class="clamp-toggle" type="button" @click="contentExpanded = !contentExpanded">
            {{ contentExpanded ? '收起 ▲' : '展开全文 ▼' }}
          </button>
        </template>

        <template v-if="attachments.length">
          <div class="dlg-subtitle">附件</div>
          <ul class="att-list">
            <li v-for="(a, i) in attachments" :key="i">
              <el-link type="primary" :href="a.url" target="_blank">{{ a.name }}</el-link>
            </li>
          </ul>
        </template>

        <template v-if="detailRow.approver || detailRow.decisionNote">
          <div class="dlg-subtitle">处理结果</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-if="detailRow.approver" label="审批人">{{ detailRow.approver }}</el-descriptions-item>
            <el-descriptions-item v-if="detailRow.decisionNote" label="审批意见">{{ detailRow.decisionNote }}</el-descriptions-item>
            <el-descriptions-item v-if="detailRow.decidedAt" label="处理时间">{{ fmtTime(detailRow.decidedAt) }}</el-descriptions-item>
          </el-descriptions>
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
import {
  decideApproval,
  decideWorkflowTask,
  listApprovals,
  listMyApplications,
  listWorkflowTodo,
  type ApprovalTaskNode,
  type WorkflowTask
} from '@/api/resource'

/** 统一行模型：多级引擎与历史单级审批在同一个表格里呈现，用 source 区分决策入口。 */
/**
 * 列表行 = 多级审批引擎任务 ∪ 单级审批池单据。
 * 两级来源字段并不完全一致：单级池（legacy，承载成果/公文）没有 taskId，
 * 故此处把它降为可选，决策时按 source 分流（见 decide()）。
 */
interface Row extends Omit<WorkflowTask, 'taskId'> {
  source: 'workflow' | 'legacy'
  taskId?: number
}

const tab = ref<'todo' | 'mine'>('todo')
const loading = ref(false)
const todoRows = ref<Row[]>([])
const mineRows = ref<Row[]>([])
const todoForbidden = ref(false)

const detailVisible = ref(false)
const detailRow = ref<Row | null>(null)

/**
 * 正文折叠：公文/成果类审批的正文可能很长，全铺开会把「审批意见」「通过/驳回」顶出可视区。
 * 超过阈值高度时默认收起；每次打开详情重置为收起态。
 */
const contentExpanded = ref(false)
function isLongText(t?: string | null) {
  return (t || '').trim().length > 260
}
const formFields = ref<{ label: string; value: string }[]>([])
const attachments = ref<{ name: string; url: string }[]>([])

/** formData 的中文标签（多级请假单与历史单字段名不同，两者都要认）。 */
const FIELD_LABELS: Record<string, string> = {
  leaveType: '请假类型',
  leaveTypeName: '请假类型',
  leaveTypeCode: '假种编码',
  start: '开始日期',
  end: '结束日期',
  startDate: '开始日期',
  endDate: '结束日期',
  days: '请假天数',
  reason: '请假事由'
}

const APPROVER_TYPE_LABEL: Record<string, string> = {
  DEPT_LEADER: '部门负责人',
  ORG_ADMIN: '企业管理员',
  TENANT_ADMIN: '租户管理员',
  SPECIFIC: '指定审批人'
}

function approverTypeLabel(t?: string): string {
  return (t && APPROVER_TYPE_LABEL[t]) || t || '审批人'
}

function bizLabel(t?: string): string {
  if (!t) return '—'
  if (/RESULT/i.test(t)) return '成果审批'
  if (/DOC/i.test(t)) return '文稿审批'
  if (/LEAVE|请假|假勤/.test(t)) return '请假'
  if (/QUOTA/i.test(t)) return '额度扩容'
  if (/RESOURCE/i.test(t)) return '资源开通'
  return t
}

function currentNode(row: Row | null): ApprovalTaskNode | null {
  const tl = row?.timeline || []
  return tl.find((n) => n.status === 'PENDING') || null
}

function nodeType(n: ApprovalTaskNode): 'success' | 'danger' | 'primary' | 'info' {
  if (n.status === 'APPROVED') return 'success'
  if (n.status === 'REJECTED') return 'danger'
  if (n.status === 'PENDING') return 'primary'
  return 'info'
}

function nodeTime(n: ApprovalTaskNode): string {
  return n.decidedAt ? fmtTime(n.decidedAt) : n.status === 'PENDING' ? '待处理' : '—'
}

function openDetail(row: Row) {
  detailRow.value = row
  contentExpanded.value = false   // 换单据时正文回到收起态，避免沿用上一单的展开
  formFields.value = []
  attachments.value = []
  try {
    if (row.formData) {
      const data = JSON.parse(row.formData)
      formFields.value = Object.keys(data).map((k) => ({
        label: FIELD_LABELS[k] || k,
        value: typeof data[k] === 'object' ? JSON.stringify(data[k]) : String(data[k])
      }))
    }
  } catch {
    /* 非法 JSON 忽略 */
  }
  try {
    if (row.attachment) {
      const arr = typeof row.attachment === 'string' ? JSON.parse(row.attachment) : row.attachment
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
  if (s === 'SKIPPED') return '已跳过'
  if (s === 'CANCELED') return '已撤销'
  return '待审批'
}
function statusTag(s: string): 'success' | 'danger' | 'warning' | 'info' {
  if (s === 'APPROVED') return 'success'
  if (s === 'REJECTED') return 'danger'
  if (s === 'SKIPPED' || s === 'CANCELED') return 'info'
  return 'warning'
}
function fmtTime(t?: string | null): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

/**
 * 待我审批 = 多级审批引擎（按节点指派人，机构管理员在此）∪ 单级待办池（租户管理员）。
 * 后者对机构管理员会 403 —— 属预期，静默跳过并提示其身份。
 */
async function loadTodo() {
  todoForbidden.value = false
  const merged: Row[] = []
  let workflowOk = false
  try {
    const tasks = (await listWorkflowTodo()) || []
    workflowOk = true
    merged.push(...tasks.map((t) => ({ ...t, source: 'workflow' as const })))
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status !== 403) ElMessage.error('待办加载失败，请确认后端已启动')
  }
  try {
    const legacy = (await listApprovals('todo')) || []
    merged.push(...legacy.map((o) => ({ ...o, source: 'legacy' as const })))
  } catch {
    // 403：当前账号不是租户级管理员，属预期
  }
  todoRows.value = merged
  todoForbidden.value = !workflowOk && !merged.length
}

async function loadMine() {
  try {
    const list = (await listMyApplications()) || []
    mineRows.value = list.map((t) => ({ ...t, source: 'workflow' as const }))
  } catch {
    try {
      const legacy = (await listApprovals('mine')) || []
      mineRows.value = legacy.map((o) => ({ ...o, source: 'legacy' as const }))
    } catch {
      mineRows.value = []
    }
  }
}

async function reload() {
  loading.value = true
  try {
    await Promise.allSettled([loadTodo(), loadMine()])
  } finally {
    loading.value = false
  }
}

async function decide(row: Row, decision: 'APPROVE' | 'REJECT') {
  const node = currentNode(row)
  const tail = row.source === 'workflow' && node
    ? `\n当前节点：第 ${node.seq}/${row.totalNodes || row.timeline?.length || 1} 级 · ${node.approverName || '—'}`
    : ''
  try {
    const { value } = await ElMessageBox.prompt(
      `单号 ${row.id} · ${row.title || row.bizType}${tail}`,
      decision === 'APPROVE' ? '通过审批 — 填写审批意见' : '驳回审批 — 填写驳回原因',
      {
        confirmButtonText: decision === 'APPROVE' ? '确认通过' : '确认驳回',
        cancelButtonText: '取消',
        inputPlaceholder: decision === 'APPROVE' ? '如：同意，按制度执行' : '如：材料不齐，请补充证明材料',
        inputValue: decision === 'APPROVE' ? '同意' : '',
        inputValidator: (v: string) => (decision === 'APPROVE' ? true : !!v?.trim() || '驳回必须填写原因'),
        customStyle: { whiteSpace: 'pre-line' }
      }
    )
    if (row.source === 'workflow' && row.taskId) {
      const res = await decideWorkflowTask(row.taskId, decision, value?.trim())
      ElMessage.success(
        decision === 'REJECT'
          ? '已驳回，已通知发起人'
          : res.finalDone
            ? '终审通过，流程已完成并通知发起人'
            : '本节点已通过，已流转到下一审批人'
      )
    } else {
      await decideApproval(row.id, decision, value?.trim())
      ElMessage.success(decision === 'APPROVE' ? '已通过，已通知发起人' : '已驳回，已通知发起人')
    }
    detailVisible.value = false
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

.flow-cur {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}
.flow-cur b {
  font-size: 13px;
}
.flow-cur.done b {
  font-weight: 500;
  color: var(--aioa-text-sub);
}
.flow-sub {
  font-size: 11px;
  color: var(--aioa-text-sub);
}

.dlg-subtitle {
  font-size: 13px;
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--aioa-text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.cur-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-color-primary);
}

.flow-timeline {
  padding-left: 2px;
}
.node-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}
.node-type {
  font-size: 12px;
  color: var(--aioa-text-sub);
}
.node-note {
  font-size: 12px;
  color: var(--aioa-text-sub);
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-word;
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

/* 正文折叠：收起时裁到 ~9 行，底部渐隐，避免把审批按钮顶出可视区 */
.dlg-content.clamped {
  position: relative;
  max-height: 178px;
  overflow: hidden;
}
.dlg-content.clamped::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 36px;
  background: linear-gradient(rgba(255, 255, 255, 0), var(--el-fill-color-light));
  pointer-events: none;
}
.clamp-toggle {
  display: block;
  width: 100%;
  background: none;
  border: none;
  color: var(--el-color-primary);
  font-size: 12px;
  font-family: inherit;
  padding: 6px 0 0;
  cursor: pointer;
  text-align: center;
}
.clamp-toggle:hover {
  color: var(--el-color-primary-dark-2);
}

.att-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}
</style>
