<template>
  <div class="review-page">
    <el-alert
      v-if="forbidden"
      type="warning"
      :closable="false"
      show-icon
      title="内容审核仅平台管理员可访问"
      description="当前账号不是平台管理员；租户管理员创建的内容由其上一级审核。"
    />

    <template v-else>
      <div class="review-head">
        <div>
          <div class="review-title">
            <el-icon><Stamp /></el-icon>
            <span>内容审核</span>
          </div>
          <p class="review-desc">
            租户管理员创建的数字员工 / 专家需经平台管理员审核通过后，才对机构成员可见并可运行。
            驳回必须填写意见，便于创建者据此修改。
          </p>
        </div>
        <el-tag :type="switchOn ? 'success' : 'info'" size="small">
          审核开关：{{ switchOn ? '已开启' : '已关闭' }}
        </el-tag>
      </div>

      <div class="review-toolbar">
        <el-radio-group v-model="status" size="small" @change="load">
          <el-radio-button value="PENDING">待审核</el-radio-button>
          <el-radio-button value="APPROVED">已通过</el-radio-button>
          <el-radio-button value="REJECTED">已驳回</el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="loading" @click="load" style="margin-left: auto">
          <el-icon><Refresh /></el-icon><span style="margin-left: 4px">刷新</span>
        </el-button>
      </div>

      <el-empty v-if="!loading && !items.length" :description="statusLabel + '（暂无）'" :image-size="80" />

      <el-table v-else v-loading="loading" :data="items" size="small" border>
        <el-table-column prop="type" label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.type === 'worker' ? 'primary' : 'warning'">
              {{ row.type === 'worker' ? '数字员工' : '专家' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="tenantId" label="租户" width="80" />
        <el-table-column prop="summary" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column prop="createdAt" label="创建时间" width="160">
          <template #default="{ row }">{{ fmt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column prop="auditNote" label="审核意见" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <template v-if="row.auditStatus === 'PENDING'">
              <el-button text type="success" size="small" @click="doReview(row, true)">通过</el-button>
              <el-button text type="danger" size="small" @click="doReview(row, false)">驳回</el-button>
            </template>
            <span v-else class="muted">{{ row.auditStatus === 'APPROVED' ? '已通过' : '已驳回' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listContentReviews, reviewContent, type ContentReviewItem } from '@/api/resource'

const items = ref<ContentReviewItem[]>([])
const loading = ref(false)
const forbidden = ref(false)
const status = ref('PENDING')
const switchOn = ref(true)

const statusLabel = computed(
  () => ({ PENDING: '待审核', APPROVED: '已通过', REJECTED: '已驳回' })[status.value] || status.value
)

function fmt(v?: string) {
  return v ? String(v).replace('T', ' ').slice(0, 16) : '—'
}

async function load() {
  loading.value = true
  try {
    const r = await listContentReviews(status.value)
    items.value = r.items || []
    switchOn.value = r.switchOn !== false
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

async function doReview(row: ContentReviewItem, approve: boolean) {
  // 驳回强制填意见：没有理由的驳回会让租户管理员反复试错
  let note = ''
  if (!approve) {
    try {
      const { value } = await ElMessageBox.prompt('请填写驳回理由（将回显给创建者）', '驳回', {
        inputPattern: /\S+/,
        inputErrorMessage: '驳回理由不能为空',
        confirmButtonText: '确认驳回',
        cancelButtonText: '取消'
      })
      note = String(value || '').trim()
    } catch {
      return
    }
  }
  try {
    await reviewContent(row.type, row.id, approve, note || undefined)
    ElMessage.success(approve ? '已通过，内容对成员生效' : '已驳回')
    await load()
  } catch (e: unknown) {
    ElMessage.error('操作失败：' + ((e as Error)?.message || '后端异常'))
  }
}

onMounted(load)
</script>

<style scoped>
.review-page {
  padding: 4px;
}
.review-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.review-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 16px;
  font-weight: 600;
}
.review-desc {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  max-width: 720px;
}
.review-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
