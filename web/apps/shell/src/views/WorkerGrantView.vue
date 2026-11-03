<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="数字人授权"
      description="数字人不再全局开通，而是「按需到部门」：先给部门开席位，再按岗位授权具体数字人。部门没开席位，岗位授权一律不可选；岗位授权决定的是「这个人能不能用」，部门席位决定的是「这个部门总共用多少」。"
      style="margin-bottom: 12px"
    />

    <el-tabs v-model="tab" type="border-card">
      <!-- ============================== 按部门开通 ============================== -->
      <el-tab-pane label="按部门开通" name="dept">
        <div class="stat-row">
          <div class="stat-card">
            <div class="stat-label">已开通部门</div>
            <div class="stat-value">{{ openedCount }}<span class="unit">/ {{ deptRows.length }}</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">已占席位</div>
            <div class="stat-value">{{ seatUsed }}<span class="unit">席</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">上月用量</div>
            <div class="stat-value">{{ fmt(totalTokens) }}<span class="unit">词元</span></div>
          </div>
          <div class="stat-card highlight">
            <div class="stat-label">资源池可用座席</div>
            <div class="stat-value">{{ seatLeft }}<span class="unit">/ {{ seatPool }} 席</span></div>
          </div>
        </div>

        <div class="toolbar">
          <el-select v-model="instFilter" size="small" style="width: 220px" placeholder="全部机构" clearable>
            <el-option v-for="i in institutions" :key="i.id" :label="i.name" :value="i.id" />
          </el-select>
          <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
          <el-button type="primary" size="small">批量开通</el-button>
          <span class="hint">开通即占用租户资源池的「专家座席」，回收后座席立刻可分配给其他部门</span>
        </div>

        <el-table v-loading="loading" :data="filteredDeptRows" stripe size="small" max-height="480">
          <el-table-column label="部门" min-width="200">
            <template #default="{ row }">
              <span class="strong">{{ row.dept }}</span>
              <span class="sub">{{ row.inst }}</span>
            </template>
          </el-table-column>
          <el-table-column label="在岗人数" width="100" align="right" prop="members" />
          <el-table-column label="已开通数字人" min-width="260">
            <template #default="{ row }">
              <template v-if="row.workers.length">
                <el-tag v-for="w in row.workers" :key="w" size="small" effect="plain" style="margin-right: 4px">{{ w }}</el-tag>
              </template>
              <span v-else class="muted">未开通</span>
            </template>
          </el-table-column>
          <el-table-column label="席位" width="110" align="right">
            <template #default="{ row }">{{ row.seats }} / {{ row.seatTotal }}</template>
          </el-table-column>
          <el-table-column label="上月用量（词元）" width="150" align="right">
            <template #default="{ row }">{{ fmt(row.tokens) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.seats ? 'success' : 'info'" effect="plain">
                {{ row.seats ? '已开通' : '未开通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="190">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDept(row)">{{ row.seats ? '调整席位' : '开通' }}</el-button>
              <el-button text type="danger" size="small" :disabled="!row.seats">回收</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 按岗位授权 ============================== -->
      <el-tab-pane label="按岗位授权" name="duty">
        <div class="toolbar">
          <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
          <el-button type="primary" size="small">新建授权</el-button>
          <span class="hint">岗位授权按「职务」下发，员工调岗后自动继承新岗位的授权、失去原岗位的授权</span>
        </div>

        <el-table v-loading="loading" :data="dutyRows" stripe size="small" max-height="420">
          <el-table-column label="岗位" min-width="160" prop="duty" />
          <el-table-column label="归属部门" min-width="170" prop="dept" show-overflow-tooltip />
          <el-table-column label="在岗人数" width="100" align="right" prop="members" />
          <el-table-column label="授权数字人" min-width="250">
            <template #default="{ row }">
              <el-tag v-for="w in row.workers" :key="w" size="small" effect="plain" style="margin-right: 4px">{{ w }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数据范围" width="150" prop="scope" />
          <el-table-column label="人均月额度（词元）" width="170" align="right">
            <template #default="{ row }">{{ fmt(row.quota) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'" effect="plain">
                {{ row.enabled ? '生效中' : '已停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDuty(row)">改授权</el-button>
              <el-button text type="danger" size="small">撤销</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 12px"
          title="两级校验"
          :description="`岗位授权只放行「用哪个数字人」，金额与次数仍受个人配额约束：上月该租户人均 ${fmt(avgTokens)} 词元，局级岗位人均 ${fmt(topAvg)} 词元，差 ${ratio}x。授权下发前会先校验部门席位余量，席满则拒绝，不会出现「有权限但跑不起来」。`"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getDepartments, getOrgUsage, listInstitutions, listMembers, getResourcePool, type Institution, type OrgMember } from '@/api/org'
import { adminListWorkers } from '@/api/resource'
import { tenantState } from '@/api/tenantScope'

const tab = ref('dept')
const loading = ref(false)
const institutions = ref<Institution[]>([])
const instFilter = ref<number | ''>('')
const workers = ref<string[]>([])
const memberRows = ref<{ userId: number; name: string; jobTitle: string; dept: string; inst: string; instId: number; deptId: number; tokens: number }[]>([])

function fmt(v?: number | null) {
  return (v ?? 0).toLocaleString('zh-CN')
}

function lastPeriod(): string {
  const cur = tenantState.currentPeriod.value || '2026-11'
  const [y, m] = cur.split('-').map(Number)
  const d = new Date(y, (m || 1) - 2, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** 部门开通配置：真实部门树 + 演示开通口径（席位 / 已开通数字人）。 */
const OPENING: Record<number, { workers: string[]; seats: number; seatTotal: number }> = {
  10: { workers: ['公文写作助手', '会议纪要员'], seats: 3, seatTotal: 6 },
  11: { workers: ['政策问答助手', '材料预审员'], seats: 3, seatTotal: 8 },
  12: { workers: ['价格测算助手'], seats: 1, seatTotal: 4 },
  14: { workers: ['数据核查员'], seats: 1, seatTotal: 2 },
  20: { workers: ['审批要件核验', '政策问答助手'], seats: 2, seatTotal: 8 },
  21: { workers: ['事项引导员'], seats: 1, seatTotal: 4 },
  15: { workers: [], seats: 0, seatTotal: 4 },
  16: { workers: [], seats: 0, seatTotal: 2 }
}

const deptRows = ref<{ dept: string; deptId: number; inst: string; instId: number; members: number; workers: string[]; seats: number; seatTotal: number; tokens: number }[]>([])

const filteredDeptRows = computed(() =>
  instFilter.value ? deptRows.value.filter((r) => r.instId === instFilter.value) : deptRows.value
)
const openedCount = computed(() => deptRows.value.filter((r) => r.seats > 0).length)
const seatUsed = computed(() => deptRows.value.reduce((s, r) => s + r.seats, 0))
const totalTokens = computed(() => deptRows.value.reduce((s, r) => s + r.tokens, 0))
/** 座席池：与租户资源池的「专家座席」同一口径，不另设上限。 */
const seatPool = ref(12)
const seatLeft = computed(() => Math.max(0, seatPool.value - seatUsed.value))

const dutyRows = computed(() => {
  const agg = new Map<string, { duty: string; dept: string; members: number; workers: string[]; scope: string; quota: number; enabled: boolean }>()
  for (const m of memberRows.value) {
    const key = m.jobTitle || '未定岗'
    const cur = agg.get(key) || {
      duty: key,
      dept: m.dept,
      members: 0,
      workers: DUTY_WORKERS[key] || ['政策问答助手'],
      scope: DUTY_SCOPE[key] || '本部门数据',
      quota: DUTY_QUOTA[key] || 15000,
      enabled: true
    }
    cur.members += 1
    agg.set(key, cur)
  }
  return [...agg.values()].sort((a, b) => b.members - a.members)
})

const DUTY_WORKERS: Record<string, string[]> = {
  局长: ['数字员工-决策简报', '政策问答助手'],
  办公室主任: ['公文写作助手', '会议纪要员', '政策问答助手'],
  科员: ['政策问答助手', '材料预审员'],
  副主任科员: ['价格测算助手', '政策问答助手'],
  副科长: ['审批要件核验'],
  工作人员: ['数据核查员'],
  未定岗: []
}
const DUTY_SCOPE: Record<string, string> = {
  局长: '全租户', 办公室主任: '本机构', 科员: '本部门', 副主任科员: '本部门', 副科长: '本部门', 工作人员: '本人'
}
const DUTY_QUOTA: Record<string, number> = {
  局长: 40000, 办公室主任: 30000, 科员: 15000, 副主任科员: 15000, 副科长: 20000, 工作人员: 10000
}

const avgTokens = computed(() => {
  const n = memberRows.value.length
  return n ? Math.round(memberRows.value.reduce((s, m) => s + m.tokens, 0) / n) : 0
})
const topAvg = computed(() => {
  const top = memberRows.value.filter((m) => m.jobTitle === '局长')
  return top.length ? Math.round(top.reduce((s, m) => s + m.tokens, 0) / top.length) : 0
})
const ratio = computed(() => (avgTokens.value ? (topAvg.value / avgTokens.value).toFixed(1) : '—'))

function openDept(_row: unknown) {
  ElMessage.info('开通 / 调整席位：选择数字人与席位数，提交后占用资源池专家座席')
}
function openDuty(_row: unknown) {
  ElMessage.info('改授权：仅可勾选「本部门已开通席位」的数字人')
}

async function load() {
  loading.value = true
  try {
    const period = lastPeriod()
    if (!institutions.value.length) {
      institutions.value = ((await listInstitutions().catch(() => [])) || []).filter((i) => i.status === 'ACTIVE').slice(0, 3)
    }
    if (!workers.value.length) {
      const ws = (await adminListWorkers().catch(() => [])) || []
      workers.value = ws.map((w: { name?: string }) => w.name || '')
    }
    const pool = await getResourcePool(tenantState.currentPeriod.value || '2026-11').catch(() => null)
    if (pool?.expertSeats) seatPool.value = pool.expertSeats
    const rows: typeof deptRows.value = []
    const mem: typeof memberRows.value = []
    for (const inst of institutions.value) {
      const tree = (await getDepartments(inst.id as number).catch(() => ({ tree: [] }))).tree || []
      const flat: { id: number; name: string }[] = []
      const walk = (nodes: { id?: number; name?: string; children?: unknown[] }[]) => {
        for (const n of nodes) {
          if (n.id) flat.push({ id: n.id, name: n.name || '' })
          if (n.children?.length) walk(n.children as { id?: number; name?: string; children?: unknown[] }[])
        }
      }
      walk(tree as { id?: number; name?: string; children?: unknown[] }[])

      const usage = await getOrgUsage(period, inst.id as number).catch(() => null)
      const list = (await listMembers({ page: 1, size: 200 }, inst.id as number).catch(() => ({ items: [] }))) as { items: OrgMember[] }
      const tokenByUser: Record<number, number> = {}
      for (const u of (usage?.members as { userId: number; tokens: number }[]) || []) tokenByUser[u.userId] = u.tokens || 0

      for (const m of list.items || []) {
        mem.push({
          userId: m.userId || 0,
          name: m.name || '',
          jobTitle: m.jobTitle || '未定岗',
          dept: m.departmentName || flat.find((d) => d.id === m.departmentId)?.name || '未分配部门',
          inst: inst.name || '',
          instId: inst.id as number,
          deptId: m.departmentId || 0,
          tokens: tokenByUser[m.userId || 0] || 0
        })
      }

      for (const d of flat) {
        const opening = OPENING[d.id] || { workers: [], seats: 0, seatTotal: 0 }
        const members = (list.items || []).filter((m) => m.departmentId === d.id)
        rows.push({
          dept: d.name,
          deptId: d.id,
          inst: inst.name || '',
          instId: inst.id as number,
          members: members.length,
          workers: opening.workers,
          seats: opening.seats,
          seatTotal: opening.seatTotal,
          tokens: members.reduce((s, m) => s + (tokenByUser[m.userId || 0] || 0), 0)
        })
      }
    }
    deptRows.value = rows.filter((r) => r.seatTotal > 0)
    memberRows.value = mem
  } catch (e: unknown) {
    ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

onMounted(load)
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
.stat-value .unit { font-size: 12px; font-weight: 400; color: #909399; margin-left: 3px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.toolbar .hint { margin-left: auto; font-size: 12px; color: #909399; }
.strong { font-weight: 500; color: #1f2933; }
.sub { margin-left: 8px; font-size: 12px; color: #909399; }
.muted { color: #b0b6bd; font-size: 12px; }
</style>
