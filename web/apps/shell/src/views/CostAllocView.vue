<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="费用分摊"
      description="按规则把平台账本用量分摊到各机构。规则支持版本化（修改即生成新版本，旧版本归档为 RETIRED）；试算不落库；账单生成幂等，重复生成不会重复建单；对账页展示与平台账本的一致率。"
      style="margin-bottom: 12px"
    />

    <!-- 规则 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <span>分摊规则（{{ rules.length }} 个版本）</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="reloadAll">刷新</el-button>
            <el-button type="primary" size="small" @click="openRuleDlg()">新增规则</el-button>
          </div>
        </div>
      </template>
      <el-table v-loading="loading" :data="rules" stripe size="small">
        <el-table-column label="规则名称" min-width="220" prop="name" show-overflow-tooltip />
        <el-table-column label="类型" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ ruleTypeText(row.ruleType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="70" prop="version" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="plain" size="small">
              {{ row.status === 'ACTIVE' ? '生效中' : '已归档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openSimDlg(row)" :disabled="row.status !== 'ACTIVE'">试算</el-button>
            <el-button text type="primary" size="small" @click="openRuleDlg(row)" :disabled="row.status !== 'ACTIVE'">改版</el-button>
            <el-button text type="primary" size="small" @click="genBills(row)" :disabled="row.status !== 'ACTIVE'">生成账单</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 账单 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>分摊账单（{{ period }}）</span>
          <div>
            <el-date-picker
              v-model="period"
              type="month"
              value-format="YYYY-MM"
              size="small"
              style="width: 130px; margin-right: 8px"
              @change="loadBills"
            />
            <el-button text type="primary" size="small" :loading="bLoading" @click="loadBills">刷新</el-button>
            <el-button type="primary" size="small" @click="reconcile">账本核对</el-button>
          </div>
        </div>
      </template>

      <el-descriptions v-if="recon" :column="4" border size="small" style="margin-bottom: 10px">
        <el-descriptions-item label="一致率">
          <el-tag :type="recon.consistentRate === 100 ? 'success' : 'danger'" size="small">{{ recon.consistentRate }}%</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="账单数">{{ recon.billCount ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="一致条数">{{ recon.consistentCount ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="不一致">{{ recon.mismatched ?? '—' }}</el-descriptions-item>
      </el-descriptions>

      <el-table v-loading="bLoading" :data="bills" stripe size="small">
        <el-table-column label="流水号" min-width="170" prop="serialNo" />
        <el-table-column label="机构" min-width="170" prop="institutionName" />
        <el-table-column label="统计期" width="90" prop="period" />
        <el-table-column label="规则版本" width="90" prop="ruleVersion" />
        <el-table-column label="用量（词元）" width="130" align="right">
          <template #default="{ row }">{{ (row.usageTokens ?? 0).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="金额（¥）" width="120" align="right">
          <template #default="{ row }">{{ (row.amount ?? 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" prop="status" />
      </el-table>
      <el-empty v-if="!bLoading && !bills.length" description="该统计期暂无账单" :image-size="56" />
    </el-card>

    <!-- 规则表单：固定比例 -->
    <el-dialog v-model="ruleDlg" :title="ruleForm.id ? '修改规则（将生成新版本）' : '新增分摊规则'" width="660">
      <el-form :model="ruleForm" label-width="110px" size="small">
        <el-form-item label="规则名称" required><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="规则类型">
          <el-select v-model="ruleForm.ruleType" style="width: 100%" disabled>
            <el-option label="固定比例" value="FIXED_RATIO" />
          </el-select>
        </el-form-item>
        <el-form-item label="分摊比例">
          <div class="ratios">
            <div v-for="(r, i) in ruleForm.ratios" :key="i" class="ratio-row">
              <el-select v-model="r.institutionId" placeholder="机构" style="flex: 1">
                <el-option v-for="i2 in institutions" :key="i2.id" :label="i2.name" :value="i2.id" />
              </el-select>
              <el-input-number v-model="r.ratio" :min="0" :max="100" :step="1" controls-position="right" style="width: 130px" />
              <span class="unit">%</span>
              <el-button text type="danger" size="small" @click="ruleForm.ratios.splice(i, 1)">删除</el-button>
            </div>
            <el-button text type="primary" size="small" @click="ruleForm.ratios.push({ institutionId: undefined, ratio: 0 })">+ 添加机构</el-button>
          </div>
        </el-form-item>
        <el-form-item label="合计">
          <el-tag :type="ratioSum === 100 ? 'success' : 'danger'" size="small">合计 {{ ratioSum }}%（须为 100%）</el-tag>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="ruleDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitRule">保存</el-button>
      </template>
    </el-dialog>

    <!-- 试算 -->
    <el-dialog v-model="simDlg" title="分摊试算（不落库）" width="760">
      <el-form :inline="true" size="small" style="margin-bottom: 8px">
        <el-form-item label="统计期"><el-input v-model="simForm.period" style="width: 120px" /></el-form-item>
        <el-form-item label="总用量（词元）">
          <el-input-number v-model="simForm.totalTokens" :min="0" :step="100000" style="width: 180px" />
        </el-form-item>
        <el-form-item><el-button type="primary" size="small" :loading="saving" @click="runSim">试算</el-button></el-form-item>
      </el-form>
      <el-table v-if="simRows.length" :data="simRows" size="small" stripe>
        <el-table-column label="机构" min-width="180">
          <template #default="{ row }">{{ instName(row.institutionId) }}</template>
        </el-table-column>
        <el-table-column label="比例" width="90">
          <template #default="{ row }">{{ row.ratio }}%</template>
        </el-table-column>
        <el-table-column label="用量（词元）" width="140" align="right">
          <template #default="{ row }">{{ (row.usageTokens ?? 0).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="金额（¥）" width="120" align="right">
          <template #default="{ row }">{{ (row.amount ?? 0).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="点击「试算」查看分摊结果" :image-size="48" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listCostRules, createCostRule, updateCostRule, simulateCostRule,
  listCostBills, generateCostBills, reconcileCostBills, listInstitutions,
  type CostRule, type CostBill, type Institution
} from '@/api/org'

const RULE_TYPES: Record<string, string> = { FIXED_RATIO: '固定比例' }
function ruleTypeText(v?: string) { return RULE_TYPES[v || ''] || v || '—' }

const loading = ref(false)
const bLoading = ref(false)
const saving = ref(false)
const rules = ref<CostRule[]>([])
const bills = ref<CostBill[]>([])
const institutions = ref<Institution[]>([])
const recon = ref<Record<string, unknown> | null>(null)
const period = ref(currentPeriod())

function currentPeriod() {
  const d = new Date()
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
}

function instName(id?: number) {
  return institutions.value.find((i) => i.id === id)?.name || ('#' + id)
}

async function loadBills() {
  bLoading.value = true
  try {
    bills.value = (await listCostBills(period.value)) || []
    recon.value = null
  } catch (e: unknown) {
    ElMessage.error('账单加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    bLoading.value = false
  }
}

async function reloadAll() {
  loading.value = true
  try {
    rules.value = (await listCostRules()) || []
    institutions.value = (await listInstitutions().catch(() => [])) || []
  } catch (e: unknown) {
    ElMessage.error('规则加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
  await loadBills()
}
onMounted(reloadAll)

function apiMsg(e: unknown, fallback: string) {
  return (e as { response?: { data?: { message?: string } } })?.response?.data?.message || fallback
}

// ---------------------------------------------------------------- 规则
const ruleDlg = ref(false)
const ruleForm = ref<{ id?: number; name: string; ruleType: string; ratios: { institutionId?: number; ratio: number }[] }>(
  { name: '', ruleType: 'FIXED_RATIO', ratios: [] }
)

const ratioSum = computed(() => ruleForm.value.ratios.reduce((s, r) => s + (r.ratio || 0), 0))

function openRuleDlg(row?: CostRule) {
  if (row?.id) {
    let ratios: { institutionId?: number; ratio: number }[] = []
    try {
      const cfg = JSON.parse(row.configJson || '{}')
      ratios = (cfg.ratios || []).map((r: { institutionId?: number; ratio?: number }) => ({
        institutionId: r.institutionId, ratio: r.ratio ?? 0
      }))
    } catch { ratios = [] }
    ruleForm.value = { id: row.id, name: row.name || '', ruleType: row.ruleType || 'FIXED_RATIO', ratios }
  } else {
    ruleForm.value = { name: '', ruleType: 'FIXED_RATIO', ratios: institutions.value.slice(0, 3).map((i) => ({ institutionId: i.id, ratio: 0 })) }
  }
  ruleDlg.value = true
}

async function submitRule() {
  if (!ruleForm.value.name) { ElMessage.warning('规则名称必填'); return }
  if (ratioSum.value !== 100) { ElMessage.warning('比例合计必须为 100%，当前 ' + ratioSum.value + '%'); return }
  saving.value = true
  try {
    const body = { name: ruleForm.value.name, ruleType: ruleForm.value.ruleType, config: { ratios: ruleForm.value.ratios } }
    if (ruleForm.value.id) await updateCostRule(ruleForm.value.id, body)
    else await createCostRule(body)
    ElMessage.success(ruleForm.value.id ? '已生成新版本，旧版本归档' : '规则已创建')
    ruleDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 试算
const simDlg = ref(false)
const simRows = ref<Record<string, unknown>[]>([])
const simForm = ref<{ ruleId?: number; period: string; totalTokens: number }>({ period: currentPeriod(), totalTokens: 2000000 })

function openSimDlg(row: CostRule) {
  simForm.value = { ruleId: row.id, period: currentPeriod(), totalTokens: 2000000 }
  simRows.value = []
  simDlg.value = true
}

async function runSim() {
  saving.value = true
  try {
    const r = await simulateCostRule(simForm.value.ruleId!, {
      period: simForm.value.period, totalTokens: simForm.value.totalTokens
    })
    simRows.value = (r?.rows as Record<string, unknown>[]) || []
    ElMessage.success('试算完成（未落库）')
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '试算失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 账单
async function genBills(row: CostRule) {
  saving.value = true
  try {
    const r = await generateCostBills({ ruleId: row.id, period: period.value })
    ElMessage.success('生成完成：新增 ' + (r?.created ?? 0) + ' 条')
    await loadBills()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '生成失败'))
  } finally {
    saving.value = false
  }
}

async function reconcile() {
  try {
    recon.value = await reconcileCostBills(period.value)
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '核对失败'))
  }
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }
.card-header > span:first-child { margin-right: auto; }
.ratios { width: 100%; }
.ratio-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.ratio-row .unit { color: #909399; }
</style>
