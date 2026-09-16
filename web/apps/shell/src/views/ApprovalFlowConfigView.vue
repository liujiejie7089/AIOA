<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="租户级默认审批流"
      description="机构未单独配置时，新提交的单据按这里的默认流流转。节点支持：按职务动态取人（人员变动不改流程）、单人 / 会签 / 抢占三种处理模式、按条件路由（如按天数分流）、知会对象（无需审批，仅知悉）。保存后对**新提交**的单据生效。"
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
        <el-table-column prop="name" label="流程名称" min-width="220" show-overflow-tooltip />
        <el-table-column label="节点数" width="80">
          <template #default="{ row }">{{ parseSteps(row.stepsJson).length }}</template>
        </el-table-column>
        <el-table-column label="节点配置" min-width="280">
          <template #default="{ row }">
            <span class="text-sub">{{ stepSummary(row) || '默认（单级审批人）' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="知会配置" min-width="200">
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

    <el-dialog v-model="dlgVisible" title="编辑审批流" width="820px">
      <template v-if="current">
        <el-descriptions :column="2" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="业务类型">{{ current.bizType }}</el-descriptions-item>
          <el-descriptions-item label="流程名称">{{ current.name }}</el-descriptions-item>
        </el-descriptions>

        <div v-for="(s, i) in steps" :key="i" class="step-row">
          <div class="step-head">
            <b>第 {{ i + 1 }} 级</b>
            <el-select v-model="s.approver_type" size="small" style="width: 230px" placeholder="审批人类型"
                       @change="onTypeChange(s)">
              <el-option v-for="opt in APPROVER_TYPES" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>

            <template v-if="s.approver_type === 'APPLICANT_SUPERIOR'">
              <span class="text-sub">向上级数（0 / 留空 = 整链）</span>
              <el-input-number v-model="s.levels" :min="0" size="small" controls-position="right" style="width: 120px" />
            </template>

            <template v-if="isDutyTyped(s.approver_type)">
              <span class="text-sub">职务</span>
              <el-select v-model="s.duty_code" size="small" style="width: 190px" placeholder="选择职务">
                <el-option v-for="d in dutiesForApproverType(s.approver_type)" :key="d.value"
                           :label="d.label" :value="d.value" />
              </el-select>
            </template>

            <template v-if="s.approver_type === 'UNIT_DUTY'">
              <span class="text-sub">机构 ID（可空 = 申请人所属机构）</span>
              <el-input-number v-model="s.institution_id" :min="0" size="small" controls-position="right"
                               style="width: 130px" />
            </template>

            <template v-if="s.approver_type === 'SPECIFIC'">
              <span class="text-sub">指定审批人</span>
              <el-select v-model="s.approver_id" size="small" filterable style="width: 190px" placeholder="选择人员">
                <el-option v-for="m in members" :key="m.userId" :label="memberLabel(m)" :value="m.userId as number" />
              </el-select>
            </template>

            <span class="text-sub">跳级阈值（天，可空）</span>
            <el-input-number v-model="s.threshold_days" :min="0" size="small" controls-position="right"
                             style="width: 120px" />
          </div>

          <div class="step-body">
            <div class="row-inline">
              <span class="text-sub">处理模式</span>
              <el-select v-model="s.mode" size="small" style="width: 220px">
                <el-option v-for="m in NODE_MODES" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <span class="text-sub hint">
                职务型节点可能命中多人：单人取首个、会签需全部通过、抢占任一人处理即完成
              </span>
            </div>

            <div class="row-inline">
              <el-switch v-model="s.whenEnabled" size="small" />
              <span class="text-sub">条件路由（不满足则本节点不参与本次审批）</span>
              <template v-if="s.whenEnabled">
                <el-select v-model="s.when_field" size="small" filterable allow-create style="width: 200px"
                           placeholder="字段">
                  <el-option v-for="f in CONDITION_FIELDS" :key="f.value" :label="f.label" :value="f.value" />
                </el-select>
                <el-select v-model="s.when_op" size="small" style="width: 80px">
                  <el-option v-for="o in CONDITION_OPS" :key="o.value" :label="o.label" :value="o.value" />
                </el-select>
                <el-input v-model="s.when_value" size="small" style="width: 150px" placeholder="比较值" />
              </template>
            </div>
            <div v-if="s.whenEnabled" class="text-sub hint">
              提示：若**所有**带条件的节点都不满足，引擎会回落到第一个无条件节点（无则末级节点），并在单据上写明回落原因。
            </div>

            <div class="row-inline">
              <span class="text-sub">知会对象（无需审批，仅知悉）</span>
              <el-select v-model="s.cc" multiple size="small" style="flex: 1; min-width: 240px"
                         placeholder="按角色知会（可多选，可留空）">
                <el-option v-for="opt in CC_TARGET_TYPES" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </div>
            <div class="row-inline">
              <span class="text-sub">指定知会人</span>
              <el-select v-model="s.cc_users" multiple filterable size="small" style="flex: 1; min-width: 240px"
                         placeholder="按人知会（可多选，可留空）">
                <el-option v-for="m in members" :key="m.userId" :label="memberLabel(m)" :value="m.userId as number" />
              </el-select>
            </div>
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
import {
  listApprovalFlowDefs,
  saveApprovalFlowDef,
  listMembers,
  type ApprovalFlowDef,
  type OrgMember
} from '@/api/org'
import {
  CC_TARGET_TYPES,
  CC_TARGET_VALUES,
  APPROVER_TYPES,
  APPROVER_TYPE_LABEL,
  NODE_MODES,
  CONDITION_FIELDS,
  CONDITION_OPS,
  dutiesForApproverType
} from '@/constants/permissions'

/** 一个节点内未建模的额外键（原样保留，避免「打开-保存」丢配置）。 */
type ExtraKeys = Record<string, unknown>

/** 可编辑的节点模型（与 steps_json 中每个 step 一一对应）。 */
interface StepModel {
  seq: number
  approver_type: string
  /** 仅 APPLICANT_SUPERIOR 有意义：向上几级；undefined / 0 = 整链 */
  levels?: number
  /** 仅职务型（DEPT_DUTY / UNIT_DUTY）有意义 */
  duty_code?: string
  /** 仅 UNIT_DUTY 有意义：目标机构；undefined / 0 = 申请人所属机构 */
  institution_id?: number
  /** 仅 SPECIFIC 有意义：指定审批人 user_id */
  approver_id?: number
  /** 阈值跳级：天数 ≤ 阈值时该节点 SKIPPED */
  threshold_days?: number
  /** single / parallel / grab */
  mode: string
  /** 条件路由（whenEnabled 为 false 时不落库） */
  whenEnabled: boolean
  when_field?: string
  when_op?: string
  when_value?: string
  /** 按角色知会 */
  cc: string[]
  /** 按人知会（落库为 {"type":"SPECIFIC","user_id":N}） */
  cc_users: number[]
  /** 本 UI 未建模的键，保存时原样带回 */
  _extra: ExtraKeys
}

const MODELED_KEYS = new Set([
  'seq', 'approver_type', 'levels', 'duty_code', 'institution_id',
  'approver_id', 'threshold_days', 'mode', 'when', 'cc'
])

const defs = ref<ApprovalFlowDef[]>([])
const members = ref<OrgMember[]>([])
const loading = ref(false)
const saving = ref(false)
const dlgVisible = ref(false)
const current = ref<ApprovalFlowDef | null>(null)
const steps = ref<StepModel[]>([])

function isDutyTyped(type: string): boolean {
  return type === 'DEPT_DUTY' || type === 'UNIT_DUTY'
}

/** 解析 stepsJson（非法 / 非数组 → 空，绝不抛错阻断渲染）。 */
function parseSteps(json?: string): StepModel[] {
  if (!json) return []
  try {
    const arr = JSON.parse(json)
    if (!Array.isArray(arr)) return []
    return arr.map((raw: Record<string, unknown>, i: number) => {
      const s = raw || {}
      const type = String(s.approver_type || 'ORG_ADMIN')
      const ccRaw = Array.isArray(s.cc) ? (s.cc as unknown[]) : []
      // cc 两种形态：字符串 = 角色；对象 = 指定人（C-11）
      const ccRoles: string[] = []
      const ccUsers: number[] = []
      ccRaw.forEach((x) => {
        if (x && typeof x === 'object') {
          const o = x as Record<string, unknown>
          const uid = Number(o.user_id)
          if (o.type === 'SPECIFIC' && Number.isFinite(uid) && uid > 0) ccUsers.push(uid)
          else if (o.type) ccRoles.push(String(o.type))
        } else if (x != null && String(x).trim()) {
          ccRoles.push(String(x))
        }
      })
      const w = (s.when && typeof s.when === 'object') ? (s.when as Record<string, unknown>) : null
      const extra: ExtraKeys = {}
      Object.keys(s).forEach((k) => { if (!MODELED_KEYS.has(k)) extra[k] = s[k] })
      return {
        seq: typeof s.seq === 'number' ? s.seq : i + 1,
        approver_type: type,
        levels: s.levels == null ? undefined : Number(s.levels),
        duty_code: s.duty_code == null ? undefined : String(s.duty_code),
        institution_id: s.institution_id == null ? undefined : Number(s.institution_id),
        approver_id: s.approver_id == null ? undefined : Number(s.approver_id),
        threshold_days: s.threshold_days == null ? undefined : Number(s.threshold_days),
        mode: s.mode == null ? 'single' : String(s.mode),
        whenEnabled: !!w,
        when_field: w && w.field != null ? String(w.field) : undefined,
        when_op: w && w.op != null ? String(w.op) : '==',
        when_value: w && w.value != null ? String(w.value) : undefined,
        cc: ccRoles,
        cc_users: ccUsers,
        _extra: extra
      }
    })
  } catch {
    return []
  }
}

function emptyStep(): StepModel {
  return {
    seq: 1, approver_type: 'ORG_ADMIN', mode: 'single',
    whenEnabled: false, when_op: '==', cc: [], cc_users: [], _extra: {}
  }
}

/** 切换审批人类型时给出合理默认值，避免存下「类型有了、参数空着」的半成品。 */
function onTypeChange(s: StepModel) {
  if (s.approver_type === 'DEPT_DUTY' && !s.duty_code) s.duty_code = 'DEPT_PRINCIPAL'
  if (s.approver_type === 'UNIT_DUTY' && !s.duty_code) s.duty_code = 'ORG_LEADER'
  if (!isDutyTyped(s.approver_type)) s.duty_code = undefined
  if (s.approver_type !== 'UNIT_DUTY') s.institution_id = undefined
  if (s.approver_type !== 'SPECIFIC') s.approver_id = undefined
}

function memberLabel(m: OrgMember): string {
  const dept = m.departmentName ? ` / ${m.departmentName}` : ''
  return `${m.name || m.username || ('#' + m.userId)}${dept}`
}

function userIdOf(uid?: number): string {
  const m = members.value.find((x) => x.userId === uid)
  return m ? (m.name || m.username || ('#' + uid)) : ('#' + uid)
}

/** 列表「节点配置」列摘要：让管理员不打开弹窗也能看出流程的形态。 */
function stepSummary(row: ApprovalFlowDef): string {
  const arr = parseSteps(row.stepsJson)
  if (!arr.length) return ''
  return arr.map((s, i) => {
    const parts: string[] = [APPROVER_TYPE_LABEL[s.approver_type] || s.approver_type]
    if (s.duty_code) parts.push(s.duty_code)
    if (s.approver_type === 'SPECIFIC' && s.approver_id) parts.push(userIdOf(s.approver_id))
    if (s.mode && s.mode !== 'single') parts.push(s.mode)
    if (s.whenEnabled && s.when_field) parts.push(`when ${s.when_field}${s.when_op}${s.when_value ?? ''}`)
    if (s.threshold_days != null && s.threshold_days > 0) parts.push(`≤${s.threshold_days}天跳级`)
    return `第${i + 1}级：${parts.join('·')}`
  }).join('；')
}

/** 列表「知会配置」列摘要（只读回显已配 cc）。 */
function ccSummary(row: ApprovalFlowDef): string {
  const parts: string[] = []
  parseSteps(row.stepsJson).forEach((s, i) => {
    const labels: string[] = s.cc.map((v) => CC_TARGET_TYPES.find((t) => t.value === v)?.label || v)
    s.cc_users.forEach((u) => labels.push(userIdOf(u)))
    if (labels.length) parts.push(`第 ${i + 1} 级：${labels.join('、')}`)
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

/** 人员名单按需加载一次（用于「指定审批人 / 指定知会人」选择器）。 */
async function ensureMembers() {
  if (members.value.length) return
  try {
    const r = await listMembers({ page: 1, size: 300 })
    members.value = (r?.items || []).filter((m) => m.userId)
  } catch {
    // 名单拉不到不阻断配置：仍可配角色型节点，只是选不了具体人。
    members.value = []
  }
}

async function editSteps(row: ApprovalFlowDef) {
  current.value = row
  const parsed = parseSteps(row.stepsJson)
  steps.value = parsed.length ? parsed : [emptyStep()]
  dlgVisible.value = true
  await ensureMembers()
}

/** 比较值按数字回写（`days <= 3` 这类条件必须是数字，字符串比较会得到错误结果）。 */
function coerceValue(v?: string): unknown {
  if (v == null || v === '') return undefined
  const t = v.trim()
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : t
}

async function saveDef() {
  if (!current.value || !steps.value.length) {
    ElMessage.warning('至少需要一个审批节点')
    return
  }
  // 前置校验：把后端会拒绝的形态在本地就说清楚（配置页是唯一能告诉管理员「你写错了」的地方）
  const modeValues = NODE_MODES.map((m) => m.value) as readonly string[]
  const bad: string[] = []
  for (let i = 0; i < steps.value.length; i++) {
    const s = steps.value[i]
    if (!modeValues.includes(s.mode)) bad.push(`第 ${i + 1} 级：处理模式不支持`)
    if (isDutyTyped(s.approver_type) && !s.duty_code) bad.push(`第 ${i + 1} 级：请选择职务`)
    if (s.approver_type === 'SPECIFIC' && !s.approver_id) bad.push(`第 ${i + 1} 级：请选择指定审批人`)
    if (s.whenEnabled && !s.when_field) bad.push(`第 ${i + 1} 级：条件路由缺「字段」`)
    s.cc.forEach((v) => { if (!CC_TARGET_VALUES.includes(v)) bad.push(`第 ${i + 1} 级：不支持的知会类型 ${v}`) })
  }
  if (bad.length) {
    ElMessage.warning(bad.join('；'))
    return
  }

  const payloadSteps = steps.value.map((s, i) => {
    // _extra 先铺开，再写本 UI 建模的键 —— 保证建模键永远赢，且未建模键不丢
    const o: Record<string, unknown> = { ...s._extra, seq: i + 1, approver_type: s.approver_type }
    if (s.levels != null && s.levels > 0) o.levels = s.levels
    if (isDutyTyped(s.approver_type) && s.duty_code) o.duty_code = s.duty_code
    if (s.approver_type === 'UNIT_DUTY' && s.institution_id != null && s.institution_id > 0) {
      o.institution_id = s.institution_id
    }
    if (s.approver_type === 'SPECIFIC' && s.approver_id) o.approver_id = s.approver_id
    if (s.threshold_days != null && s.threshold_days > 0) o.threshold_days = s.threshold_days
    if (s.mode && s.mode !== 'single') o.mode = s.mode
    if (s.whenEnabled && s.when_field) {
      const w: Record<string, unknown> = { field: s.when_field, op: s.when_op || '==' }
      const v = coerceValue(s.when_value)
      if (v !== undefined) w.value = v
      o.when = w
    }
    const cc: unknown[] = [...s.cc]
    s.cc_users.forEach((uid) => cc.push({ type: 'SPECIFIC', user_id: uid }))
    if (cc.length) o.cc = cc
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

.hint {
  line-height: 1.5;
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

.row-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
