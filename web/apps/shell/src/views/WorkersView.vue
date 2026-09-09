<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="数字员工"
      description="配置每日执行时刻与任务内容后，到点自动真实执行（调模型生成），执行记录留痕，并向租户全员推送弹窗提醒。停用后历史产出保留，可随时恢复。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>数字员工列表</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
            <el-button type="primary" size="small" @click="openDlg()">新增数字员工</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="名称" min-width="130">
          <template #default="{ row }">
            <span class="w-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" prop="description" min-width="150" show-overflow-tooltip />
        <el-table-column label="执行时刻" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.scheduleTime" type="warning" effect="plain" size="small">每日 {{ row.scheduleTime }}</el-tag>
            <span v-else class="muted">不定时</span>
          </template>
        </el-table-column>
        <el-table-column label="任务内容" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.taskPrompt || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <el-tag :type="row.enabled === 1 ? 'success' : 'info'" effect="plain" size="small">
              {{ row.enabled === 1 ? row.status || '运行中' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近产出" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.lastOutput || '尚未运行' }}</template>
        </el-table-column>
        <el-table-column label="启用" width="70">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled === 1"
              size="small"
              @change="() => toggle(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" :loading="runLoading === row.id" @click="runNow(row)">立即执行</el-button>
            <el-button text type="primary" size="small" @click="showRuns(row)">执行记录</el-button>
            <el-button text type="primary" size="small" @click="openDlg(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无数字员工，点击「新增数字员工」创建" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="form.id ? '编辑数字员工' : '新增数字员工'" width="520px">
      <el-form label-width="88px" size="small">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="如：政策快讯员" /></el-form-item>
        <el-form-item label="图标键"><el-input v-model="form.icon" placeholder="bot / bell / pen / megaphone" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="一句话说明这个数字员工做什么" /></el-form-item>
        <el-form-item label="运行计划"><el-input v-model="form.scheduleText" placeholder="如：每日 08:00 / 触发式（有申请即审）" /></el-form-item>
        <el-form-item label="执行时刻">
          <el-time-picker
            v-model="formTime"
            format="HH:mm"
            :seconds-disabled="true"
            placeholder="选择每日执行时刻（可选）"
            style="width: 100%"
          />
          <div class="hint">设置后每天到点自动执行一次任务内容；留空表示不定时</div>
        </el-form-item>
        <el-form-item label="任务内容">
          <el-input
            v-model="form.taskPrompt"
            type="textarea"
            :rows="3"
            placeholder="如：汇总今日办公平台待办与公告，生成一份不超过 200 字的晨间简报"
          />
          <div class="hint">到点后交给模型真实执行，产出会推送提醒给租户全员</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="runsDlg" :title="`执行记录 · ${runsWorker?.name || ''}`" size="46%">
      <el-timeline v-if="runs.length" style="padding-left: 4px">
        <el-timeline-item
          v-for="r in runs"
          :key="r.id"
          :type="r.status === 'SUCCESS' ? 'success' : 'danger'"
          :timestamp="fmtTime(r.startedAt) + ' · ' + (r.triggerType === 'MANUAL' ? '手动' : '定时') + ' · ' + r.durationMs + 'ms'"
        >
          <div class="run-title">
            <el-tag :type="r.status === 'SUCCESS' ? 'success' : 'danger'" effect="plain" size="small">
              {{ r.status === 'SUCCESS' ? '成功' : '失败' }}
            </el-tag>
            <span v-if="r.model" class="muted" style="margin-left: 6px">{{ r.model }}</span>
          </div>
          <div v-if="r.output" class="run-body">{{ r.output }}</div>
          <div v-else-if="r.errorMsg" class="run-body run-err">{{ r.errorMsg }}</div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无执行记录" :image-size="70" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminCreateWorker,
  adminDeleteWorker,
  adminListWorkerRuns,
  adminListWorkers,
  adminRunWorkerNow,
  adminToggleWorker,
  adminUpdateWorker,
  type AgentWorker,
  type WorkerRun
} from '@/api/resource'

const loading = ref(false)
const rows = ref<AgentWorker[]>([])
const dlg = ref(false)
const form = reactive<Partial<AgentWorker> & { id?: number }>({})
const formTime = ref<Date | null>(null)

const runsDlg = ref(false)
const runsWorker = ref<AgentWorker | null>(null)
const runs = ref<WorkerRun[]>([])
const runLoading = ref<number | null>(null)

/** HH:mm → Date（time-picker 需要 Date 值） */
const formTimeValue = computed<Date | null>({
  get: () => formTime.value,
  set: (v) => (formTime.value = v)
})
void formTimeValue

async function reload() {
  loading.value = true
  try {
    rows.value = (await adminListWorkers()) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('数字员工维护仅租户管理员可操作')
      rows.value = []
    } else {
      ElMessage.error('数字员工加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

function timeToDate(t?: string | null): Date | null {
  if (!t) return null
  const [h, m] = t.split(':').map((x) => parseInt(x, 10))
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  const d = new Date()
  d.setHours(h, m, 0, 0)
  return d
}

function openDlg(row?: AgentWorker) {
  Object.assign(form, {
    id: row?.id,
    name: row?.name || '',
    icon: row?.icon || 'bot',
    description: row?.description || '',
    status: row?.status || '运行中',
    scheduleText: row?.scheduleText || '',
    scheduleTime: row?.scheduleTime || null,
    taskPrompt: row?.taskPrompt || ''
  })
  formTime.value = timeToDate(row?.scheduleTime)
  dlg.value = true
}

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  const body: Partial<AgentWorker> = { ...form }
  if (formTime.value) {
    const p = (n: number) => String(n).padStart(2, '0')
    body.scheduleTime = `${p(formTime.value.getHours())}:${p(formTime.value.getMinutes())}`
  } else {
    body.scheduleTime = null
  }
  try {
    if (form.id) await adminUpdateWorker(form.id, body)
    else await adminCreateWorker(body)
    ElMessage.success('已保存')
    dlg.value = false
    await reload()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function toggle(row: AgentWorker) {
  try {
    await adminToggleWorker(row.id)
    ElMessage.success(row.enabled === 1 ? '已停用' : '已启用')
    await reload()
  } catch (e: unknown) {
    ElMessage.error('操作失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function runNow(row: AgentWorker) {
  runLoading.value = row.id
  try {
    const r = await adminRunWorkerNow(row.id)
    if (r.status === 'SUCCESS') {
      ElMessage.success('执行完成，已推送通知给租户全员')
    } else {
      ElMessage.error('执行失败：' + (r.errorMsg || '未知原因'))
    }
    await reload()
  } catch (e: unknown) {
    ElMessage.error('执行失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    runLoading.value = null
  }
}

async function showRuns(row: AgentWorker) {
  runsWorker.value = row
  runsDlg.value = true
  try {
    runs.value = (await adminListWorkerRuns(row.id, 30)) || []
  } catch (e: unknown) {
    ElMessage.error('执行记录加载失败：' + ((e as Error)?.message || '后端异常'))
    runs.value = []
  }
}

async function remove(row: AgentWorker) {
  try {
    await ElMessageBox.confirm(`确认删除数字员工「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await adminDeleteWorker(row.id)
  ElMessage.success('已删除')
  await reload()
}

function fmtTime(t?: string | null): string {
  return t ? String(t).replace('T', ' ').slice(0, 16) : ''
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.w-name {
  font-weight: 600;
}

.muted {
  color: var(--el-text-color-secondary);
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 2px;
}

.run-title {
  display: flex;
  align-items: center;
  margin-bottom: 4px;
}

.run-body {
  font-size: 13px;
  color: var(--el-text-color-primary);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 8px 10px;
}

.run-err {
  color: var(--el-color-danger);
}
</style>
