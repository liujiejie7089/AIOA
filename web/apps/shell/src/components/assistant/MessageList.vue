<template>
  <div ref="scroller" class="msg-list">
    <el-empty v-if="!assistant.messages.length" description="有什么可以帮你？" :image-size="80" />
    <div
      v-for="msg in assistant.messages"
      :key="msg.id"
      class="msg-row"
      :class="msg.role === 'user' ? 'is-user' : 'is-ai'"
    >
      <el-avatar :size="26" class="msg-avatar">
        {{ msg.role === 'user' ? '我' : 'AI' }}
      </el-avatar>
      <div class="msg-body">
        <div class="msg-bubble" :class="{ 'is-error': msg.error }">
          <span class="msg-text">{{ msg.content }}</span>
          <span v-if="isStreamingTail(msg)" class="msg-caret" />
        </div>
        <div v-if="msg.createdAt" class="msg-time">{{ formatTime(msg.createdAt) }}</div>
      </div>
    </div>
    <div v-if="assistant.error" class="msg-error">
      <el-alert type="error" :title="assistant.error" :closable="false" show-icon />
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import dayjs from 'dayjs'
import { useAssistantStore } from '@/stores/assistant'
import type { ChatMessage } from '@/types'

const assistant = useAssistantStore()
const scroller = ref<HTMLElement | null>(null)

function formatTime(value: string): string {
  return dayjs(value).format('MM-DD HH:mm')
}

function isStreamingTail(msg: ChatMessage): boolean {
  return assistant.streaming && msg.role === 'assistant' && msg.id === assistant.messages[assistant.messages.length - 1]?.id
}

watch(
  () => [assistant.messages.length, assistant.messages[assistant.messages.length - 1]?.content],
  () => {
    void nextTick(() => {
      if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
    })
  }
)
</script>

<style scoped>
.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.msg-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.msg-row.is-user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex: 0 0 26px;
  font-size: 12px;
}

.msg-body {
  display: flex;
  flex-direction: column;
  max-width: 76%;
}

.msg-row.is-user .msg-body {
  align-items: flex-end;
}

.msg-bubble {
  padding: 8px 10px;
  border-radius: 6px;
  background: #f4f4f5;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-row.is-user .msg-bubble {
  background: var(--aioa-primary);
  color: #fff;
}

.msg-bubble.is-error {
  background: #fef0f0;
  color: #f56c6c;
}

.msg-caret {
  display: inline-block;
  width: 2px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--aioa-primary);
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.msg-time {
  margin-top: 4px;
  font-size: 11px;
  color: #c0c4cc;
}

.msg-error {
  margin-bottom: 12px;
}
</style>
