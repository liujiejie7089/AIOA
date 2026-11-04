<template>
  <div>
    <!--
      取数失败要把原因显示出来：旧实现在 403 / 后端报错时静默留空表，
      管理员只看到「什么都没有」，无法区分「确实没数据」和「没权限」。
    -->
    <el-alert
      v-if="errorMsg"
      type="error"
      :closable="false"
      show-icon
      :title="errorMsg"
      style="margin-bottom: 12px"
    />

    <!--
      角色与权限点：同一件事的两面（谁能做什么 / 有哪些动作）。
      原先占两条菜单项，用户要在两个页面之间来回跳才能对上号，现合并为一页两页签。
    -->
    <el-card v-if="section === 'auth'" shadow="never">
      <template #header>
        <div class="card-header">
          <span>角色与权限</span>
          <el-button text type="primary" size="small" :loading="loading" @click="loadSection">刷新</el-button>
        </div>
      </template>
      <el-tabs v-model="authTab">
        <el-tab-pane label="角色" name="roles">
          <el-table v-loading="loading" :data="roles" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="roleCode" label="角色编码" min-width="170" />
            <el-table-column label="角色名称" min-width="130">
              <template #default="{ row }">{{ row.roleName || '—' }}</template>
            </el-table-column>
            <el-table-column label="数据范围" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="plain" type="info">{{ row.dataScope || '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="权限简介" min-width="300">
              <template #default="{ row }">{{ dataScopeText(row.dataScope) }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无角色数据" :image-size="60" />
            </template>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="权限点" name="permissions">
          <el-table v-loading="loading" :data="permissions" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="permCode" label="权限编码" min-width="220" />
            <el-table-column label="权限名称" min-width="200">
              <template #default="{ row }">{{ row.permName || '—' }}</template>
            </el-table-column>
            <el-table-column prop="type" label="类型" width="100" />
            <template #empty>
              <el-empty description="暂无权限点数据" :image-size="60" />
            </template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 功能管理：模块开关与可见范围 -->
    <el-card v-if="section === 'apps'" shadow="never">
      <template #header>
        <div class="card-header">
          <span>功能管理</span>
          <el-button text type="primary" size="small" :loading="loading" @click="loadApps">刷新</el-button>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="启用/禁用与可见范围保存后立即生效：禁用的模块从用户端「我的应用」隐藏；「仅管理员」模块对普通用户不可见。"
        style="margin-bottom: 10px"
      />
      <el-table v-loading="loading" :data="apps" stripe>
        <el-table-column prop="appCode" label="模块编码" width="120" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v: boolean) => saveApp(row, { enabled: v })" />
          </template>
        </el-table-column>
        <el-table-column label="可见范围" width="160">
          <template #default="{ row }">
            <el-select
              :model-value="row.visibleScope || 'ALL'"
              size="small"
              @change="(v: 'ALL' | 'ADMIN') => saveApp(row, { visibleScope: v })"
            >
              <el-option label="所有人" value="ALL" />
              <el-option label="仅管理员" value="ADMIN" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column prop="hostType" label="类型" width="100" />
        <template #empty>
          <el-empty description="暂无功能模块" :image-size="60" />
        </template>
      </el-table>
    </el-card>

    <!-- 模型管理：大模型接入配置 -->
    <el-card v-if="section === 'models'" shadow="never">
      <template #header>
        <div class="card-header">
          <span>模型管理</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="loadModels">刷新</el-button>
            <el-button text type="primary" size="small" :loading="syncing" @click="doSync">同步到模型服务</el-button>
            <el-button text type="primary" size="small" @click="openHistory">配置历史 / 回滚</el-button>
            <el-button type="primary" size="small" @click="openModelDialog()">新增模型</el-button>
          </div>
        </div>
      </template>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="保存/切换默认后自动推送 agent 热加载，无需重启即可生效。默认模型即用户端会话的默认路由。「启动」会先做连通性校验，不通过则保持停用并给出原因。"
        style="margin-bottom: 10px"
      />
      <el-alert
        v-if="keyEncryptionWeak"
        type="warning"
        :closable="false"
        show-icon
        title="未配置 AIOS_MODEL_KEY_ENC_KEY / AIOS_GITEE_TOKEN_ENC_KEY，管理端填写的 API Key 使用内置开发密钥加密（弱保护）。生产环境请在服务端环境变量配置其中之一。"
        style="margin-bottom: 10px"
      />
      <el-table v-loading="loading" :data="models" stripe>
        <el-table-column prop="providerKey" label="标识" width="110" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="modelName" label="模型" min-width="150" />
        <el-table-column prop="baseUrl" label="接入地址" min-width="220" show-overflow-tooltip />
        <el-table-column label="默认" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.isDefault" type="success" effect="plain" size="small">默认</el-tag>
            <el-button v-else text type="primary" size="small" @click="makeDefault(row)">设默认</el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain" size="small">
              {{ row.enabled ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="热更新" width="90">
          <template #default="{ row }">
            <el-tag :type="row.syncState === 'PENDING' ? 'warning' : 'success'" effect="plain" size="small">
              {{ row.syncState === 'PENDING' ? '待同步' : '已生效' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="密钥" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{
              row.apiKeyMasked || (row.apiKeySource === 'ENV' ? '已配置（环境变量）' : '未配置')
            }}</span>
            <el-tag
              size="small"
              effect="plain"
              :type="row.apiKeySource === 'NONE' ? 'danger' : 'info'"
              style="margin-left: 4px"
            >
              {{ row.apiKeySource === 'DB' ? '管理端填写' : row.apiKeySource === 'ENV' ? '环境变量' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button
              text
              size="small"
              :type="row.enabled ? 'warning' : 'success'"
              :loading="modelChecking === row.providerKey"
              @click="toggleModel(row, !row.enabled)"
            >
              {{ row.enabled ? '停用' : '启动' }}
            </el-button>
            <el-button
              text
              type="primary"
              size="small"
              :loading="modelChecking === row.providerKey"
              @click="checkModel(row)"
            >
              校验
            </el-button>
            <el-button text type="primary" size="small" @click="openModelDialog(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="removeModel(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无模型配置" :image-size="60" />
        </template>
      </el-table>
    </el-card>

    <!-- 模型弹窗 -->
    <el-dialog v-model="modelDialog.visible" :title="modelDialog.form.id ? '编辑模型' : '新增模型'" width="580px">
      <el-form label-position="top">
        <el-form-item label="大模型类型">
          <el-select v-model="modelDialog.form.providerType" style="width: 100%" @change="applyPreset">
            <el-option v-for="p in modelPresets" :key="p.type" :value="p.type" :label="p.label" />
          </el-select>
          <div style="color: var(--el-text-color-secondary); font-size: 12px">
            选中后自动带出该厂商的接入地址 / 模型标识名 / 密钥环境变量名，仍可手工修改。
          </div>
        </el-form-item>
        <el-form-item label="模型标识（唯一，如 minimax）">
          <el-input v-model="modelDialog.form.providerKey" :disabled="!!modelDialog.form.id" />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="modelDialog.form.name" />
        </el-form-item>
        <el-form-item label="API Base URL">
          <el-input v-model="modelDialog.form.baseUrl" placeholder="https://api.minimax.chat/v1" />
        </el-form-item>
        <el-form-item label="模型标识名（请求体 model）">
          <el-select
            v-model="modelDialog.form.modelName"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            placeholder="MiniMax-M3.1-Flash"
          >
            <el-option v-for="m in presetModels" :key="m" :value="m" :label="m" />
          </el-select>
          <div style="color: var(--el-text-color-secondary); font-size: 12px">
            厂家发布新模型时，这里直接改成新名字即可调用（可手输任意模型名），无需改代码或重启。
          </div>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="modelDialog.form.apiKey"
            type="password"
            show-password
            placeholder="留空则只用环境变量；原样保存掩码表示不修改"
          />
          <div style="color: var(--el-text-color-secondary); font-size: 12px">
            加密后存库，列表只回显掩码；明文仅在内网推送给 agent，不会返回给浏览器。
          </div>
        </el-form-item>
        <el-form-item label="密钥环境变量名">
          <el-input v-model="modelDialog.form.apiKeyEnv" placeholder="MINIMAX_API_KEY" />
        </el-form-item>
        <el-form-item label="温度 temperature（0~2，越低越确定）">
          <el-slider
            v-model="modelDialog.form.temperature"
            :min="0"
            :max="2"
            :step="0.05"
            show-input
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="核采样 top_p（0~1，留空 = 不下发，沿用供应商默认）">
          <el-input-number
            v-model="modelDialog.form.topP"
            :min="0"
            :max="1"
            :step="0.05"
            :precision="2"
            placeholder="不下发"
            style="width: 200px"
          />
        </el-form-item>
        <el-form-item label="单次输出上限 max_tokens（0 = 不下发）">
          <el-input-number v-model="modelDialog.form.maxTokens" :min="0" :max="65536" :step="256" />
        </el-form-item>
        <el-form-item label="话题新颖度惩罚 presence_penalty（-2~2）">
          <el-input-number
            v-model="modelDialog.form.presencePenalty"
            :min="-2"
            :max="2"
            :step="0.1"
            :precision="2"
          />
        </el-form-item>
        <el-form-item label="词频惩罚 frequency_penalty（-2~2，抑制复读）">
          <el-input-number
            v-model="modelDialog.form.frequencyPenalty"
            :min="-2"
            :max="2"
            :step="0.1"
            :precision="2"
          />
        </el-form-item>
        <el-form-item label="最大上下文长度（token，0 表示不限制）">
          <el-input-number v-model="modelDialog.form.maxContext" :min="0" :max="1048576" :step="1024" />
        </el-form-item>
        <el-form-item label="请求超时（秒，5~600）">
          <el-input-number v-model="modelDialog.form.timeoutSeconds" :min="5" :max="600" :step="5" />
        </el-form-item>
        <el-form-item label="重试次数（含首次，1~5；仅对可重试错误生效）">
          <el-input-number v-model="modelDialog.form.retryAttempts" :min="1" :max="5" :step="1" />
        </el-form-item>
        <el-form-item label="流式输出">
          <el-switch v-model="modelDialog.form.streamEnabled" />
          <span style="margin-left: 8px; color: var(--el-text-color-secondary); font-size: 12px">
            关掉后走非流式补全（兼容不支持 SSE 的网关），首字延迟会变高
          </span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="modelDialog.form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="modelDialog.saving" @click="saveModelForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 配置历史 / 回滚：每次写操作前留快照，整表替换后立即热更新 -->
    <el-dialog v-model="historyDialog.visible" title="配置历史 / 一键回滚" width="600px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="每次保存 / 启停 / 删除前都会留一份全量快照。回滚会用所选快照整体替换当前配置，并立即推送给模型服务；回滚前也会为当前状态留一份快照，本身可再撤回。"
      />
      <el-table
        v-loading="historyDialog.loading"
        :data="historyDialog.rows"
        size="small"
        style="margin-top: 10px"
      >
        <el-table-column prop="id" label="#" width="70" />
        <el-table-column label="动作" width="110">
          <template #default="{ row }">{{ reasonText(row.reason) }}</template>
        </el-table-column>
        <el-table-column prop="total" label="模型数" width="90" />
        <el-table-column prop="createdAt" label="时间" min-width="170" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="doRollback(row)">回滚</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无历史版本" :image-size="60" />
        </template>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 平台级基线配置（权限与安全 → 角色 / 权限点；系统配置 → 功能管理 / 模型管理）。
 *
 * <p>这四个子项原本都堆在「人员管理」页里 —— 它们管的是**平台级基线数据与系统配置**
 * （角色字典 / 模块开关 / 大模型接入 / 权限字典），与「员工与账号」没有从属关系。
 * 混在人员页里既让人员页臃肿，也让「模型管理」这类高频配置被埋在页面底部找不着。
 * 现将它们按功能域拆到两个组，各自有独立路由与面包屑。</p>
 *
 * <p>三个路由共用本组件，按 `route.meta.section` 决定渲染哪一块：
 * 「权限与安全 → 角色与权限」（section=auth，页签内含角色 / 权限点两块字典）与
 * 「系统配置 → 功能管理 / 模型管理」（section=apps / models）。
 * 表格 / 接口 / 权限判断全部沿用原实现，只换了承载位置，行为零变化。</p>
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteModel,
  listAllApps,
  listModelHistory,
  listModelPresets,
  listModels,
  listPermissions,
  listRoles,
  rollbackModel,
  saveModel,
  setDefaultModel,
  setModelStatus,
  syncModels,
  testModel,
  updateApp,
  type AppItem,
  type ModelCheckResult,
  type ModelConfigHistoryItem,
  type ModelItem,
  type ModelPreset,
  type SysPermission,
  type SysRole,
} from '@/api/resource'
// 「数据范围 → 一句话简介」的唯一常量入口（铁律 #4：常量只有一个入口）
import { dataScopeText } from '@/constants/permissions'

type Section = 'auth' | 'apps' | 'models'

const route = useRoute()
const section = computed<Section>(() => (route.meta.section as Section) || 'auth')
/** 角色 / 权限点合并成一页后，用页签切换两块表格（默认落在「角色」）。 */
const authTab = ref<'roles' | 'permissions'>('roles')

const loading = ref(false)
const errorMsg = ref('')

/** 与 AdminView 同口径：后端业务失败是 HTTP 200 + code≠0，鉴权失败才是 403/404。 */
function apiError(e: unknown, fallback: string): string {
  const resp = (e as { response?: { status?: number; data?: { message?: string } } })?.response
  if (resp?.data?.message) return resp.data.message
  if (resp?.status === 403) return '当前账号无权查看该配置'
  return (e as { message?: string })?.message || fallback
}

// ---------- 角色 / 权限点（只读字典） ----------
const roles = ref<SysRole[]>([])
const permissions = ref<SysPermission[]>([])

async function loadRoles() {
  loading.value = true
  errorMsg.value = ''
  try {
    roles.value = (await listRoles()) || []
  } catch (e) {
    roles.value = []
    errorMsg.value = apiError(e, '角色列表加载失败')
  } finally {
    loading.value = false
  }
}

async function loadPermissions() {
  loading.value = true
  errorMsg.value = ''
  try {
    permissions.value = (await listPermissions()) || []
  } catch (e) {
    permissions.value = []
    errorMsg.value = apiError(e, '权限点列表加载失败')
  } finally {
    loading.value = false
  }
}

// ---------- 功能管理 ----------
const apps = ref<AppItem[]>([])

async function loadApps() {
  loading.value = true
  errorMsg.value = ''
  try {
    apps.value = (await listAllApps()) || []
  } catch (e) {
    apps.value = []
    errorMsg.value = apiError(e, '功能模块加载失败')
  } finally {
    loading.value = false
  }
}

async function saveApp(row: AppItem, patch: { enabled?: boolean; visibleScope?: 'ALL' | 'ADMIN' }) {
  try {
    const updated = await updateApp(row.appCode, patch)
    Object.assign(row, updated)
    ElMessage.success(`「${row.name}」配置已保存并即时生效`)
  } catch (e) {
    ElMessage.error(apiError(e, '保存失败'))
  }
}

// ---------- 模型管理 ----------
const models = ref<ModelItem[]>([])
const modelPresets = ref<ModelPreset[]>([])
const keyEncryptionWeak = ref(false)
const modelChecking = ref('')
const syncing = ref(false)
const modelDialog = reactive({
  visible: false,
  saving: false,
  form: {
    id: 0,
    providerKey: '',
    providerType: 'minimax',
    name: '',
    baseUrl: '',
    modelName: '',
    apiKeyEnv: '',
    apiKey: '',
    temperature: 0.3 as number,
    topP: null as number | null,
    maxTokens: 0 as number,
    presencePenalty: 0 as number,
    frequencyPenalty: 0 as number,
    maxContext: 0 as number,
    timeoutSeconds: 120 as number,
    retryAttempts: 3 as number,
    streamEnabled: true,
    enabled: true,
  },
})

const historyDialog = reactive({
  visible: false,
  loading: false,
  rows: [] as ModelConfigHistoryItem[],
})

/** 当前所选厂商的常用模型名候选（厂家发新模型时改名字即可调用） */
const presetModels = computed(
  () => modelPresets.value.find((p) => p.type === modelDialog.form.providerType)?.models || [],
)

function reasonText(reason: string): string {
  const map: Record<string, string> = {
    SAVE: '保存',
    DELETE: '删除',
    STATUS: '启停',
    DEFAULT: '设默认',
    ROLLBACK: '回滚',
  }
  return map[reason] || reason
}

async function loadModels() {
  loading.value = true
  errorMsg.value = ''
  try {
    models.value = (await listModels()) || []
    const presetResp = await listModelPresets()
    modelPresets.value = presetResp?.presets || []
    keyEncryptionWeak.value = !!presetResp?.keyEncryptionWeak
  } catch (e) {
    models.value = []
    errorMsg.value = apiError(e, '模型列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 选择大模型类型后自动带出该厂商的接入地址 / 模型名 / 密钥环境变量名。 */
function applyPreset() {
  const preset = modelPresets.value.find((p) => p.type === modelDialog.form.providerType)
  if (!preset) return
  if (!modelDialog.form.id) {
    if (!modelDialog.form.providerKey) modelDialog.form.providerKey = preset.type
    if (!modelDialog.form.name) modelDialog.form.name = preset.label
  }
  modelDialog.form.baseUrl = preset.baseUrl
  modelDialog.form.modelName = preset.defaultModel
  modelDialog.form.apiKeyEnv = preset.apiKeyEnv
  modelDialog.form.temperature = preset.temperature
  modelDialog.form.maxContext = preset.maxContext
}

function openModelDialog(row?: ModelItem) {
  if (row) {
    modelDialog.form = {
      id: row.id,
      providerKey: row.providerKey,
      providerType: row.providerType || (row.providerKey === 'echo' ? 'echo' : 'custom'),
      name: row.name,
      baseUrl: row.baseUrl,
      modelName: row.modelName,
      apiKeyEnv: row.apiKeyEnv,
      // 库里的明文永远不下发到前端：这里回显的是掩码，原样保存即表示「不修改密钥」
      apiKey: row.apiKeyMasked || '',
      temperature: row.temperature ?? 0.3,
      topP: row.topP ?? null,
      maxTokens: row.maxTokens ?? 0,
      presencePenalty: row.presencePenalty ?? 0,
      frequencyPenalty: row.frequencyPenalty ?? 0,
      maxContext: row.maxContext ?? 0,
      timeoutSeconds: row.timeoutSeconds ?? 120,
      retryAttempts: row.retryAttempts ?? 3,
      streamEnabled: row.streamEnabled ?? true,
      enabled: !!row.enabled,
    }
  } else {
    modelDialog.form = {
      id: 0,
      providerKey: '',
      providerType: 'minimax',
      name: '',
      baseUrl: '',
      modelName: '',
      apiKeyEnv: '',
      apiKey: '',
      temperature: 0.3,
      topP: null,
      maxTokens: 0,
      presencePenalty: 0,
      frequencyPenalty: 0,
      maxContext: 0,
      timeoutSeconds: 120,
      retryAttempts: 3,
      streamEnabled: true,
      enabled: true,
    }
    applyPreset()
  }
  modelDialog.visible = true
}

/** 配置历史：每次写操作前的全量快照，用于一键回滚 */
async function openHistory() {
  historyDialog.visible = true
  historyDialog.loading = true
  try {
    historyDialog.rows = (await listModelHistory()) || []
  } catch (e) {
    historyDialog.rows = []
    ElMessage.error(apiError(e, '历史版本加载失败'))
  } finally {
    historyDialog.loading = false
  }
}

async function doRollback(row: ModelConfigHistoryItem) {
  try {
    await ElMessageBox.confirm(
      `将把当前模型配置整体替换为「#${row.id} · ${reasonText(row.reason)} · ${row.total} 个模型」这一版，并立即生效。是否继续？`,
      '回滚确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await rollbackModel(row.id)
    ElMessage.success(
      res?.synced
        ? `已回滚到 #${row.id}（${res.restored} 个模型），已热更新生效`
        : `已回滚到 #${row.id}（${res?.restored ?? 0} 个模型），但未同步到模型服务，请点「同步到模型服务」重试`,
    )
    historyDialog.visible = false
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '回滚失败'))
  }
}

async function doSync() {
  syncing.value = true
  try {
    const res = await syncModels()
    if (res?.synced) ElMessage.success(`已同步 ${res.total} 个模型到模型服务，立即生效`)
    else ElMessage.warning('同步未确认成功：模型服务可能不可达，请检查后重试')
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '同步失败'))
  } finally {
    syncing.value = false
  }
}

async function saveModelForm() {
  modelDialog.saving = true
  try {
    const saved = await saveModel({ ...modelDialog.form })
    // 后端会回执是否真的热更新到 agent：落库成功但推送失败时不能报「已生效」
    if (saved?.syncState === 'PENDING') {
      ElMessage.warning('配置已保存，但未同步到模型服务（agent 可能离线）。请稍后点「同步到模型服务」。')
    } else {
      ElMessage.success('模型配置已保存并推送 agent 热加载，立即生效')
    }
    modelDialog.visible = false
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '保存失败'))
  } finally {
    modelDialog.saving = false
  }
}

async function makeDefault(row: ModelItem) {
  try {
    await setDefaultModel(row.providerKey)
    ElMessage.success(`默认模型已切换为「${row.name}」，立即生效`)
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '操作失败'))
  }
}

/** 启动 / 停用：启动时后端先做连通性校验，不通过会把原因抛回来（模型保持停用）。 */
async function toggleModel(row: ModelItem, enabled: boolean) {
  modelChecking.value = row.providerKey
  try {
    const res = await setModelStatus(row.providerKey, enabled)
    ElMessage.success(res?.message || (enabled ? '已启用' : '已停用'))
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, enabled ? '启用失败' : '停用失败'))
    await loadModels()
  } finally {
    modelChecking.value = ''
  }
}

/** 只做连通性校验，不改启用状态。 */
async function checkModel(row: ModelItem) {
  modelChecking.value = row.providerKey
  try {
    const res: ModelCheckResult = await testModel(row.providerKey)
    if (res?.ok) {
      ElMessage.success(res.message || '连通性校验通过')
    } else {
      ElMessage.warning(res?.message || '连通性校验未通过')
    }
  } catch (e) {
    ElMessage.error(apiError(e, '校验失败'))
  } finally {
    modelChecking.value = ''
  }
}

async function removeModel(row: ModelItem) {
  try {
    await ElMessageBox.confirm(`确认删除模型「${row.name}」？`, '删除确认', { type: 'warning' })
    await deleteModel(row.providerKey)
    ElMessage.success('已删除')
    await loadModels()
  } catch (e) {
    if ((e as string) !== 'cancel') ElMessage.error(apiError(e, '删除失败'))
  }
}

/** 只拉当前菜单项要用的那一块，别为看不见的页签发请求。 */
function loadSection() {
  switch (section.value) {
    // 角色与权限点合并成一页：两块字典都要拉，页签切换是纯前端行为
    case 'auth':
      return Promise.all([loadRoles(), loadPermissions()])
    case 'apps':
      return loadApps()
    case 'models':
      return loadModels()
  }
}

// 四个路由共用同一个组件实例，onMounted 不会再触发，必须靠 watch 重新取数
watch(section, loadSection)
onMounted(loadSection)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
