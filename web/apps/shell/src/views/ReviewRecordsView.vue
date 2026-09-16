<template>
  <div class="rr-page">
    <el-alert
      v-if="forbidden"
      type="warning"
      :closable="false"
      show-icon
      title="审核记录仅平台管理员或租户管理员可查看"
      description="平台管理员可看全量；租户管理员只看本租户。"
    />

    <template v-else>
      <div class="rr-head">
        <div>
          <div class="rr-title">
            <el-icon><DocumentChecked /></el-icon>
            <span>审核记录</span>
          </div>
          <p class="rr-desc">
            集中留痕四类审核数据：数字员工、AI 专家、专家配置（需求⑤）、权限申请授权（需求①）。
            每行同时给出<b>提交方</b>与<b>处理方</b>，回答「谁在什么时候审的、结论是什么」。
          </p>
        </div>
        <el-tag :type="scope === 'ALL_TENANTS' ? 'danger' : 'info'" size="small">
          {{ scope === 'ALL_TENANTS' ? '全平台视角' : '本租户视角' }}
        </el-tag>
      </div>

      <div class="rr-stats">
        <div v-for="s in statCards" :key="s.key" class="rr-stat" :class="'is-' + s.tone">
          <div class="rr-stat-num">{{ s.value }}</div>
          <div class="rr-stat-label">{{ s.label }}</div>
        </div>
      </div>

      <div class="rr-toolbar">
        <el-select v-model="query.type" size="small" style="width: 140px" @change="reload">
          <el-option label="全部类型" value="all" />
          <el-option label="数字员工" value="worker" />
          <el-option label="AI 专家" value="expert" />
          <el-option label="专家配置" value="expert_config" />
          <el-option label="权限授权" value="permission_grant" />
        </el-select>
        <el-select v-model="query.status" size="small" style="width: 140px; margin-left: 10px" @change="reload">
          <el-option label="全部状态" value="ALL" />
          <el-option label="待处理" value="PENDING" />
          <el-option label="已通过/生效" value="APPROVED" />
          <el-option label="已驳回" value="REJECTED" />
          <el-option label="已回收" value="REVOKED" />
        </el-select>
        <el-input
          v-model="query.keyword"
          size="small"
          placeholder="搜索名称 / 意见 / 权限码"
          style="width: 220px; margin-left: 10px"
          clearable
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-button size="small" type="primary" style="margin-left: 10px" @click="reload">查询</el-button>
        <el-button size="small" :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon><span style="margin-left: 4px">刷新</span>
        </el-button>
      </div>

      <el-empty v-if="!loading && !items.length" description="暂无审核记录" :image-size="80" />

      <el-table v-else v-loading="loading" :data="items" size="small" border>
        <el-table-column prop="type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTagType(row.type)">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="对象" min-width="190" show-overflow-tooltip />
        <el-table-column prop="tenantId" label="租户" width="70" />
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.auditStatus)" effect="plain">
              {{ statusText(row.auditStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="提交方" width="120">
          <template #default="{ row }">{{ row.createdByName || ('#' + (row.createdBy ?? '—')) }}</template>
        </el-table-column>
        <el-table-column prop="createdAt" label="提交时间" width="150">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="处理方" width="120">
          <template #default="{ row }">{{ row.reviewerName || '—' }}</template>
        </el-table-column>
        <el-table-column prop="reviewedAt" label="处理时间" width="150">
          <template #default="{ row }">{{ fmt(row.reviewedAt) }}</template>
        </el-table-column>
        <el-table-column prop="auditNote" label="意见" min-width="150" show-overflow-tooltip />
      </el-table>

      <div v-if="total > query.size" class="rr-pager">
        <el-pagination
          layout="prev, pager, next, total"
          :total="total"
          :page-size="query.size"
          :current-page="query.page"
          @current-change="onPage"
        />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listReviewRecords, type ReviewRecord } from '@/api/resource'

const items = ref<ReviewRecord[]>([])
const loading = ref(false)
const forbidden = ref(false)
const total = ref(0)
const stats = ref<Record<string, number>>({})
const scope = ref('TENANT')

const query = reactive({ type: 'all', status: 'ALL', keyword: '', page: 1, size: 20 })

/** 统计卡：后端返回的是「当前筛选结果」的分布，故与表格同源，不会自相矛盾。 */
const statCards = computed(() => [
  { key: 'PENDING', label: '待处理', value: stats.value.PENDING || 0, tone: 'pending' },
  { key: 'APPROVED', label: '已通过/生效', value: (stats.value.APPROVED || 0) + (stats.value.ACTIVE || 0), tone: 'ok' },
  { key: 'REJECTED', label: '已驳回', value: stats.value.REJECTED || 0, tone: 'bad' },
  { key: 'REVOKED', label: '已回收', value: stats.value.REVOKED || 0, tone: 'muted' }
])

function typeLabel(t?: string) {
  return (
    {
      worker: '数字员工',
      expert: 'AI 专家',
      expert_config: '专家配置',
      permission_grant: '权限授权'
    } as Record<string, string>
  )[t || ''] || t || '—'
}

function typeTagType(t?: string) {
  return t === 'worker' ? 'primary' : t === 'expert_config' ? 'success' : 'warning'
}

function statusText(s?: string) {
  return (
    {
      PENDING: '待处理',
      APPROVED: '已通过',
      REJECTED: '已驳回',
      ACTIVE: '已生效',
      REVOKED: '已回收'
    }[s || ''] || s || '—'
  )
}

function statusTagType(s?: string) {
  if (s === 'APPROVED' || s === 'ACTIVE') return 'success'
  if (s === 'REJECTED' || s === 'REVOKED') return 'danger'
  if (s === 'PENDING') return 'warning'
  return 'info'
}

function fmt(v?: string) {
  return v ? String(v).replace('T', ' ').slice(0, 16) : '—'
}

function onPage(p: number) {
  query.page = p
  load()
}

function reload() {
  query.page = 1
  load()
}

async function load() {
  loading.value = true
  try {
    const r = await listReviewRecords({ ...query })
    items.value = r.items || []
    total.value = r.total || 0
    stats.value = r.stats || {}
    scope.value = r.scope || 'TENANT'
    forbidden.value = false
  } catch (e: unknown) {
    if ((e as { response?: { status?: number } })?.response?.status === 403) {
      forbidden.value = true
      items.value = []
    } else {
      ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.rr-page {
  padding: 4px;
}
.rr-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.rr-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 16px;
  font-weight: 600;
}
.rr-desc {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  max-width: 780px;
}
.rr-stats {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.rr-stat {
  min-width: 118px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}
.rr-stat-num {
  font-size: 20px;
  font-weight: 600;
  line-height: 1.2;
}
.rr-stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.rr-stat.is-pending .rr-stat-num {
  color: var(--el-color-warning);
}
.rr-stat.is-ok .rr-stat-num {
  color: var(--el-color-success);
}
.rr-stat.is-bad .rr-stat-num {
  color: var(--el-color-danger);
}
.rr-stat.is-muted .rr-stat-num {
  color: var(--el-text-color-secondary);
}
.rr-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  flex-wrap: wrap;
  gap: 0;
}
.rr-pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
