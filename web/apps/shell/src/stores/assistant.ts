import { defineStore } from 'pinia'
import * as conversationsApi from '@/api/conversations'
import * as runsApi from '@/api/runs'
import type { PageContextSnapshot, ChatMessage, Conversation } from '@/types'
import { useAuthStore } from './auth'

/** 当前 run 的中断控制器（非响应式状态，故放在模块作用域） */
let controller: AbortController | null = null

export const useAssistantStore = defineStore('assistant', {
  state: () => ({
    /** 抽屉是否展开 */
    open: false,
    /** 加宽模式 640px，默认 420px */
    expanded: false,
    conversations: [] as Conversation[],
    currentId: '' as string,
    messages: [] as ChatMessage[],
    streaming: false,
    runId: '' as string,
    error: '' as string,
    /** 子应用通过 SDK 上报的上下文，按 appCode 覆盖 */
    contexts: {} as Record<string, PageContextSnapshot>,
    /** 当前宿主页面所在子应用（来自 /app/:appCode） */
    activeAppCode: '' as string,
    /** 待预填到输入框的问题（AIOA_OPEN_ASSISTANT） */
    preset: '' as string,
    loadingConversations: false,
    loadingMessages: false
  }),
  getters: {
    currentContext(state): PageContextSnapshot | null {
      if (!state.activeAppCode) return null
      return state.contexts[state.activeAppCode] || null
    },
    currentConversation(state): Conversation | null {
      return state.conversations.find((item) => item.id === state.currentId) || null
    }
  },
  actions: {
    openDrawer(preset?: string): void {
      if (preset) this.preset = preset
      this.open = true
    },
    closeDrawer(): void {
      this.open = false
    },
    toggleExpanded(): void {
      this.expanded = !this.expanded
    },
    consumePreset(): string {
      const value = this.preset
      this.preset = ''
      return value
    },
    setActiveApp(appCode: string): void {
      this.activeAppCode = appCode
    },
    setContext(appCode: string, context: PageContextSnapshot): void {
      if (!appCode) return
      this.contexts = { ...this.contexts, [appCode]: { ...this.contexts[appCode], ...context } }
    },

    async loadConversations(): Promise<void> {
      this.loadingConversations = true
      try {
        this.conversations = await conversationsApi.list()
      } catch {
        this.conversations = []
      } finally {
        this.loadingConversations = false
      }
    },

    async loadMessages(): Promise<void> {
      if (!this.currentId) {
        this.messages = []
        return
      }
      this.loadingMessages = true
      try {
        this.messages = await conversationsApi.messages(this.currentId)
      } catch {
        this.messages = []
      } finally {
        this.loadingMessages = false
      }
    },

    async selectConversation(id: string): Promise<void> {
      if (this.streaming) return
      this.currentId = id
      this.error = ''
      await this.loadMessages()
    },

    async newConversation(): Promise<void> {
      if (this.streaming) return
      this.currentId = ''
      this.messages = []
      this.error = ''
      if (!this.conversations.length) await this.loadConversations()
    },

    /** 发送：必要时建会话 → 建 run → 订阅 SSE */
    async send(text: string): Promise<void> {
      const content = text.trim()
      if (!content || this.streaming) return

      let conversationId = this.currentId
      try {
        if (!conversationId) {
          const conversation = await conversationsApi.create(content.slice(0, 20))
          conversationId = conversation.id
          this.currentId = conversationId
          await this.loadConversations()
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : '创建会话失败'
        return
      }

      const now = new Date().toISOString()
      this.messages.push({ id: `u-${Date.now()}`, role: 'user', content, createdAt: now })
      const aiMessage: ChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '',
        createdAt: now
      }
      this.messages.push(aiMessage)
      this.error = ''
      this.streaming = true

      const auth = useAuthStore()
      controller = new AbortController()
      const signal = controller.signal
      try {
        const result = await runsApi.create(conversationId, {
          text: content,
          context: this.currentContext
        })
        this.runId = result.runId
        await runsApi.streamRun({
          runId: result.runId,
          token: auth.token,
          signal,
          handlers: {
            onDelta: (delta) => {
              if (delta) aiMessage.content += delta
            },
            onCompleted: (fullText) => {
              if (fullText != null && fullText !== '') aiMessage.content = fullText
              if (!aiMessage.content) aiMessage.content = '（助手未返回内容）'
            },
            onError: (message) => {
              this.error = message
              aiMessage.error = true
              if (!aiMessage.content) aiMessage.content = `生成失败：${message}`
            }
          }
        })
      } catch (error) {
        if (!signal.aborted) {
          this.error = error instanceof Error ? error.message : '助手请求失败'
          aiMessage.error = true
          if (!aiMessage.content) aiMessage.content = `生成失败：${this.error}`
        }
      } finally {
        this.streaming = false
        this.runId = ''
        controller = null
      }
    },

    /** 停止：中断 SSE 并通知后端取消 run */
    async stop(): Promise<void> {
      if (!this.streaming) return
      const runId = this.runId
      controller?.abort()
      controller = null
      this.streaming = false
      this.runId = ''
      if (runId) {
        try {
          await runsApi.cancel(runId)
        } catch {
          // 取消失败不影响前端中断
        }
      }
    }
  }
})
