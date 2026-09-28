<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="企业入驻进度"
      description="8 步门禁：租户端完成 1~4 步（签约、建档、配额、授权），企业端完成 5~8 步（组织、能力、使用、结算）。每步都给出判定闸门与阻塞原因，未通过的门禁无法跳过；未完成的步骤可直接点进对应的设置页面。"
      style="margin-bottom: 12px"
    />

    <!-- 8 步路线图：完整展示 8 个步骤（含未解锁的），未完成的可点击直达设置页 -->
    <el-card ref="roadmapRef" shadow="never">
      <template #header>
        <div class="card-header">
          <span>
            8 步入驻路线
            <span v-if="detail.institutionName" class="inst-name">· {{ detail.institutionName }}</span>
          </span>
          <div class="head-ops">
            <el-select
              v-if="list.length > 1"
              :model-value="selectedId"
              size="small"
              style="width: 220px"
              placeholder="选择机构"
              @change="onPickInst"
            >
              <el-option
                v-for="i in list"
                :key="i.institutionId"
                :label="i.institutionName || `机构 ${i.institutionId}`"
                :value="i.institutionId"
              />
            </el-select>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
          </div>
        </div>
      </template>

      <div v-if="roadmapSteps.length" class="roadmap-head">
        <el-progress
          :percentage="headPercent"
          :stroke-width="10"
          :status="headCompleted ? 'success' : undefined"
          style="flex: 1"
        />
        <span class="pos">
          <template v-if="headCurrentStep != null">
            当前处于 <b>第 {{ headCurrentStep }} 步 / 共 {{ headTotal }} 步</b>
            <template v-if="headCurrentName">（{{ headCurrentName }}）</template>
          </template>
          <template v-else>
            8 步<b>已全部完成</b>
          </template>
        </span>
      </div>

      <div v-if="roadmapSteps.length" class="roadmap">
        <div
          v-for="s in roadmapSteps"
          :key="s.step"
          class="step-card"
          :class="[stateClass(s), { clickable: canGo(s) }]"
          @click="goStep(s)"
        >
          <div class="step-top">
            <span class="no">{{ s.step }}</span>
            <span class="nm">{{ s.name }}</span>
            <el-tag size="small" effect="plain" :type="stateTag(s).type">{{ stateTag(s).text }}</el-tag>
          </div>
          <div class="owner">{{ ownerText(s.owner) }}</div>
          <div class="gate">闸门：{{ s.gate }}</div>
          <div v-if="s.passed" class="line ok">已完成</div>
          <div v-else-if="isUnlocked(s)" class="line todo">未完成 · {{ s.reason || '待完成' }}</div>
          <div v-else class="line locked">未完成 · 需先完成第 {{ s.blockedByStep ?? '?' }} 步</div>
          <div v-if="canGo(s)" class="go">{{ s.routeLabel || '去处理' }} →</div>
          <div v-else-if="!s.passed" class="go muted">按顺序完成前序步骤后可进入</div>
        </div>
      </div>

      <el-empty
        v-else-if="!list.length"
        description="本租户尚无机构。第 1 步由平台运营端交付资源池，第 2 步起需先在「机构管理」建立机构。"
      >
        <!--
          路由取自后端目录（emptySteps[1] = 第 2 步「建立机构」），**不在此处硬编码路径** ——
          否则「每步跳哪里」就有两份定义，后端改路由时这里会静默失效（铁律 #1）。
        -->
        <el-button
          v-if="emptySteps[1]"
          type="primary"
          size="small"
          @click="goStep(emptySteps[1])"
        >
          {{ emptySteps[1].routeLabel || '去建立机构' }}
        </el-button>
      </el-empty>
      <el-empty v-else description="加载中…" />
    </el-card>

    <!-- 入驻总览：本租户全部机构 -->
    <el-card shadow="never" style="margin-top: 12px">
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
          <template #default="{ row }">{{ row.currentStep ?? '—' }}</template>
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
            <el-button text type="primary" size="small" @click="focusInst(row)">查看 8 步</el-button>
            <el-button text type="primary" size="small" @click="advance(row)">推进</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getOnboardingOverview, getOnboardingProgress, getOnboardingSteps, advanceOnboardingAll,
  type OnboardingProgress, type OnboardingStep, type OnboardingStepCatalog
} from '@/api/org'
import {
  institutionState,
  loadInstitutionScope,
  setCurrentInstitution
} from '@/api/institutionScope'

interface OverviewRow {
  institutionId: number
  institutionName?: string
  code?: string
  adminName?: string
  onboardStep?: number
  currentStep?: number | null
  passedCount?: number
  percent?: number
  completed?: boolean
  totalSteps?: number
}

const router = useRouter()

/**
 * 责任方代码 → 中文。
 *
 * <p>后端下发的是**代码**（PLATFORM_OPS / TENANT_ADMIN / ORG_ADMIN / MEMBER），页面上不能把裸码甩给用户。
 * 此前这里的映射键写的是 `TENANT/ORG/MEMBER`，与后端实际下发的代码**一个都对不上**，
 * 于是抽屉里显示成「（TENANT_ADMIN）」这种半成品。现在按后端真实代码建表，
 * 并由静态守卫断言「后端下发的每个 owner 代码在这里都有中文标签」——
 * 将来后端新增责任方却没有标签时会被守卫拦下，而不是又变成裸码。</p>
 */
const OWNERS: Record<string, string> = {
  PLATFORM_OPS: '平台运营端',
  TENANT_ADMIN: '租户管理员端',
  ORG_ADMIN: '企业管理员端',
  MEMBER: '成员端'
}
function ownerText(v?: string) { return (v && OWNERS[v]) || v || '—' }

const roadmapRef = ref<{ $el?: HTMLElement } | null>(null)
const list = ref<OverviewRow[]>([])
const loading = ref(false)
const completedCount = ref(0)
const selectedId = ref<number | null>(null)
const detail = ref<OnboardingProgress & { institutionName?: string }>({} as OnboardingProgress)
const catalog = ref<OnboardingStepCatalog | null>(null)

const institutionScopeLoaded = institutionState.loaded

/** 无机构时的兜底路线：仍**完整展示 8 步**（全部未完成），只把「建立机构」放开为可点。 */
const emptySteps = computed<OnboardingStep[]>(() =>
  (catalog.value?.steps || []).map((d) => ({
    step: d.step, key: d.key, name: d.name, owner: d.owner, gate: d.gate,
    route: d.route, routeLabel: d.routeLabel,
    passed: false, unlocked: d.step === 2, blockedByStep: d.step === 2 ? null : 2,
    current: d.step === 2
  }))
)

const roadmapSteps = computed<OnboardingStep[]>(() =>
  detail.value.institutionId ? (detail.value.steps || []) : emptySteps.value
)
const headTotal = computed(() => detail.value.institutionId ? (detail.value.totalSteps ?? 8) : (catalog.value?.totalSteps ?? 8))
const headPercent = computed(() => detail.value.institutionId ? (detail.value.percent ?? 0) : 0)
const headCompleted = computed(() => detail.value.institutionId ? !!detail.value.completed : false)
const headCurrentStep = computed<number | null>(() => {
  // null = 8 步全部通过（后端在「入驻已确认完成」时也回 null，避免每月重现「当前步」）
  if (detail.value.institutionId) return detail.value.currentStep ?? null
  return 2
})
const headCurrentName = computed(() =>
  detail.value.institutionId ? (detail.value.currentStepName || '') : '建立机构'
)

function isUnlocked(s: OnboardingStep) { return !!s.unlocked }
function canGo(s: OnboardingStep) { return !!s.route && (!!s.passed || isUnlocked(s)) }

function stateTag(s: OnboardingStep): { text: string; type: 'success' | 'primary' | 'info' } {
  if (s.passed) return { text: '已完成', type: 'success' }
  if (s.current) return { text: '进行中', type: 'primary' }
  if (isUnlocked(s)) return { text: '未完成', type: 'info' }
  return { text: '未开始', type: 'info' }
}
function stateClass(s: OnboardingStep) {
  if (s.passed) return 'is-done'
  if (s.current) return 'is-current'
  return isUnlocked(s) ? 'is-todo' : 'is-locked'
}

async function reload() {
  loading.value = true
  try {
    const d = await getOnboardingOverview()
    list.value = ((d?.institutions as OverviewRow[]) || []).map((x) => ({
      ...x,
      totalSteps: (d?.totalSteps as number) ?? 8
    }))
    completedCount.value = (d?.completedCount as number) ?? 0
    if (!list.value.length) {
      // 无机构时也要「展示完整的 8 个步骤」，故取静态定义兜底（后端唯一权威）。
      if (!catalog.value) {
        try { catalog.value = await getOnboardingSteps() } catch { /* 兜底失败则显示空态 */ }
      }
      detail.value = {} as OnboardingProgress
      return
    }
    const keep = selectedId.value && list.value.some((x) => x.institutionId === selectedId.value)
    await selectInstitution(keep ? selectedId.value! : list.value[0].institutionId)
  } catch (e: unknown) {
    ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

async function selectInstitution(id: number) {
  selectedId.value = id
  try {
    const d = await getOnboardingProgress(id)
    const row = list.value.find((x) => x.institutionId === id)
    detail.value = { ...d, institutionName: d.institutionName || row?.institutionName }
  } catch (e: unknown) {
    ElMessage.error('进度加载失败：' + ((e as Error)?.message || '后端异常'))
  }
}

function onPickInst(id: number) { void selectInstitution(id) }

function focusInst(row: OverviewRow) {
  void selectInstitution(row.institutionId)
  const el = roadmapRef.value?.$el
  if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/**
 * 点未完成的步骤 → 跳到该步骤对应的设置页面。
 *
 * <p>三条纪律：</p>
 * <ol>
 *   <li><b>未解锁不给跳</b>：前序没完成就跳过去，用户到页面也无从下手（例如机构还没建档就跳「组织搭建」）。
 *       此时明确告诉他卡在第几步——是「按顺序」，不是「按钮坏了」。</li>
 *   <li><b>路由以后端下发为准</b>：前端不写任何 `/xxx` 步骤路由字面量。</li>
 *   <li><b>先切当前机构再跳</b>：目标页（如组织与员工）按「当前机构」取数，
 *       不先切会跳到**另一家**机构的数据上——这种错位不会报错，只会让人以为数据错了。</li>
 * </ol>
 */
async function goStep(s: OnboardingStep) {
  if (!canGo(s)) {
    if (s.blockedByStep) {
      const blockedName = roadmapSteps.value.find((x) => x.step === s.blockedByStep)?.name || ''
      ElMessage.warning(`请先完成第 ${s.blockedByStep} 步「${blockedName}」`)
    }
    return
  }
  if (!s.route) { ElMessage.warning('该步骤尚未配置可跳转的设置页面'); return }
  const instId = detail.value.institutionId
  if (instId) {
    if (!institutionScopeLoaded.value) {
      try { await loadInstitutionScope() } catch { /* 失败也继续：目标页自己会兜底取数 */ }
    }
    setCurrentInstitution(instId)
  }
  await router.push(s.route)
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

onMounted(reload)
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.head-ops { display: flex; align-items: center; gap: 8px; }
.inst-name { font-weight: 600; }
.muted { color: #909399; }
.small { font-size: 12px; }

.roadmap-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.roadmap-head .pos { font-size: 13px; color: #606266; white-space: nowrap; }
.roadmap-head .pos b { color: #303133; }

.roadmap { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.step-card {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px;
  background: #fafafa;
  transition: box-shadow .15s, border-color .15s;
}
.step-card.clickable { cursor: pointer; }
.step-card.clickable:hover { border-color: #409eff; box-shadow: 0 2px 8px rgba(64, 158, 255, .15); }
.step-card.is-current { border-color: #409eff; background: #ecf5ff; }
.step-card.is-done { background: #f0f9eb; border-color: #e1f3d8; }
.step-card.is-locked { opacity: .72; }

.step-top { display: flex; align-items: center; gap: 6px; }
.step-top .no {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: #909399; color: #fff; font-size: 12px; flex: 0 0 auto;
}
.step-card.is-current .step-top .no { background: #409eff; }
.step-card.is-done .step-top .no { background: #67c23a; }
.step-top .nm { font-weight: 600; font-size: 13px; }
.step-top .el-tag { margin-left: auto; }

.owner { font-size: 12px; color: #909399; margin: 4px 0 2px; }
.gate { font-size: 12px; color: #606266; line-height: 1.5; }
.line { font-size: 12px; margin-top: 6px; line-height: 1.5; }
.line.ok { color: #67c23a; }
.line.todo { color: #e6a23c; }
.line.locked { color: #909399; }
.go { margin-top: 6px; font-size: 12px; color: #409eff; font-weight: 600; }
.go.muted { color: #c0c4cc; font-weight: 400; }
</style>
