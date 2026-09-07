<template>
  <div class="ctx-bar">
    <template v-if="ctx">
      <el-tag size="small" type="primary" effect="light">{{ ctx.appCode || '-' }}</el-tag>
      <el-tag size="small" type="info" effect="plain">{{ ctx.page || '-' }}</el-tag>
      <el-tag v-if="ctx.entityType" size="small" effect="plain">
        {{ ctx.entityType }}: {{ ctx.entityId || '-' }}
      </el-tag>
      <span class="ctx-title" :title="ctx.pageTitle">{{ ctx.pageTitle || '' }}</span>
    </template>
    <span v-else class="ctx-empty">未在子应用中</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAssistantStore } from '@/stores/assistant'

const assistant = useAssistantStore()
const ctx = computed(() => assistant.currentContext)
</script>

<style scoped>
.ctx-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--aioa-border);
  background: #fafafa;
}

.ctx-title {
  font-size: 12px;
  color: var(--aioa-text-sub);
  max-width: 180px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ctx-empty {
  font-size: 12px;
  color: var(--aioa-text-sub);
}
</style>
