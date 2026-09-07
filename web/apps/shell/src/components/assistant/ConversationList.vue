<template>
  <div class="conv">
    <div class="conv-head">
      <span class="conv-label">会话</span>
      <el-button size="small" text type="primary" :disabled="assistant.streaming" @click="onCreate">
        <el-icon><Plus /></el-icon>
        <span style="margin-left: 2px">新建</span>
      </el-button>
    </div>
    <div class="conv-list">
      <el-skeleton v-if="assistant.loadingConversations" :rows="1" animated />
      <template v-else>
        <div
          v-for="item in assistant.conversations"
          :key="item.id"
          class="conv-item"
          :class="{ active: item.id === assistant.currentId }"
          :title="item.title"
          @click="onSelect(item.id)"
        >
          {{ item.title || '未命名会话' }}
        </div>
        <div v-if="!assistant.conversations.length" class="conv-empty">暂无历史会话，发送后自动创建</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useAssistantStore } from '@/stores/assistant'

const assistant = useAssistantStore()

function onSelect(id: string) {
  void assistant.selectConversation(id)
}

function onCreate() {
  void assistant.newConversation()
}
</script>

<style scoped>
.conv {
  border-bottom: 1px solid var(--aioa-border);
  padding: 6px 12px 8px;
}

.conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.conv-label {
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.conv-list {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.conv-item {
  flex: 0 0 auto;
  max-width: 160px;
  padding: 4px 10px;
  font-size: 12px;
  line-height: 20px;
  border: 1px solid var(--aioa-border);
  border-radius: 12px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--aioa-text);
  background: #fff;
}

.conv-item:hover {
  border-color: var(--aioa-primary);
}

.conv-item.active {
  background: var(--aioa-primary);
  border-color: var(--aioa-primary);
  color: #fff;
}

.conv-empty {
  font-size: 12px;
  color: var(--aioa-text-sub);
  padding: 4px 0;
}
</style>
