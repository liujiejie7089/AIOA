<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="租户级默认审批流"
      description="机构未单独配置时，新提交的单据按这里的默认流流转。每个节点可选「知会对象（无需审批，仅知悉）」——保存后对**新提交**的单据生效。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>审批流配置（共 {{ defs.length }} 条）</span>
          <el-button text type="primary" size="small" :loading="loading" @click="loadDefs">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="defs" stripe>
        <el-table-column prop="bizType" label="业务类型" width="160" />
        <el-table-column prop="name" label="流程名称" min-width="240" show-overflow-tooltip />
        <el-table-column label="节点数" width="90">
          <template #default="{ row }">{{ parseSteps(row.stepsJson).length }}</template>
        </el-table-column>
        <el-table-column label="知会配置" min-width="220">
          <template #default="{ row }">
            <span v-if="ccSummary(row)" class="text-sub">{{ ccSummary(row) }}</span>
            <span v-else class="text-sub">未配置知会</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="editSteps(row)">编辑</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="本租户暂无审批流定义" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <el-dialog v-model="dlgVisible" title="编辑审批流" width="720px">
      <template v-if="current">
        <el-descriptions :column="2" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="业务类型">{{ current.bizType }}</el-descriptions-item>
          <el-descriptions-item label="流程名称">{{ current.name }}</el-descriptions-item>
        </el-descriptions>

        <div v-for="(s, i) in steps" :key="i" class="step-row">
          <div class="step-head">
            <b>第 {{ i + 1 }} 级</b>
            <el-select v-model="s.approver_type" size="small" style="width: 180px" placeholder="审批人类型">
              <el-option
                v-for="opt in APPROVER_TYPE_OPTIONS"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <span v-if="s.approver_type === 'APPLICANT_SUPERIOR'" class="text-sub">
              向上级数（0 / 留空 = 整链）
            </span>
            <el-input-number
              v-if="s.approver_type === 'APPLICANT_SUPERIOR'"
              v-model="s.levels"
              :min="0"
              size="small"
              controls-position="right"
              style="width: 130px"
            />
            <span class="text-sub">跳级阈值（天，可空）</span>
            <el-input-number
              v-model="s.threshold_days"
              :min="0"
              size="small"
              controls-position="right"
              style="width: 130px"
            />
          </div>
          <div class="step-body">
            <span class="text-sub">知会对象（无需审批，仅知悉）</span>
            <el-select
              v-model="s.cc"
              multiple
              size="small"
              style="width: 100%"
              placeholder="选择知会对象（可多选，可留空 = 不生成知会）"
            >
              <el-option
                v-for="opt in CC_TARGET_TYPES"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="dlgVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDef">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listApprovalFlowDefs, saveApprovalFlowDef, type ApprovalFlowDef } from '@/api/org'
import { CC_TARGET_TYPES, CC_TARGET_VALUES } from '@/constants/permissions'

/** 可编辑的节点模型（与 steps_json 中每个 step 一一对应）。 */
interface StepModel {
  seq: number
  approver_type: string
  /** 仅 APPLICANT_SUPERIOR 有意义：向上几级；undefined / 0 = 整链 */
  levels?: number
  /** 阈值跳级：天数 ≤ 阈值时该节点 SKIPPED */
  threshold_days?: number
  /** 知会对象类型清单（可空） */
  cc: string[]
}

/** 与后端 ApprovalTask.TYPE_* 对齐的审批人类型选项。 */
const APPROVER_TYPE_OPTIONS = [
  { value: 'APPLICANT_SUPERIOR', label: '申请人的上级' },
  { value: 'DEPT_LEADER', label: '部门负责人' },
  { value: 'ORG_ADMIN', label: '企业管理员' },
  { value: 'TENANT_ADMIN', label: '租户管理员' },
  { value: 'PLATFORM_ADMIN', label: '平台管理员' },
  { value: 'SPECIFIC', label: '指定审批人' }
] as const

const defs = ref<ApprovalFlowDef[]>([])
const loading = ref(false)
const saving = ref(false)
const dlgVisible = ref(false)
const current = ref<ApprovalFlowDef | null>(null)
const steps = ref<StepModel[]>([])

/** 解析 stepsJson（非法 / 非数组 → 空，绝不抛错阻断渲染）。 */
function parseSteps(json?: string): StepModel[] {
  if (!json) return []
  try {
    const arr = JSON.parse(json)
    if (!Array.isArray(arr)) return []
    return arr.map((s: Record<string, unknown>, i: number) => ({
      seq: typeof s.seq === 'number' ? s.seq : i + 1,
      approver_type: String(s.approver_type || 'ORG_ADMIN'),
      levels: s.levels == null ? undefined : Number(s.levels),
      threshold_days: s.threshold_days == null ? undefined : Number(s.threshold_days),
      cc: Array.isArray(s.cc) ? (s.cc as unknown[]).map((x) => String(x)) : []
    }))
  } catch {
    return []
  }
}

/** 列表「知会配置」列摘要（只读回显已配 cc）。 */
function ccSummary(row: ApprovalFlowDef): string {
  const parts: string[] = []
  parseSteps(row.stepsJson).forEach((s, i) => {
    if (s.cc.length) {
      const labels = s.cc.map((v) => CC_TARGET_TYPES.find((t) => t.value === v)?.label || v)
      parts.push(`第 ${i + 1} 级：${labels.join('、')}`)
    }
  })
  return parts.join('；')
}

async function loadDefs() {
  loading.value = true
  try {
    // institutionId=0 → 只看租户级默认流（机构级由机构管理单独维护）
    defs.value = (await listApprovalFlowDefs(0)) || []
  } catch (e: unknown) {
    ElMessage.error('审批流加载失败：' + ((e as Error)?.message || '后端异常'))
    defs.value = []
  } finally {
    loading.value = false
  }
}

function editSteps(row: ApprovalFlowDef) {
  current.value = row
  const parsed = parseSteps(row.stepsJson)
  steps.value = parsed.length
    ? parsed
    : [{ seq: 1, approver_type: 'ORG_ADMIN', levels: undefined, threshold_days: undefined, cc: [] }]
  dlgVisible.value = true
}

async function saveDef() {
  if (!current.value || !steps.value.length) {
    ElMessage.warning('至少需要一个审批节点')
    return
  }
  // 非法知会类型：**给提示、不静默丢弃**（A3-9）
  const bad: string[] = []
  steps.value.forEach((s) => s.cc.forEach((v) => { if (!CC_TARGET_VALUES.includes(v)) bad.push(v) }))
  if (bad.length) {
    ElMessage.warning(`存在不支持的知会类型：${Array.from(new Set(bad)).join('、')}；请从下拉列表中选择`)
    return
  }
  const payloadSteps = steps.value.map((s, i) => {
    const o: Record<string, unknown> = { seq: i + 1, approver_type: s.approver_type }
    if (s.levels != null && s.levels > 0) o.levels = s.levels
    if (s.threshold_days != null && s.threshold_days > 0) o.threshold_days = s.threshold_days
    if (s.cc.length) o.cc = s.cc
    return o
  })
  saving.value = true
  try {
    await saveApprovalFlowDef({
      id: current.value.id,
      bizType: current.value.bizType,
      institutionId: current.value.institutionId ?? 0,
      name: current.value.name,
      steps: payloadSteps
    })
    ElMessage.success('已保存，对新提交的单据生效')
    dlgVisible.value = false
    await loadDefs()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    saving.value = false
  }
}

onMounted(loadDefs)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.text-sub {
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.step-row {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
