<template>
  <div class="app-host">
    <el-skeleton v-if="apps.loading && !app" :rows="6" animated style="padding: 16px" />

    <template v-else-if="app && !failed">
      <WujieVue
        v-if="app.hostType === 'wujie'"
        :key="`wujie-${app.appCode}`"
        class="host-wujie"
        :name="app.appCode"
        :url="app.entryUrl"
        :alive="true"
      />
      <iframe
        v-else
        :key="`iframe-${app.appCode}`"
        class="host-frame"
        :src="app.entryUrl"
        :data-app-code="app.appCode"
        frameborder="0"
        @error="failed = true"
      />
    </template>

    <el-result v-else icon="warning" title="子应用加载失败" :sub-title="errorText">
      <template #extra>
        <el-button type="primary" @click="onRetry">重试</el-button>
        <el-button v-if="app?.entryUrl" text>
          <a :href="app.entryUrl" target="_blank" rel="noopener">独立打开</a>
        </el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import WujieVue from 'wujie-vue3'
import { useAppsStore } from '@/stores/apps'
import { useAssistantStore } from '@/stores/assistant'

const route = useRoute()
const apps = useAppsStore()
const assistant = useAssistantStore()

const failed = ref(false)

const appCode = computed(() => String(route.params.appCode || ''))
const app = computed(() => apps.getByCode(appCode.value))

const errorText = computed(() => {
  if (!appCode.value) return '缺少 appCode 参数'
  if (!app.value) return `应用注册表中未找到「${appCode.value}」，请检查后端 apps 接口`
  return `${app.value.appName}（${app.value.hostType}）加载失败，请确认子应用已启动：${app.value.entryUrl}`
})

function onRetry() {
  failed.value = false
  void apps.list(true)
}

watch(
  appCode,
  (value) => {
    failed.value = false
    assistant.setActiveApp(value)
    void apps.list()
  },
  { immediate: true }
)

onMounted(() => {
  assistant.setActiveApp(appCode.value)
})
</script>

<style scoped>
.host-wujie {
  width: 100%;
  height: 100%;
}
</style>
