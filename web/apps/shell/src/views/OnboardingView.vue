<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="企业入驻进度"
      description="8 步门禁：租户端完成 1~4 步（签约、建档、配额、授权），企业端完成 5~8 步（组织、能力、使用、结算）。每步都给出判定闸门与阻塞原因，未通过的门禁无法跳过。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>入驻总览（{{ list.length }} 家机构，已完成 {{ completedCount }} 家）</span>
          <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="list" stripe>
        <el-table-column label="机构" min-width="180">
          <template #default="{ row }">
            <span class="inst-name">{{ row.institutionName }}</span>
            <div class="muted small">{{ row.code }} · {{ row.adminName || '未设管理员' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="row.percent ?? 0"
              :stroke-width="10"
              :status="row.completed ? 'success' : undefined"
            />
          </template>
        </el-table-column>
        <el-table-column label="已完成步骤" width="110">
          <template #default="{ row }">{{ row.passedCount ?? 0 }} / {{ row.totalSteps ?? 8 }}</template>
        </el-table-column>
        <el-table-column label="当前步" width="80">
          <template #default="{ row }">{{ row.onboardStep ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.completed ? 'success' : 'warning'" effect="plain" size="small">
              {{ row.completed ? '已入驻' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="viewDetail(row)">查看 8 步</el-button>
            <el-button text type="primary" size="small" @click="advance(row)">推进</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 8 步明细 -->
    <el-drawer v-model="drawer" :title="detail.institutionName + ' · 入驻 8 步'" size="720px">
      <el-steps :active="detail.onboardStep ?? 0" direction="vertical" finish-status="success">
        <el-step
          v-for="s in detail.steps || []"
          :key="s.step"
          :title="`第 ${s.step} 步 · ${s.name}（${ownerText(s.owner)}）`"
          :status="s.passed ? 'success' : (s.current ? 'process' : 'wait')"
        >
          <template #description>
            <div class="step-desc">
              <div class="gate">闸门：{{ s.gate }}</div>
              <div v-if="s.passed" class="ok">已通过</div>
              <div v-else class="block">阻塞：{{ s.reason || '前序步骤未完成' }}</div>
            </div>
          </template>
        </el-step>
      </el-steps>
      <div v-if="!(detail.steps || []).length" class="muted">无明细</div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getOnboardingOverview, getOnboardingProgress, advanceOnboardingAll,
  type OnboardingProgress
} from '@/api/org'

interface OverviewRow {
  institutionId: number
  institutionName?: string
  code?: string
  adminName?: string
  onboardStep?: number
  passedCount?: number
  percent?: number
  completed?: boolean
}

const OWNERS: Record<string, string> = { TENANT: '租户端', ORG: '企业端', MEMBER: '成员端' }
function ownerText(v?: string) { return OWNERS[v || ''] || v || '—' }

const list = ref<OverviewRow[]>([])
const loading = ref(false)
const completedCount = ref(0)

async function reload() {
  loading.value = true
  try {
    const d = await getOnboardingOverview()
    list.value = ((d?.institutions as OverviewRow[]) || []).map((x) => ({
      ...x,
      totalSteps: (d?.totalSteps as number) ?? 8
    })) as OverviewRow[]
    completedCount.value = (d?.completedCount as number) ?? 0
  } catch (e: unknown) {
    ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}
onMounted(reload)

const drawer = ref(false)
const detail = ref<OnboardingProgress & { institutionName?: string; onboardStep?: number }>({} as OnboardingProgress)

async function viewDetail(row: OverviewRow) {
  try {
    const d = await getOnboardingProgress(row.institutionId)
    detail.value = { ...d, institutionName: row.institutionName, onboardStep: row.onboardStep }
    drawer.value = true
  } catch (e: unknown) {
    ElMessage.error('明细加载失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function advance(row: OverviewRow) {
  try {
    const r = await advanceOnboardingAll(row.institutionId)
    const blocked = r?.blockedAt as string | undefined
    if (r?.completed) {
      ElMessage.success('已推进至 8/8 步，入驻完成')
    } else {
      ElMessage.info('已推进到第 ' + (r?.advancedTo ?? '?') + ' 步' + (blocked ? '，阻塞于：' + blocked : ''))
    }
    await reload()
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message
    ElMessage.error(msg || '推进失败')
  }
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; }
.inst-name { font-weight: 600; }
.muted { color: #909399; }
.small { font-size: 12px; }
.step-desc { font-size: 12px; line-height: 1.6; }
.step-desc .gate { color: #606266; }
.step-desc .ok { color: #67c23a; }
.step-desc .block { color: #e6a23c; }
</style>
