<template>
  <div v-if="ticket">
    <div class="crumb">
      <el-button link type="primary" size="small" @click="back">← 返回工单列表</el-button>
    </div>

    <el-descriptions :title="ticket.id" :column="2" border size="small">
      <el-descriptions-item label="标题" :span="2">{{ ticket.title }}</el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag size="small" :type="statusType">{{ STATUS_LABEL[ticket.status] }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="优先级">{{ ticket.priority }}</el-descriptions-item>
      <el-descriptions-item label="处理人">{{ ticket.assignee }}</el-descriptions-item>
      <el-descriptions-item label="来源渠道">{{ ticket.channel }}</el-descriptions-item>
      <el-descriptions-item label="创建时间" :span="2">{{ ticket.createdAt }}</el-descriptions-item>
      <el-descriptions-item label="问题描述" :span="2">{{ ticket.description }}</el-descriptions-item>
    </el-descriptions>

    <el-card shadow="never" class="tip">
      <span class="tip-text">
        当前上下文已上报给工作台：entityType=ticket，entityId={{ ticket.id }}。可在右侧 AI 助手中直接提问。
      </span>
      <el-button size="small" type="primary" @click="onAsk">问 AI</el-button>
    </el-card>
  </div>
  <el-empty v-else description="工单不存在" />
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { findTicket, STATUS_LABEL } from '@/data/tickets'
import { getBridge } from '@/aioa'

const route = useRoute()
const router = useRouter()

const id = computed(() => String(route.params.id || ''))
const ticket = computed(() => findTicket(id.value))
const statusType = computed<'info' | 'primary' | 'success'>(() => {
  const value = ticket.value?.status
  if (value === 'OPEN') return 'info'
  if (value === 'PROCESSING') return 'primary'
  return 'success'
})

function reportContext() {
  if (!id.value) return
  getBridge().setContext({
    page: 'ticket-detail',
    pageTitle: `工单详情 ${id.value}`,
    entityType: 'ticket',
    entityId: id.value,
    filters: undefined,
    selection: [id.value]
  })
}

function back() {
  void router.push('/list')
}

function onAsk() {
  getBridge().openAssistant({ preset: `帮我总结工单 ${id.value} 的处理进展` })
}

onMounted(reportContext)
watch(id, reportContext)
</script>

<style scoped>
.crumb {
  margin-bottom: 10px;
}

.tip {
  margin-top: 12px;
}

.tip :deep(.el-card__body) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.tip-text {
  font-size: 12px;
  color: #606266;
}
</style>
