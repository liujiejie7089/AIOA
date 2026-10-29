<template>
  <div class="connector-config">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>连接器配置（租户级）</span>
          <el-tag v-if="view" :type="view.configReady ? 'success' : 'warning'" effect="plain">
            {{ view.configReady ? '已就绪' : '待配置' }}
          </el-tag>
        </div>
      </template>

      <el-alert
        v-if="view && view.hubAvailable === false"
        type="error"
        :closable="false"
        show-icon
        title="连接器运行时（mcp-hub）不可达：当前只读的是数据库影子记录，保存会失败。请先启动 mcp-hub 并确认 AIOS_MCP_HUB=true。"
        style="margin-bottom: 16px"
      />
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="字段由连接器自身声明（connector_def.config_keys），新增第三方应用无需改前端。凭据加密存库、保存后不再回显明文；留空的字段表示保留旧值。"
        style="margin-bottom: 16px"
      />

      <el-form label-width="150px" style="max-width: 600px" v-if="loaded">
        <el-form-item label="连接器">
          <el-select v-model="code" style="width: 300px" @change="load">
            <el-option
              v-for="item in options"
              :key="item.code"
              :label="`${item.name}（${item.code}）`"
              :value="item.code"
            />
          </el-select>
          <span v-if="current?.authMode" class="mode-tag">{{ current.authMode }}</span>
        </el-form-item>

        <el-form-item v-for="key in keys" :key="key" :label="labelOf(key)">
          <el-input
            v-model="form[key]"
            :type="isSensitive(key) ? 'password' : 'text'"
            :show-password="isSensitive(key)"
            :placeholder="placeholderOf(key)"
          />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button :disabled="!view?.configured" :loading="clearing" @click="clear">清除配置</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="view && !view.configReady"
        type="warning"
        :closable="false"
        show-icon
        :title="'当前就绪状态：' + (view.configHint || '未就绪')"
        style="margin-top: 12px; max-width: 600px"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  deleteConnectorTenantConfig,
  getConnectorTenantConfig,
  listConnectorTenantConfigs,
  putConnectorTenantConfig,
  type ConnectorConfigItem,
  type ConnectorTenantConfigView
} from '@/api/connectorAdmin'

/** 键名 → 中文标签（仅影响展示；未登记的新连接器直接显示键名，不影响保存）。 */
const LABELS: Record<string, string> = {
  corpId: '企业ID（CorpID）',
  agentId: '应用 AgentId',
  corpSecret: '应用 Secret',
  redirectUri: 'OAuth 回调地址',
  apiKey: 'API Key',
  endpoint: '接口地址'
}

const code = ref('')
const options = ref<ConnectorConfigItem[]>([])
const view = ref<ConnectorTenantConfigView | null>(null)
const loaded = ref(false)
const saving = ref(false)
const clearing = ref(false)
const keys = ref<string[]>([])
const form = reactive<Record<string, any>>({ enabled: true })

const current = computed(() => options.value.find((o) => o.code === code.value))
const labelOf = (k: string) => LABELS[k] || k
const isSensitive = (k: string) => view.value?.values?.[`${k}Set`] !== undefined
const placeholderOf = (k: string) => {
  const v = view.value?.values?.[k]
  if (isSensitive(k) && view.value?.values?.[`${k}Set`] === true) return '••••••（已配置，留空保留旧值）'
  return typeof v === 'string' && v ? `当前：${v}` : `填写 ${labelOf(k)}`
}

async function loadList() {
  options.value = await listConnectorTenantConfigs()
  if (!code.value && options.value.length) code.value = options.value[0].code
}

async function load() {
  if (!code.value) return
  view.value = await getConnectorTenantConfig(code.value)
  keys.value = view.value.configKeys || []
  for (const k of keys.value) form[k] = ''
  form.enabled = view.value.enabled
  loaded.value = true
}

async function save() {
  saving.value = true
  try {
    const values: Record<string, string> = {}
    for (const k of keys.value) values[k] = String(form[k] ?? '')
    view.value = await putConnectorTenantConfig(code.value, { values, enabled: form.enabled })
    ElMessage.success('已保存（凭据已加密落库）')
    for (const k of keys.value) form[k] = ''
    await loadList()
  } finally {
    saving.value = false
  }
}

async function clear() {
  clearing.value = true
  try {
    await deleteConnectorTenantConfig(code.value)
    ElMessage.success('已清除，用户端回到「待管理员配置」')
    await load()
    await loadList()
  } finally {
    clearing.value = false
  }
}

onMounted(async () => {
  await loadList()
  await load()
})
</script>

<style scoped>
.connector-config {
  padding: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mode-tag {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
