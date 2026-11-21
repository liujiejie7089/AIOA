<template>
  <div class="connector-config">
    <el-card v-loading="loading">
      <template #header>
        <div class="card-header">
          <div class="card-head-text">
            <span class="card-title">连接器接入（按租户）</span>
            <span class="card-sub">
              外部能力按租户授权启用：启用后本租户用户才可见并调用；停用或改配置立即生效，无需重新登录
            </span>
          </div>
          <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>

      <el-alert
        v-if="loadError"
        type="error"
        :closable="false"
        show-icon
        :title="loadError"
        style="margin-bottom: 16px"
      />

      <div v-for="a in accessList" :key="a.code" class="access-item">
        <div class="access-head">
          <div class="access-name">
            <strong>{{ nameOf(a.code) }}</strong>
            <span class="access-code">{{ a.code }}</span>
          </div>
          <el-tag :type="statusTag(a.status)" effect="plain">{{ statusText(a.status) }}</el-tag>
          <span class="access-switch">
            <span>启用</span>
            <el-switch
              :model-value="a.enabled"
              :loading="!!busy[a.code]"
              @change="(v: boolean) => toggleAccess(a, v)"
            />
          </span>
        </div>

        <div v-if="summaryOf(a.code)" class="access-desc">{{ summaryOf(a.code) }}</div>

        <el-form label-width="110px" class="access-form">
          <el-form-item label="机构白名单">
            <el-select
              v-model="accessForm[a.code].scope"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="留空 = 全租户可用"
              style="width: 100%"
            >
              <el-option
                v-for="i in institutions"
                :key="i.id"
                :label="instLabel(i)"
                :value="i.id"
              />
            </el-select>
            <div class="field-hint">可搜索选择本租户机构（来自机构管理）；按用户主机构判定，留空 = 全租户可用</div>
          </el-form-item>

          <el-form-item label="允许调用用户">
            <el-select
              v-model="accessForm[a.code].users"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="留空 = 不限制"
              style="width: 100%"
            >
              <el-option
                v-for="u in accounts"
                :key="u.userId"
                :label="userLabel(u)"
                :value="u.userId"
              />
            </el-select>
            <div class="field-hint">可搜索选择本租户账号（来自组织成员账号）；留空 = 不限制</div>
          </el-form-item>

          <el-form-item label="数据源地址">
            <el-input
              v-model="accessForm[a.code].baseUrl"
              placeholder="留空 = 使用平台默认地址（如 https://szbhpt.tsichuan.com/scfy）"
            />
            <div class="field-hint">租户自建部署时填写本租户的数据源地址；留空使用平台默认</div>
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="small"
              :loading="!!busy[a.code]"
              @click="saveAccess(a)"
            >保存配置</el-button>
            <span class="access-hint">
              最近启用：{{ fmtTime(a.enabledAt) }}<template v-if="a.enabledBy"> · 操作人 {{ operatorName(a.enabledBy) }}</template>
            </span>
          </el-form-item>
        </el-form>
      </div>

      <el-empty v-if="!loading && !accessList.length" description="当前没有按租户接入的连接器" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  configureConnectorAccess,
  disableConnectorAccess,
  enableConnectorAccess,
  listConnectorAccess,
  listConnectorCatalog,
  type ConnectorAccessStatus,
  type ConnectorAccessView,
  type ConnectorCatalogEntry
} from '@/api/connectorAdmin'
import { listInstitutions, listAccountCandidates, type Institution } from '@/api/org'

/** 机构（id 必有才进选择器）。 */
type InstitutionRow = Institution & { id: number }
/** 本租户账号候选（userId 必有才进选择器）。 */
type AccountRow = {
  userId: number
  username?: string
  nickname?: string
  boundMemberName?: string
  virtual?: boolean
}

const accessList = ref<ConnectorAccessView[]>([])
const catalog = ref<ConnectorCatalogEntry[]>([])
const institutions = ref<InstitutionRow[]>([])
const accounts = ref<AccountRow[]>([])
const loading = ref(false)
const loadError = ref('')
const busy = reactive<Record<string, boolean>>({})
const accessForm = reactive<Record<string, { scope: Array<number | string>; users: Array<number | string>; baseUrl: string }>>({})

const STATUS_TEXT: Record<ConnectorAccessStatus, string> = {
  NOT_CONNECTED: '未接入',
  CONFIGURED_DISABLED: '已配置待启用',
  ENABLED: '已启用',
  DISABLED: '已停用'
}
const statusText = (s: ConnectorAccessStatus) => STATUS_TEXT[s] || s
const statusTag = (s: ConnectorAccessStatus) =>
  s === 'ENABLED' ? 'success' : s === 'DISABLED' ? 'danger' : 'warning'

const nameOf = (code: string) => catalog.value.find((c) => c.code === code)?.name || code
const summaryOf = (code: string) => catalog.value.find((c) => c.code === code)?.summary || ''

const instLabel = (i: InstitutionRow) => (i.name ? `${i.name}（${i.code || i.id}）` : `机构 ${i.id}`)

function userLabel(u: AccountRow): string {
  const name = u.nickname || u.boundMemberName || ''
  const login = u.username || `#${u.userId}`
  const base = name ? `${name} · ${login}` : login
  return u.virtual ? `${base}（虚拟）` : base
}

function operatorName(id: number): string {
  const u = accounts.value.find((x) => x.userId === id)
  return u ? userLabel(u) : `#${id}`
}

/** ISO 时间 → 「YYYY-MM-DD HH:mm:ss」；空 = 从未。 */
function fmtTime(iso: string | null): string {
  if (!iso) return '从未'
  return iso.replace('T', ' ').slice(0, 19)
}

/** 选择器值 → number[]：allow-create 手输的字符串统一转数字，脏值丢弃不写坏配置。 */
function toIds(arr: Array<number | string> | undefined): number[] {
  return (arr || [])
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n > 0)
}

function errText(reason: unknown): string {
  const msg = (reason as { message?: string })?.message
  return String(msg || reason || '未知错误')
}

function syncAccessForm(a: ConnectorAccessView) {
  accessForm[a.code] = {
    scope: (a.scopeInstitutions || []).slice(),
    users: (a.config?.allowedUserIds || []).slice(),
    baseUrl: String(a.config?.baseUrl ?? '')
  }
}

async function loadAccess() {
  const list = await listConnectorAccess()
  list.forEach(syncAccessForm)   // 先填 form，再赋 list，避免模板渲染时取到 undefined
  accessList.value = list
}

async function reload() {
  loading.value = true
  try {
    await loadAccess()
  } finally {
    loading.value = false
  }
}

async function toggleAccess(a: ConnectorAccessView, on: boolean) {
  busy[a.code] = true
  try {
    const updated = on ? await enableConnectorAccess(a.code) : await disableConnectorAccess(a.code)
    replaceAccess(updated)
    ElMessage.success(on ? '已启用，本租户用户立即可见' : '已停用，工具立即从本租户清单移除')
  } finally {
    busy[a.code] = false
  }
}

async function saveAccess(a: ConnectorAccessView) {
  busy[a.code] = true
  try {
    const f = accessForm[a.code]
    const config: Record<string, unknown> = {}
    const baseUrl = String(f.baseUrl || '').trim()
    if (baseUrl) config.baseUrl = baseUrl
    const users = toIds(f.users)
    if (users.length) config.allowedUserIds = users
    // config 传空对象 = 清空租户级配置；scope 传空数组 = 清空白名单（全租户）
    const updated = await configureConnectorAccess(a.code, {
      scopeInstitutions: toIds(f.scope),
      config
    })
    replaceAccess(updated)
    ElMessage.success('接入配置已保存')
  } finally {
    busy[a.code] = false
  }
}

function replaceAccess(updated: ConnectorAccessView) {
  const i = accessList.value.findIndex((x) => x.code === updated.code)
  if (i >= 0) accessList.value.splice(i, 1, updated)
  else accessList.value.push(updated)
  syncAccessForm(updated)
}

onMounted(async () => {
  loading.value = true
  // 四路真实数据并行加载；接入清单失败要显式报错，其余失败只降级（选择器退化为手输 ID）
  const [access, cat, inst, acs] = await Promise.allSettled([
    listConnectorAccess(),
    listConnectorCatalog(),
    listInstitutions(),
    listAccountCandidates()
  ])
  if (access.status === 'fulfilled') {
    access.value.forEach(syncAccessForm)
    accessList.value = access.value
  } else {
    loadError.value = '接入清单加载失败：' + errText(access.reason)
  }
  if (cat.status === 'fulfilled') catalog.value = cat.value
  if (inst.status === 'fulfilled') {
    institutions.value = inst.value.filter((i): i is InstitutionRow => i.id != null)
  }
  if (acs.status === 'fulfilled') {
    accounts.value = (acs.value as Array<AccountRow & { userId?: number }>).filter(
      (u): u is AccountRow => u.userId != null
    )
  }
  loading.value = false
})
</script>

<style scoped>
.connector-config {
  padding: 16px;
}
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.card-head-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
}
.card-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.access-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px 4px;
  margin-bottom: 14px;
}
.access-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.access-name {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.access-code {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.access-desc {
  margin: 6px 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.access-form {
  max-width: 680px;
}
.field-hint {
  width: 100%;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
  margin-top: 2px;
}
.access-switch {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.access-hint {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
