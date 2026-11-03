<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="计费与用量"
      description="计量明细逐笔可查（词元 × 单价 = 金额，与平台账本同源）；四维统计把同一批账本按个人 / 团队 / 部门 / 岗位重新聚合，口径一律回账本、不在页面另算；配额与预警管的是「下个月能不能继续用」。"
      style="margin-bottom: 12px"
    />

    <el-tabs v-model="tab" type="border-card">
      <!-- ================================ 计量明细 ================================ -->
      <el-tab-pane label="计量明细" name="ledger">
        <div class="stat-row">
          <div class="stat-card">
            <div class="stat-label">调用次数</div>
            <div class="stat-value">{{ ledger.length }}<span class="unit">次</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">消耗词元</div>
            <div class="stat-value">{{ fmt(ledgerTokens) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">计量金额</div>
            <div class="stat-value">¥{{ ledgerAmount.toFixed(2) }}</div>
          </div>
          <div class="stat-card highlight">
            <div class="stat-label">单次调用均价</div>
            <div class="stat-value">¥{{ avgPrice.toFixed(3) }}</div>
          </div>
        </div>

        <div class="toolbar">
          <el-date-picker v-model="ledgerPeriod" type="month" value-format="YYYY-MM" size="small"
                          style="width: 130px" :clearable="false" @change="loadLedger" />
          <el-select v-model="bizFilter" size="small" style="width: 150px" clearable placeholder="全部业务类型">
            <el-option v-for="b in BIZ_TYPES" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
          <el-input v-model="kw" size="small" style="width: 200px" placeholder="按业务标题筛选" clearable />
          <el-button text type="primary" size="small" :loading="loading" @click="loadLedger">刷新</el-button>
          <el-button size="small" :disabled="!rows.length">导出对账单</el-button>
          <span class="hint">单价 {{ unitPrice }} 元/词元（资源池合同价，{{ poolExpire }} 前不变）</span>
        </div>

        <el-table v-loading="loading" :data="rows" stripe size="small" height="444">
          <el-table-column label="计量时间" width="160">
            <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 19) }}</template>
          </el-table-column>
          <el-table-column label="业务类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ bizLabel(row.bizType) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="业务标题" min-width="230" prop="bizTitle" show-overflow-tooltip />
          <el-table-column label="输入词元" width="100" align="right">
            <template #default="{ row }">{{ fmt(row.promptTokens) }}</template>
          </el-table-column>
          <el-table-column label="输出词元" width="100" align="right">
            <template #default="{ row }">{{ fmt(row.completionTokens) }}</template>
          </el-table-column>
          <el-table-column label="合计" width="100" align="right">
            <template #default="{ row }">{{ fmt(row.totalTokens) }}</template>
          </el-table-column>
          <el-table-column label="单价（元/千词元）" width="150" align="right">
            <template #default>0.120</template>
          </el-table-column>
          <el-table-column label="金额（¥）" width="110" align="right">
            <template #default="{ row }">{{ ((row.totalTokens || 0) * unitPrice).toFixed(3) }}</template>
          </el-table-column>
          <el-table-column label="流水号" width="100">
            <template #default="{ row }"><span class="src">#{{ row.id }}</span></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ================================ 四维统计 ================================ -->
      <el-tab-pane label="四维统计" name="stats">
        <div class="toolbar">
          <el-radio-group v-model="dim" size="small">
            <el-radio-button value="user">个人</el-radio-button>
            <el-radio-button value="team">团队</el-radio-button>
            <el-radio-button value="dept">部门</el-radio-button>
            <el-radio-button value="duty">岗位</el-radio-button>
          </el-radio-group>
          <el-date-picker v-model="statsPeriod" type="month" value-format="YYYY-MM" size="small"
                          style="width: 130px" :clearable="false" @change="loadStats" />
          <el-button text type="primary" size="small" :loading="statsLoading" @click="loadStats">刷新</el-button>
          <span class="hint">{{ dimHint }}</span>
        </div>

        <div class="stat-row">
          <div class="stat-card">
            <div class="stat-label">统计期</div>
            <div class="stat-value small">{{ statsPeriod }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">{{ dimUnit }}数</div>
            <div class="stat-value">{{ statRows.length }}<span class="unit">{{ dimUnit }}</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">消耗词元（可归集）</div>
            <div class="stat-value">{{ fmt(statTotal) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">计量金额</div>
            <div class="stat-value">¥{{ (statTotal * unitPrice).toFixed(2) }}</div>
          </div>
        </div>

        <el-table v-loading="statsLoading" :data="statRows" stripe size="small" max-height="460">
          <el-table-column :label="dimUnit" min-width="180" prop="name" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="strong">{{ row.name }}</span>
              <el-tag v-if="row.tag" size="small" effect="plain" style="margin-left: 6px">{{ row.tag }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="dim !== 'user' && dim !== 'duty'" label="覆盖人数" width="100" align="right" prop="members" />
          <el-table-column label="消耗词元" width="130" align="right">
            <template #default="{ row }">{{ fmt(row.tokens) }}</template>
          </el-table-column>
          <el-table-column label="占比" width="150">
            <template #default="{ row }">
              <div class="ratio">
                <div class="ratio-bar"><i :style="{ width: pct(row.tokens) + '%' }" /></div>
                <span>{{ pct(row.tokens).toFixed(1) }}%</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="dim !== 'user'" label="人均词元" width="120" align="right">
            <template #default="{ row }">{{ row.members ? fmt(Math.round(row.tokens / row.members)) : '—' }}</template>
          </el-table-column>
          <el-table-column v-if="dim === 'user'" label="所属部门" min-width="150" prop="dept" show-overflow-tooltip />
          <el-table-column label="计量金额（¥）" width="130" align="right">
            <template #default="{ row }">{{ (row.tokens * unitPrice).toFixed(2) }}</template>
          </el-table-column>
        </el-table>

        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 10px"
          title="口径说明"
          description="四维统计只归集「能追到人」的账本：个人 → 团队 → 部门 → 岗位四张表由同一批账本聚合，合计恒等，页面不产生新数字。共享账号没有归属人，其消耗不计入个人与岗位维度，单独在「账号管理 → 共享账号」查看。"
        />
      </el-tab-pane>

      <!-- ============================== 配额与预警 ============================== -->
      <el-tab-pane label="配额与预警" name="quota">
        <el-card shadow="never" style="margin-bottom: 12px">
          <template #header>
            <div class="card-header">
              <span>租户资源池（{{ quotaPeriod }}）</span>
              <div>
                <el-button text type="primary" size="small" :loading="quotaLoading" @click="loadQuota">刷新</el-button>
                <el-button type="primary" size="small">池扩容 / 调参</el-button>
              </div>
            </div>
          </template>
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="词元总量">{{ fmt(pool.tokenTotal) }}</el-descriptions-item>
            <el-descriptions-item label="已分配机构">{{ fmt(pool.allocatedTokens) }}</el-descriptions-item>
            <el-descriptions-item label="可分配余量">{{ fmt(pool.allocatableTokens) }}</el-descriptions-item>
            <el-descriptions-item label="本租户已用">{{ fmt(pool.tokenUsed) }}</el-descriptions-item>
            <el-descriptions-item label="预警阈值">
              <el-tag type="warning" size="small" effect="plain">使用率 ≥ {{ pool.warnThreshold ?? 20 }}%</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="结算单价">{{ unitPrice }} 元/词元</el-descriptions-item>
            <el-descriptions-item label="专家座席">{{ pool.expertUsed ?? 0 }} / {{ pool.expertSeats ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="技能座席">{{ pool.skillUsed ?? 0 }} / {{ pool.skillSeats ?? 0 }}</el-descriptions-item>
          </el-descriptions>
          <div class="usage-bar">
            <span class="usage-label">池使用率</span>
            <el-progress :percentage="Number(pool.usageRatio ?? 0)" :stroke-width="14" :color="barColor" style="flex: 1" />
          </div>
        </el-card>

        <el-card shadow="never" style="margin-bottom: 12px">
          <template #header><span>机构配额与预警（{{ quotaPeriod }}）</span></template>
          <el-table :data="quotas" stripe size="small">
            <el-table-column label="机构" min-width="240" prop="institutionName" show-overflow-tooltip />
            <el-table-column label="配额词元" width="140" align="right">
              <template #default="{ row }">{{ fmt(row.quotaTokens) }}</template>
            </el-table-column>
            <el-table-column label="追加额度" width="120" align="right">
              <template #default="{ row }">{{ fmt(row.freeTokens) }}</template>
            </el-table-column>
            <el-table-column label="已用" width="140" align="right">
              <template #default="{ row }">{{ fmt(row.usedTokens) }}</template>
            </el-table-column>
            <el-table-column label="使用率" width="180">
              <template #default="{ row }">
                <el-progress :percentage="usagePct(row)" :stroke-width="12" :color="barColor" />
              </template>
            </el-table-column>
            <el-table-column label="预警" width="110">
              <template #default="{ row }">
                <el-tag v-if="usagePct(row) >= Number(pool.warnThreshold ?? 20)" type="warning" size="small">已触发</el-tag>
                <el-tag v-else type="success" size="small" effect="plain">正常</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150">
              <template #default>
                <el-button text type="primary" size="small">调额</el-button>
                <el-button text type="warning" size="small">冻结</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <div class="two-col">
          <el-card shadow="never">
            <template #header><span>预警规则</span></template>
            <el-table :data="warnRules" size="small" stripe>
              <el-table-column label="档位" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.tag" size="small" effect="plain">{{ row.level }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="触发条件" min-width="170" prop="cond" />
              <el-table-column label="通知对象" min-width="130" prop="to" />
              <el-table-column label="渠道" width="140" prop="channel" />
            </el-table>
          </el-card>
          <el-card shadow="never">
            <template #header><span>配额调整记录</span></template>
            <el-table :data="logs" size="small" stripe max-height="196">
              <el-table-column label="时间" width="150">
                <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 16) }}</template>
              </el-table-column>
              <el-table-column label="机构" min-width="150" show-overflow-tooltip>
                <template #default="{ row }">{{ instName(row.institutionId) }}</template>
              </el-table-column>
              <el-table-column label="变动" width="110" align="right">
                <template #default="{ row }">
                  <span :class="(row.delta || 0) >= 0 ? 'up' : 'down'">
                    {{ (row.delta || 0) >= 0 ? '+' : '' }}{{ fmt(row.delta) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="经办" width="100" prop="operatorName" />
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { http, unwrap } from '@/api'
import {
  getResourcePool, listOrgQuotas, listQuotaLogs, getOrgUsage, listMembers, listInstitutions,
  type ResourcePool, type OrgQuota, type QuotaLog, type Institution, type OrgMember
} from '@/api/org'
import { tenantState } from '@/api/tenantScope'

const BIZ_TYPES = [
  { value: 'CHAT', label: '智能问答' },
  { value: 'REPORT', label: '报告生成' },
  { value: 'SKILL', label: '技能调用' },
  { value: 'AGENT', label: '数字员工' }
]
function bizLabel(v?: string) {
  return BIZ_TYPES.find((b) => b.value === v)?.label || v || '—'
}

/** 结算单价：资源池合同价，本页所有金额都由它乘出来，不另设口径。 */
const unitPrice = 0.00012
const poolExpire = '2027-12-31'

const tab = ref('ledger')
const loading = ref(false)

function fmt(v?: number | null) {
  return (v ?? 0).toLocaleString('zh-CN')
}

/** 上一个完整月：本月尚未结账，账本类页面默认看上月。 */
function lastPeriod(): string {
  const cur = tenantState.currentPeriod.value || '2026-11'
  const [y, m] = cur.split('-').map(Number)
  const d = new Date(y, (m || 1) - 2, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// ------------------------------------------------------------------ 计量明细
interface LedgerRow {
  id?: number
  bizType?: string
  bizTitle?: string
  promptTokens?: number
  completionTokens?: number
  totalTokens?: number
  createdAt?: string
}

const ledgerPeriod = ref(lastPeriod())
const ledger = ref<LedgerRow[]>([])
const bizFilter = ref('')
const kw = ref('')

const rows = computed(() =>
  ledger.value.filter(
    (r) =>
      (!bizFilter.value || r.bizType === bizFilter.value) &&
      (!kw.value || (r.bizTitle || '').includes(kw.value))
  )
)
const ledgerTokens = computed(() => rows.value.reduce((s, r) => s + (r.totalTokens || 0), 0))
const ledgerAmount = computed(() => ledgerTokens.value * unitPrice)
const avgPrice = computed(() => (rows.value.length ? ledgerAmount.value / rows.value.length : 0))


async function loadLedger() {
  loading.value = true
  try {
    const data = await http
      .get('/ledger', { params: { limit: 200 } })
      .then((r) => unwrap<LedgerRow[]>(r))
    // 账本接口按「当前账号可见范围」返回，前端再按统计期收窄，避免跨月混算
    ledger.value = (data || []).filter((r) => (r.createdAt || '').slice(0, 7) === ledgerPeriod.value)
  } catch (e: unknown) {
    ElMessage.error('计量明细加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

// ------------------------------------------------------------------ 四维统计
type Dim = 'user' | 'team' | 'dept' | 'duty'
const dim = ref<Dim>('user')
const statsPeriod = ref(lastPeriod())
const statsLoading = ref(false)
const institutions = ref<Institution[]>([])
const usage = ref<{ inst: Institution; members: { userId: number; tokens: number }[]; total: number }[]>([])
const membersById = ref<Record<number, OrgMember>>({})

const dimUnit = computed(() => ({ user: '人', team: '团队', dept: '部门', duty: '岗位' }[dim.value]))
const dimHint = computed(
  () =>
    ({
      user: '按人聚合：谁在用、用了多少，可追到工号',
      team: '按机构（团队）聚合：单位之间的用量对比与人均',
      dept: '按部门聚合：内设科室的用量分布，用于内部再分配',
      duty: '按岗位聚合：同一岗位的人均用量，判断权限该给到哪一档'
    }[dim.value])
)

interface StatRow { name: string; tokens: number; members?: number; dept?: string; tag?: string }
const statRows = computed<StatRow[]>(() => {
  const agg = new Map<string, StatRow>()
  const bump = (key: string, tokens: number, member?: OrgMember) => {
    const cur = agg.get(key) || { name: key, tokens: 0, members: 0, dept: member?.departmentName, tag: undefined }
    cur.tokens += tokens
    cur.members = (cur.members || 0) + (member ? 1 : 0)
    agg.set(key, cur)
  }

  for (const u of usage.value) {
    for (const m of u.members) {
      const mem = membersById.value[m.userId]
      const who = mem?.name || `用户#${m.userId}`
      const dept = mem?.departmentName || '未分配部门'
      const duty = mem?.jobTitle || '未定岗'
      if (dim.value === 'user') {
        bump(who, m.tokens, mem)
        const cur = agg.get(who)
        if (cur) { cur.dept = dept; cur.tag = mem?.employeeNo }
      } else if (dim.value === 'team') {
        bump(u.inst.name || `机构#${u.inst.id}`, m.tokens)
      } else if (dim.value === 'dept') {
        bump(`${dept}`, m.tokens, mem)
      } else {
        bump(duty, m.tokens, mem)
      }
    }
  }
  return [...agg.values()].filter((r) => r.tokens > 0).sort((a, b) => b.tokens - a.tokens)
})
const statTotal = computed(() => statRows.value.reduce((s, r) => s + r.tokens, 0))
function pct(t: number) {
  return statTotal.value ? (t * 100) / statTotal.value : 0
}

async function loadStats() {
  statsLoading.value = true
  try {
    if (!institutions.value.length) {
      institutions.value = ((await listInstitutions().catch(() => [])) || []).filter((i) => i.status === 'ACTIVE')
    }
    const out: { inst: Institution; members: { userId: number; tokens: number }[]; total: number }[] = []
    const map: Record<number, OrgMember> = { ...membersById.value }
    for (const inst of institutions.value.slice(0, 6)) {
      const u = await getOrgUsage(statsPeriod.value, inst.id as number).catch(() => null)
      const list = ((u?.members as { userId: number; tokens: number }[]) || []).filter((m) => (m.tokens || 0) > 0)
      if (!list.length) continue
      const mem = (await listMembers({ page: 1, size: 200 }, inst.id as number).catch(() => ({ items: [] }))) as { items: OrgMember[] }
      for (const m of mem.items || []) if (m.userId) map[m.userId] = { ...m, departmentName: m.departmentName || '未分配部门' }
      out.push({ inst, members: list, total: (u?.institutionUsageTokens as number) || 0 })
    }
    membersById.value = map
    usage.value = out
  } finally {
    statsLoading.value = false
  }
}

// ------------------------------------------------------------------ 配额与预警
const quotaPeriod = ref(tenantState.currentPeriod.value || '2026-11')
const quotaLoading = ref(false)
const pool = ref<ResourcePool>({})
const quotas = ref<OrgQuota[]>([])
const logs = ref<(QuotaLog & { delta?: number })[]>([])

function instName(id?: number) {
  return institutions.value.find((i) => i.id === id)?.name || (id ? '机构#' + id : '—')
}

/** 使用率按「基础配额」算：追加额度（freeTokens）单独一列，不摊进分母。 */
function usagePct(row: OrgQuota) {
  const total = row.quotaTokens || 0
  return total ? Math.min(100, Math.round(((row.usedTokens || 0) * 100) / total)) : 0
}
function barColor(p: number) {
  if (p >= 80) return '#C0392B'
  if (p >= 50) return '#E6A23C'
  return '#2F5D50'
}

const warnRules = computed(() => [
  { level: '提示', tag: 'info' as const, cond: `使用率 ≥ ${pool.value.warnThreshold ?? 20}%`, to: '机构管理员', channel: '站内信' },
  { level: '预警', tag: 'warning' as const, cond: '使用率 ≥ 50%', to: '机构 + 租户管理员', channel: '站内信 + 短信' },
  { level: '停服', tag: 'danger' as const, cond: '使用率 ≥ 100%', to: '租户管理员', channel: '站内信 + 短信 + 横幅' }
])

async function loadQuota() {
  quotaLoading.value = true
  try {
    pool.value = (await getResourcePool(quotaPeriod.value).catch(() => ({}))) || {}
    quotas.value = (await listOrgQuotas(quotaPeriod.value).catch(() => [])) || []
    logs.value = (await listQuotaLogs({ period: quotaPeriod.value, limit: 30 }).catch(() => [])) || []
  } finally {
    quotaLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadLedger(), loadStats(), loadQuota()])
})
</script>

<style scoped>
.stat-row { display: flex; gap: 12px; margin-bottom: 12px; }
.stat-card {
  flex: 1;
  background: #faf9f5;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 14px;
}
.stat-card.highlight { background: #f2f6f4; border-color: #cfdcd6; }
.stat-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.stat-value { font-size: 22px; font-weight: 600; color: #1f2933; line-height: 1.2; white-space: nowrap; }
.stat-value.small { font-size: 18px; padding-top: 3px; }
.stat-value .unit { font-size: 12px; font-weight: 400; color: #909399; margin-left: 3px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.toolbar .hint { margin-left: auto; font-size: 12px; color: #909399; }
.card-header { display: flex; align-items: center; gap: 6px; }
.card-header > span:first-child { margin-right: auto; }
.usage-bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.usage-label { font-size: 12px; color: #909399; white-space: nowrap; }
.two-col { display: flex; gap: 12px; }
.two-col > * { flex: 1; min-width: 0; }
.ratio { display: flex; align-items: center; gap: 6px; }
.ratio-bar { flex: 1; height: 6px; background: #eef0f2; border-radius: 3px; overflow: hidden; }
.ratio-bar i { display: block; height: 6px; background: #2f5d50; }
.ratio span { font-size: 12px; color: #606266; width: 44px; text-align: right; }
.strong { font-weight: 500; color: #1f2933; }
.src { color: #7a8590; font-size: 12px; }
.up { color: #c0392b; }
.down { color: #2f7d4f; }
</style>
