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
        type="info"
        :closable="false"
        show-icon
        title="配置企业微信自建应用凭据（corpId / agentId / corpSecret），保存后用户端即可发起企业微信授权。凭据加密存库，保存后不再回显明文；留空的字段表示保留旧值。"
        style="margin-bottom: 16px"
      />

      <el-form label-width="120px" style="max-width: 560px" v-if="loaded">
        <el-form-item label="连接器">
          <el-select v-model="code" style="width: 260px" @change="load">
            <el-option label="企业微信（wechat_work）" value="wechat_work" />
          </el-select>
        </el-form-item>
        <el-form-item label="CorpID">
          <el-input v-model="form.corpId" :placeholder="view?.corpId || '企业ID（我的企业-企业信息）'" />
        </el-form-item>
        <el-form-item label="AgentId">
          <el-input v-model="form.agentId" :placeholder="view?.agentId || '自建应用 AgentId'" />
        </el-form-item>
        <el-form-item label="CorpSecret">
          <el-input
            v-model="form.corpSecret"
            type="password"
            show-password
            :placeholder="view?.corpSecretSet ? '••••••（已配置，留空保留旧值）' : '自建应用 Secret'"
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
        style="margin-top: 12px; max-width: 560px"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  deleteConnectorTenantConfig,
  getConnectorTenantConfig,
  putConnectorTenantConfig,
  type ConnectorTenantConfigView
} from '@/api/connectorAdmin'

const code = ref('wechat_work')
const view = ref<ConnectorTenantConfigView | null>(null)
const loaded = ref(false)
const saving = ref(false)
const clearing = ref(false)
const form = reactive({ corpId: '', agentId: '', corpSecret: '', enabled: true })

async function load() {
  view.value = await getConnectorTenantConfig(code.value)
  form.enabled = view.value.enabled
  form.corpId = ''
  form.agentId = ''
  form.corpSecret = ''
  loaded.value = true
}

async function save() {
  saving.value = true
  try {
    view.value = await putConnectorTenantConfig(code.value, {
      values: { corpId: form.corpId, agentId: form.agentId, corpSecret: form.corpSecret },
      enabled: form.enabled
    })
    ElMessage.success('已保存（凭据已加密落库）')
    form.corpId = ''
    form.agentId = ''
    form.corpSecret = ''
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
  } finally {
    clearing.value = false
  }
}

onMounted(load)
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
</style>
