<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="配额管理"
      description="查看租户词元配额总量与用量，向部门/成员二次分配配额，并查看按业务类型的用量报表与最近流水。"
      style="margin-bottom: 12px"
    />

    <el-row :gutter="12" style="margin-bottom: 12px">
      <el-col :span="6">
        <el-card shadow="never"><el-statistic title="成员总数" :value="overview?.memberCount || 0" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><el-statistic title="配额合计（词元）" :value="overview?.totalQuota || 0" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><el-statistic title="已用合计（词元）" :value="overview?.totalUsed || 0" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <el-statistic title="剩余合计（词元）" :value="overview?.totalFree || 0">
            <template #suffix>
              <el-tag size="small" type="success" effect="plain" style="margin-left: 6px">可用</el-tag>
            </template>
          </el-statistic>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <span>成员配额分配</span>
          <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="overview?.users || []" stripe>
        <el-table-column label="成员" min-width="140">
          <template #default="{ row }"><span class="name">{{ row.nickname }}</span></template>
        </el-table-column>
        <el-table-column label="ID" prop="userId" width="60" />
        <el-table-column label="配额" width="130">
          <template #default="{ row }"><span class="num">{{ fmt(row.quotaTokens) }}</span></template>
        </el-table-column>
        <el-table-column label="已用" width="130">
          <template #default="{ row }"><span class="num used">{{ fmt(row.usedTokens) }}</span></template>
        </el-table-column>
        <el-table-column label="使用率" min-width="180">
          <template #default="{ row }">
            <el-progress
              :percentage="pct(row.quotaTokens, row.usedTokens)"
              :stroke-width="8"
              :color="pct(row.quotaTokens, row.usedTokens) > 85 ? '#d93a3f' : '#0f9d63'"
            />
          </template>
        </el-table-column>
        <el-table-column label="最近变更" width="150">
          <template #default="{ row }">{{ row.updatedAt ? String(row.updatedAt).replace('T', ' ').slice(0, 16) : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openAssign(row)">调整配额</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无成员" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>用量报表（近 {{ days }} 天）</span>
          <el-select v-model="days" size="small" style="width: 110px" @change="reloadUsage">
            <el-option label="近 7 天" :value="7" />
            <el-option label="近 30 天" :value="30" />
            <el-option label="近 90 天" :value="90" />
          </el-select>
        </div>
      </template>
      <el-row :gutter="12">
        <el-col :span="10">
          <el-table :data="usage?.byBizType || []" stripe size="small">
            <el-table-column label="业务类型" prop="bizType" min-width="110" />
            <el-table-column label="调用次数" prop="cnt" width="90" />
            <el-table-column label="词元合计" width="120">
              <template #default="{ row }"><span class="num">{{ fmt(row.totalTokens) }}</span></template>
            </el-table-column>
            <el-table-column label="输入 / 输出" min-width="140">
              <template #default="{ row }" >
                <span class="num muted">{{ fmt(row.promptTokens) }} / {{ fmt(row.completionTokens) }}</span>
              </template>
            </el-table-column>
            <template #empty><el-empty description="统计周期内暂无调用" :image-size="60" /></template>
          </el-table>
        </el-col>
        <el-col :span="14">
          <el-table :data="usage?.recentLedger || []" stripe size="small">
            <el-table-column label="时间" width="140">
              <template #default="{ row }">{{ String(row.createdAt).replace('T', ' ').slice(5, 16) }}</template>
            </el-table-column>
            <el-table-column label="成员" prop="userName" width="90" />
            <el-table-column label="业务" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ row.bizTitle || row.bizType }}</template>
            </el-table-column>
            <el-table-column label="词元" width="90">
              <template #default="{ row }"><span class="num">+{{ fmt(row.totalTokens) }}</span></template>
            </el-table-column>
            <template #empty><el-empty description="暂无流水" :image-size="60" /></template>
          </el-table>
        </el-col>
      </el-row>
    </el-card>

    <el-dialog v-model="dlg" title="调整成员配额" width="420px">
      <el-form label-width="92px" size="small">
        <el-form-item label="成员">{{ assignRow?.nickname }}（#{{ assignRow?.userId }}）</el-form-item>
        <el-form-item label="当前配额"><span class="num">{{ fmt(assignRow?.quotaTokens || 0) }} 词元</span></el-form-item>
        <el-form-item label="新配额">
          <el-input-number v-model="assignValue" :min="0" :max="1000000000" :step="10000" style="width: 100%" />
          <div class="hint">已用量不变；剩余 = 新配额 + 赠送 − 已用</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" @click="doAssign">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  assignQuota,
  getQuotaOverview,
  getQuotaUsage,
  type QuotaOverview,
  type QuotaOverviewUser,
  type LedgerRow,
  type UsageRow
} from '@/api/resource'

const loading = ref(false)
const overview = ref<QuotaOverview | null>(null)
const usage = ref<{ since: string; byBizType: UsageRow[]; recentLedger: LedgerRow[] } | null>(null)
const days = ref(30)
const dlg = ref(false)
const assignRow = ref<QuotaOverviewUser | null>(null)
const assignValue = ref(0)

async function reload() {
  loading.value = true
  try {
    overview.value = await getQuotaOverview()
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('配额管理仅租户管理员可操作')
    } else {
      ElMessage.error('配额总览加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

async function reloadUsage() {
  try {
    usage.value = await getQuotaUsage(days.value)
  } catch (e: unknown) {
    ElMessage.error('用量报表加载失败：' + ((e as Error)?.message || '后端异常'))
  }
}

function openAssign(row: QuotaOverviewUser) {
  assignRow.value = row
  assignValue.value = row.quotaTokens || 0
  dlg.value = true
}

async function doAssign() {
  if (!assignRow.value) return
  try {
    await assignQuota(assignRow.value.userId, assignValue.value)
    ElMessage.success('配额已更新，即时生效')
    dlg.value = false
    await reload()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  }
}

function fmt(n?: number | string): string {
  const v = Number(n || 0)
  return v.toLocaleString('zh-CN')
}

function pct(quota: number, used: number): number {
  if (!quota) return used ? 100 : 0
  return Math.min(100, Math.round((used / quota) * 100))
}

onMounted(() => {
  void reload()
  void reloadUsage()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.name {
  font-weight: 600;
}

.num {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 12.5px;
}

.used {
  color: var(--el-color-warning);
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
</style>
