<template>
  <el-drawer
    v-model="visible"
    :size="assistant.expanded ? '640px' : '420px'"
    direction="rtl"
    :modal="false"
    :with-header="true"
    class="assistant-drawer"
  >
    <template #header>
      <div class="ad-header">
        <span class="ad-title">
          <el-icon><ChatDotRound /></el-icon>
          <span style="margin-left: 6px">AI 助手</span>
        </span>
        <el-button text size="small" @click="assistant.toggleExpanded()">
          <el-icon>
            <ZoomIn v-if="!assistant.expanded" />
            <ZoomOut v-else />
          </el-icon>
        </el-button>
      </div>
    </template>

    <div class="ad-wrap">
      <ContextBar />
      <ConversationList />
      <MessageList />
      <div class="ad-input">
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          resize="none"
          placeholder="输入问题，Enter 发送，Ctrl+Enter 换行"
          @keydown.enter.exact.prevent="onSend"
        />
        <div class="ad-actions">
          <span class="ad-hint">全链路真实调用 · 支持工具调用与计量</span>
          <div>
            <el-button v-if="assistant.streaming" type="danger" size="small" @click="onStop">停止</el-button>
            <el-button v-else type="primary" size="small" :disabled="!draft.trim()" @click="onSend">发送</el-button>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ContextBar from './ContextBar.vue'
import ConversationList from './ConversationList.vue'
import MessageList from './MessageList.vue'
import { useAssistantStore } from '@/stores/assistant'

const assistant = useAssistantStore()
const draft = ref('')

const visible = computed({
  get: () => assistant.open,
  set: (value: boolean) => {
    if (value) assistant.openDrawer()
    else assistant.closeDrawer()
  }
})

// 子应用通过 openAssistant({ preset }) 唤起时，把预填问题塞进输入框
watch(
  () => assistant.preset,
  (value) => {
    if (!value) return
    assistant.open = true
    draft.value = value
    assistant.consumePreset()
  }
)

watch(
  () => assistant.open,
  (open) => {
    if (open && !assistant.conversations.length && !assistant.loadingConversations) {
      void assistant.loadConversations()
    }
  }
)

function onSend() {
  const text = draft.value
  if (!text.trim() || assistant.streaming) return
  draft.value = ''
  void assistant.send(text)
}

function onStop() {
  void assistant.stop()
}
</script>

<style scoped>
.ad-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ad-title {
  display: flex;
  align-items: center;
  font-size: 15px;
  font-weight: 600;
}

.ad-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.ad-input {
  border-top: 1px solid var(--aioa-border);
  padding: 8px 12px 10px;
}

.ad-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}

.ad-hint {
  font-size: 11px;
  color: #c0c4cc;
}
</style>
