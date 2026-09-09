<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="经营数据看板"
      description="此处维护的数据实时展示在客户端小程序「工作台」首页看板，支持本月 / 本季两套口径。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <el-radio-group v-model="period" size="small" @change="reloadAll">
            <el-radio-button value="month">本月</el-radio-button>
            <el-radio-button value="quarter">本季</el-radio-button>
          </el-radio-group>
          <el-button text type="primary" size="small" :loading="loading" @click="reloadAll">刷新</el-button>
        </div>
      </template>

      <!-- 指标卡 -->
      <div class="block-title">
        <span>指标卡（{{ period === 'month' ? '本月' : '本季' }}）</span>
        <el-button type="primary" size="small" @click="openMetric()">新增指标</el-button>
      </div>
      <el-table v-loading="loading" :data="metrics" stripe size="small">
        <el-table-column label="排序" prop="sortNo" width="70" />
        <el-table-column label="指标名" prop="label" min-width="120" />
        <el-table-column label="展示值" prop="valueText" min-width="110" />
        <el-table-column label="变化值" prop="deltaText" width="100" />
        <el-table-column label="涨跌" width="80">
          <template #default="{ row }">
            <el-tag :type="row.up === 1 ? 'success' : 'danger'" effect="plain" size="small">
              {{ row.up === 1 ? '上涨' : '下降' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="比较口径" prop="compareLabel" width="100" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openMetric(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="removeMetric(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无指标，点击「新增指标」录入" :image-size="60" /></template>
      </el-table>

      <!-- 趋势柱 -->
      <div class="block-title" style="margin-top: 20px">
        <span>趋势柱（近 N 期，单位：万元）</span>
        <el-button type="primary" size="small" @click="openTrend()">新增趋势点</el-button>
      </div>
      <el-table v-loading="loading" :data="trend" stripe size="small">
        <el-table-column label="排序" prop="sortNo" width="70" />
        <el-table-column label="X 轴标签" prop="pointLabel" min-width="120" />
        <el-table-column label="数值" prop="numValue" width="110" />
        <el-table-column label="当期高亮" width="100">
          <template #default="{ row }">
            <el-tag :type="row.hot === 1 ? 'primary' : 'info'" effect="plain" size="small">
              {{ row.hot === 1 ? '高亮' : '常规' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openTrend(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="removeTrend(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无趋势数据" :image-size="60" /></template>
      </el-table>

      <!-- AI 解读 -->
      <div class="block-title" style="margin-top: 20px">
        <span>AI 解读与数据来源</span>
        <el-button type="primary" size="small" :loading="savingInsight" @click="saveInsight">保存解读</el-button>
      </div>
      <el-form label-position="top" size="small">
        <el-form-item label="AI 解读正文">
          <el-input v-model="insight.content" type="textarea" :rows="3" placeholder="如：销售额环比 +12.3%，主要由华东区 3 个大单贡献…" />
        </el-form-item>
        <el-form-item label="数据来源说明">
          <el-input v-model="insight.sourceText" placeholder="如：来源：产品销售明细.xlsx · ERP 同步" />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 指标编辑弹层 -->
    <el-dialog v-model="metricDlg" :title="metricForm.id ? '编辑指标' : '新增指标'" width="420px">
      <el-form label-width="84px" size="small">
        <el-form-item label="指标名"><el-input v-model="metricForm.label" placeholder="如：销售额" /></el-form-item>
        <el-form-item label="展示值"><el-input v-model="metricForm.valueText" placeholder="如：¥286.4万" /></el-form-item>
        <el-form-item label="变化值"><el-input v-model="metricForm.deltaText" placeholder="如：+12.3%" /></el-form-item>
        <el-form-item label="涨跌">
          <el-radio-group v-model="metricForm.up">
            <el-radio :value="1">上涨</el-radio>
            <el-radio :value="0">下降</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="比较口径">
          <el-select v-model="metricForm.compareLabel" style="width: 100%">
            <el-option label="环比" value="环比" />
            <el-option label="同比" value="同比" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="metricForm.sortNo" :min="0" :max="999" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="metricDlg = false">取消</el-button>
        <el-button type="primary" size="small" @click="saveMetric">保存</el-button>
      </template>
    </el-dialog>

    <!-- 趋势编辑弹层 -->
    <el-dialog v-model="trendDlg" :title="trendForm.id ? '编辑趋势点' : '新增趋势点'" width="420px">
      <el-form label-width="84px" size="small">
        <el-form-item label="X 轴标签"><el-input v-model="trendForm.pointLabel" placeholder="如：9月" /></el-form-item>
        <el-form-item label="数值"><el-input-number v-model="trendForm.numValue" :min="0" :precision="1" /></el-form-item>
        <el-form-item label="当期高亮">
          <el-radio-group v-model="trendForm.hot">
            <el-radio :value="1">高亮</el-radio>
            <el-radio :value="0">常规</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="trendForm.sortNo" :min="0" :max="999" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="trendDlg = false">取消</el-button>
        <el-button type="primary" size="small" @click="saveTrend">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminCreateKpiMetric,
  adminCreateKpiTrend,
  adminDeleteKpiMetric,
  adminDeleteKpiTrend,
  adminGetKpiInsight,
  adminListKpiMetrics,
  adminListKpiTrend,
  adminUpdateKpiMetric,
  adminUpdateKpiTrend,
  adminUpsertKpiInsight,
  type KpiMetric,
  type KpiTrendPoint
} from '@/api/resource'

const period = ref<'month' | 'quarter'>('month')
const loading = ref(false)
const metrics = ref<KpiMetric[]>([])
const trend = ref<KpiTrendPoint[]>([])
const savingInsight = ref(false)

const insight = reactive({ content: '', sourceText: '' })

const metricDlg = ref(false)
const metricForm = reactive<Partial<KpiMetric> & { id?: number }>({})
const trendDlg = ref(false)
const trendForm = reactive<Partial<KpiTrendPoint> & { id?: number }>({})

async function reloadAll() {
  loading.value = true
  try {
    const [m, t, i] = await Promise.all([
      adminListKpiMetrics(period.value),
      adminListKpiTrend(period.value),
      adminGetKpiInsight(period.value)
    ])
    metrics.value = m || []
    trend.value = t || []
    insight.content = i?.content || ''
    insight.sourceText = i?.sourceText || ''
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('经营数据维护仅租户管理员可操作')
      metrics.value = []
      trend.value = []
    } else {
      ElMessage.error('经营数据加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

function openMetric(row?: KpiMetric) {
  Object.assign(metricForm, {
    id: row?.id,
    label: row?.label || '',
    valueText: row?.valueText || '',
    deltaText: row?.deltaText || '',
    up: row?.up ?? 1,
    compareLabel: row?.compareLabel || '环比',
    sortNo: row?.sortNo ?? metrics.value.length + 1
  })
  metricDlg.value = true
}

async function saveMetric() {
  if (!metricForm.label?.trim()) {
    ElMessage.warning('请填写指标名')
    return
  }
  try {
    const body = { ...metricForm, period: period.value }
    if (metricForm.id) await adminUpdateKpiMetric(metricForm.id, body)
    else await adminCreateKpiMetric(body)
    ElMessage.success('已保存')
    metricDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function removeMetric(row: KpiMetric) {
  try {
    await ElMessageBox.confirm(`确认删除指标「${row.label}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await adminDeleteKpiMetric(row.id)
  ElMessage.success('已删除')
  await reloadAll()
}

function openTrend(row?: KpiTrendPoint) {
  Object.assign(trendForm, {
    id: row?.id,
    pointLabel: row?.pointLabel || '',
    numValue: row?.numValue ?? 0,
    hot: row?.hot ?? 0,
    sortNo: row?.sortNo ?? trend.value.length + 1
  })
  trendDlg.value = true
}

async function saveTrend() {
  if (!trendForm.pointLabel?.trim()) {
    ElMessage.warning('请填写 X 轴标签')
    return
  }
  try {
    const body = { ...trendForm, period: period.value }
    if (trendForm.id) await adminUpdateKpiTrend(trendForm.id, body)
    else await adminCreateKpiTrend(body)
    ElMessage.success('已保存')
    trendDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function removeTrend(row: KpiTrendPoint) {
  try {
    await ElMessageBox.confirm(`确认删除趋势点「${row.pointLabel}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await adminDeleteKpiTrend(row.id)
  ElMessage.success('已删除')
  await reloadAll()
}

async function saveInsight() {
  savingInsight.value = true
  try {
    await adminUpsertKpiInsight(period.value, { content: insight.content, sourceText: insight.sourceText })
    ElMessage.success('解读已保存')
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    savingInsight.value = false
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.block-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 10px;
}
</style>
