<template>
  <div>
    <div class="toolbar">
      <el-radio-group v-model="status" size="small">
        <el-radio-button v-for="opt in STATUS_OPTIONS" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </el-radio-button>
      </el-radio-group>
      <span class="count">共 {{ rows.length }} 条</span>
    </div>

    <el-table :data="rows" border size="small" style="width: 100%">
      <el-table-column prop="id" label="工单号" width="140" />
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="assignee" label="处理人" width="100" />
      <el-table-column prop="createdAt" label="创建时间" width="150" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="goDetail(row.id)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { STATUS_LABEL, STATUS_OPTIONS, TICKETS, type TicketStatus } from '@/data/tickets'
import { getBridge, REFRESH_EVENT } from '@/aioa'

const router = useRouter()
const status = ref<TicketStatus | 'ALL'>('ALL')
const version = ref(0)

const rows = computed(() => {
  void version.value
  return status.value === 'ALL' ? TICKETS : TICKETS.filter((item) => item.status === status.value)
})

function statusLabel(value: TicketStatus): string {
  return STATUS_LABEL[value]
}

function statusType(value: TicketStatus): 'info' | 'primary' | 'success' {
  if (value === 'OPEN') return 'info'
  if (value === 'PROCESSING') return 'primary'
  return 'success'
}

function goDetail(id: string) {
  void router.push(`/detail/${id}`)
}

/** 上报上下文：页面切换与筛选变化时都调用 */
function reportContext() {
  getBridge().setContext({
    page: 'ticket-list',
    pageTitle: '工单列表',
    entityType: 'ticket',
    entityId: undefined,
    filters: { status: status.value, count: rows.value.length },
    selection: []
  })
}

function onRefresh() {
  version.value += 1
  reportContext()
}

onMounted(() => {
  reportContext()
  window.addEventListener(REFRESH_EVENT, onRefresh)
})

onUnmounted(() => {
  window.removeEventListener(REFRESH_EVENT, onRefresh)
})

// 筛选条件变化时重新上报上下文
watch(status, () => reportContext())
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.count {
  font-size: 12px;
  color: #909399;
}
</style>
