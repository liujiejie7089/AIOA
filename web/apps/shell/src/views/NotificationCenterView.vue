<template>
  <div class="noti">
    <el-tabs v-model="activeTab" class="noti-tabs">
      <!-- ============================== 我的通知（所有登录角色） ============================== -->
      <el-tab-pane name="mine">
        <template #label>
          <span>
            我的通知
            <el-badge
              v-if="unreadCount > 0"
              :value="unreadCount > 99 ? '99+' : unreadCount"
              class="noti-badge"
            />
          </span>
        </template>

        <div class="noti-toolbar">
          <span class="noti-sub">未读 {{ unreadCount }}</span>
          <el-button
            type="primary"
            size="small"
            :disabled="unreadCount === 0"
            @click="readAll"
            >全部已读</el-button
          >
          <el-button size="small" :loading="notiLoading" @click="loadNotifications">刷新</el-button>
        </div>

        <el-table
          v-loading="notiLoading"
          :data="notifications"
          empty-text="暂无通知"
          stripe
          style="width: 100%"
        >
          <el-table-column prop="title" label="标题" min-width="180">
            <template #default="{ row }">
              <span :class="{ 'noti-unread': row.unread }">{{ row.title || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="content" label="内容" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">{{ row.content || '—' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="NOTI_TYPE_TAG[row.type] || 'info'" size="small" effect="plain">
                {{ NOTI_TYPE_LABEL[row.type] || row.type || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column label="已读态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.unread ? 'danger' : 'success'" size="small" effect="light">
                {{ row.unread ? '未读' : '已读' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.unread"
                type="primary"
                link
                size="small"
                @click="readOne(row.id)"
                >标记已读</el-button
              >
              <span v-else class="noti-muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 通道配置（仅租户管理员） ============================== -->
      <el-tab-pane v-if="isTenantAdmin" name="channels">
        <template #label>通道配置</template>
        <div class="noti-toolbar">
          <span class="noti-sub">配置各通道的启用与接入参数（可配置 HTTP 网关）</span>
          <el-button size="small" :loading="channelLoading" @click="loadChannels">刷新</el-button>
        </div>

        <div v-loading="channelLoading">
          <el-empty v-if="!channelLoading && channels.length === 0" description="暂无通道" />
          <el-card
            v-for="ch in channels"
            :key="ch.code"
            shadow="never"
            class="noti-channel"
          >
            <template #header>
              <div class="noti-channel-head">
                <span class="noti-channel-name">{{ ch.label }}（{{ ch.code }}）</span>
                <el-tag v-if="ch.configured" size="small" type="success" effect="plain">已配置</el-tag>
                <el-tag v-else size="small" type="info" effect="plain">未配置</el-tag>
              </div>
            </template>

            <!-- 站内信：仅展示，不可编辑 -->
            <template v-if="ch.code === 'INAPP'">
              <el-alert
                type="info"
                :closable="false"
                show-icon
                title="站内信为系统内通道，始终可用，无需网关配置。"
              />
            </template>

            <!-- 非站内通道：启用开关 + 配置表单 + 发送测试 -->
            <template v-else>
              <el-form label-width="120px" class="noti-form">
                <el-form-item label="启用">
                  <el-switch v-model="forms[ch.code].enabled" />
                </el-form-item>
                <el-form-item label="网关地址 url" required>
                  <el-input
                    v-model="forms[ch.code].config.url"
                    placeholder="http(s)://gateway.example.com/send"
                  />
                </el-form-item>
                <el-form-item label="令牌 token" required>
                  <el-input
                    v-model="forms[ch.code].config.token"
                    placeholder="网关鉴权令牌"
                    show-password
                  />
                </el-form-item>
                <el-form-item v-if="ch.code === 'EMAIL'" label="发件人 from" required>
                  <el-input v-model="forms[ch.code].config.from" placeholder="noreply@example.com" />
                </el-form-item>
                <el-form-item v-if="ch.code === 'SMS'" label="签名 signName" required>
                  <el-input v-model="forms[ch.code].config.signName" placeholder="企业签名" />
                </el-form-item>
                <el-form-item v-if="ch.code === 'PUSH'" label="标题模板" prop="titleTemplate">
                  <el-input
                    v-model="forms[ch.code].config.titleTemplate"
                    maxlength="64"
                    show-word-limit
                    placeholder="可选，≤64 字"
                  />
                </el-form-item>
                <el-form-item>
                  <el-button
                    type="primary"
                    size="small"
                    :loading="channelSaving === ch.code"
                    @click="saveChannel(ch.code)"
                    >保存</el-button
                  >
                  <el-button
                    size="small"
                    :loading="channelTesting === ch.code"
                    @click="testChannelFn(ch.code)"
                    >发送测试</el-button
                  >
                </el-form-item>
              </el-form>

              <el-alert
                v-if="testResults[ch.code]"
                :type="testResults[ch.code].status === 'SENT' ? 'success' : 'error'"
                :closable="false"
                show-icon
                class="noti-test"
                :title="`测试结果：${testResults[ch.code].status}`"
                :description="testResults[ch.code].message"
              />
            </template>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- ============================== 投递记录（仅租户管理员） ============================== -->
      <el-tab-pane v-if="isTenantAdmin" name="deliveries">
        <template #label>投递记录</template>
        <div class="noti-toolbar">
          <el-select
            v-model="deliveryStatusFilter"
            size="small"
            placeholder="全部状态"
            clearable
            style="width: 160px"
            @change="loadDeliveries"
          >
            <el-option
              v-for="s in deliveryStatusOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
          <span class="noti-sub">共 {{ deliveryTotal }} 条</span>
          <el-button size="small" :loading="deliveryLoading" @click="loadDeliveries">刷新</el-button>
        </div>

        <el-table
          v-loading="deliveryLoading"
          :data="deliveries"
          empty-text="暂无投递记录"
          stripe
          style="width: 100%"
        >
          <el-table-column prop="notificationId" label="通知 ID" width="110" />
          <el-table-column label="通道" width="110">
            <template #default="{ row }">{{ channelLabel(row.channelCode) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="deliveryStatusTag(row.status)" size="small" effect="light">
                {{ deliveryStatusLabel(row.status) || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="attempts" label="尝试次数" width="100" />
          <el-table-column label="错误" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.lastError || '—' }}</template>
          </el-table-column>
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ fmtTime(row.sentAt || row.createdAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'FAILED'"
                type="primary"
                link
                size="small"
                :loading="deliveryRetrying === row.id"
                @click="retryDeliveryFn(row.id)"
                >重试</el-button
              >
              <span v-else class="noti-muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 个人偏好（所有登录角色） ============================== -->
      <el-tab-pane name="prefs">
        <template #label>个人偏好</template>
        <div class="noti-toolbar">
          <span class="noti-sub">选择默认接收通道（可多选）</span>
          <el-button
            type="primary"
            size="small"
            :loading="prefSaving"
            @click="savePreferences"
            >保存偏好</el-button
          >
          <el-button size="small" :loading="prefLoading" @click="loadPreferences">刷新</el-button>
        </div>

        <el-card shadow="never" class="noti-pref">
          <el-form label-width="120px">
            <el-form-item label="默认通道">
              <el-checkbox-group v-model="preferences.defaultChannels">
                <el-checkbox
                  v-for="c in CHANNEL_CODES"
                  :key="c"
                  :value="c"
                  :label="CHANNEL_LABELS[c]"
                />
              </el-checkbox-group>
            </el-form-item>
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="站内信（INAPP）始终写入，建议保持勾选；关闭后系统消息仍可正常接收。"
            />
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { hasAnyRole, TENANT_SCOPE_ROLES } from '@/constants/permissions'
import {
  CHANNEL_CODES,
  CHANNEL_LABELS,
  DELIVERY_STATUS_LABEL,
  DELIVERY_STATUS_TAG,
  NOTI_TYPE_LABEL,
  NOTI_TYPE_TAG,
  type ChannelCode,
  type ChannelTestResult,
  type DeliveryStatus,
  type NotificationItem,
  type NotificationPreferences,
  getPreferences,
  listChannels,
  listDeliveries,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notiErrMsg,
  retryDelivery,
  testChannel,
  updateChannel,
  updatePreferences
} from '@/api/notifications'

const auth = useAuthStore()
/** 租户管理员判定：与 GiteeProjectsView 同源（TENANT_SCOPE_ROLES = ADMIN / TENANT_ADMIN）。 */
const isTenantAdmin = computed(() => hasAnyRole(auth.roles, TENANT_SCOPE_ROLES))

const activeTab = ref<'mine' | 'channels' | 'deliveries' | 'prefs'>('mine')

function fmtTime(t?: string | null): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

// el-table 的 row 在模板里是 any，直接用 any 索引受限于具体键类型的 Record 会触发 TS7053，
// 故统一经这些函数收窄（同时回退到原值，避免未知码显示空白）。
function channelLabel(code: string): string {
  return CHANNEL_LABELS[code as ChannelCode] || code
}
function deliveryStatusLabel(s: string): string {
  return DELIVERY_STATUS_LABEL[s as DeliveryStatus] || s
}
function deliveryStatusTag(s: string): string {
  return DELIVERY_STATUS_TAG[s as DeliveryStatus] || 'info'
}

const deliveryStatusOptions: { value: DeliveryStatus; label: string }[] = (
  Object.keys(DELIVERY_STATUS_LABEL) as DeliveryStatus[]
).map((s) => ({ value: s, label: DELIVERY_STATUS_LABEL[s] }))

// ---------------------------------------------------------------- 我的通知
const notifications = ref<NotificationItem[]>([])
const unreadCount = ref(0)
const notiLoading = ref(false)

async function loadNotifications() {
  notiLoading.value = true
  try {
    const res = await listNotifications(50)
    notifications.value = res.items || []
    unreadCount.value = res.unread || 0
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '加载通知失败'))
  } finally {
    notiLoading.value = false
  }
}

async function readOne(id: number) {
  try {
    await markNotificationRead(id)
    const n = notifications.value.find((x) => x.id === id)
    if (n) n.unread = false
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '标记已读失败'))
  }
}

async function readAll() {
  try {
    await markAllNotificationsRead()
    notifications.value.forEach((n) => (n.unread = false))
    unreadCount.value = 0
    ElMessage.success('已全部标记已读')
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '操作失败'))
  }
}

// ---------------------------------------------------------------- 通道配置（仅租户管理员）
interface ChannelForm {
  enabled: boolean
  config: {
    url: string
    token: string
    from: string
    signName: string
    titleTemplate: string
  }
}

const channels = ref<{ code: ChannelCode; label: string; configured: boolean }[]>([])
const channelLoading = ref(false)
const channelSaving = ref<ChannelCode | ''>('')
const channelTesting = ref<ChannelCode | ''>('')
const forms = ref<Record<string, ChannelForm>>({})
const testResults = ref<Record<string, ChannelTestResult>>({})

function blankForm(): ChannelForm {
  return {
    enabled: false,
    config: { url: '', token: '', from: '', signName: '', titleTemplate: '' }
  }
}

async function loadChannels() {
  if (!isTenantAdmin.value) return
  channelLoading.value = true
  try {
    const res = await listChannels()
    channels.value = (res.items || []).map((c) => ({
      code: c.code,
      label: c.label,
      configured: c.configured
    }))
    const next: Record<string, ChannelForm> = {}
    for (const c of res.items || []) {
      next[c.code] = {
        enabled: c.enabled,
        config: {
          url: c.config?.url || '',
          token: c.config?.token || '',
          from: c.config?.from || '',
          signName: c.config?.signName || '',
          titleTemplate: c.config?.titleTemplate || ''
        }
      }
    }
    forms.value = next
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '加载通道配置失败'))
  } finally {
    channelLoading.value = false
  }
}

/** 本地必填校验：按通道码取必填键，不通过返回错误文案（不发起请求）。 */
function validateChannel(code: ChannelCode): string {
  if (code === 'INAPP') return ''
  const f = forms.value[code] || blankForm()
  const cfg = f.config
  if (!/^https?:\/\//i.test(cfg.url || '')) return '网关地址 url 必须以 http:// 或 https:// 开头'
  if (!cfg.token?.trim()) return '缺少令牌 token'
  if (code === 'EMAIL' && !cfg.from?.trim()) return '邮件通道缺少发件人 from'
  if (code === 'SMS' && !cfg.signName?.trim()) return '短信通道缺少签名 signName'
  if (code === 'PUSH' && (cfg.titleTemplate?.length || 0) > 64) {
    return '标题模板不能超过 64 字符'
  }
  return ''
}

async function saveChannel(code: ChannelCode) {
  const err = validateChannel(code)
  if (err) {
    ElMessage.warning(err)
    return
  }
  const f = forms.value[code] || blankForm()
  channelSaving.value = code
  try {
    await updateChannel(code, { enabled: f.enabled, config: f.config })
    ElMessage.success(`${CHANNEL_LABELS[code]} 配置已保存`)
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '保存失败'))
  } finally {
    channelSaving.value = ''
  }
}

async function testChannelFn(code: ChannelCode) {
  channelTesting.value = code
  delete testResults.value[code]
  try {
    testResults.value[code] = await testChannel(code)
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '测试请求失败'))
  } finally {
    channelTesting.value = ''
  }
}

// ---------------------------------------------------------------- 投递记录（仅租户管理员）
const deliveries = ref<{
  id: number
  notificationId: number
  channelCode: ChannelCode
  status: DeliveryStatus
  attempts: number
  lastError?: string | null
  sentAt?: string | null
  createdAt?: string
}[]>([])
const deliveryTotal = ref(0)
const deliveryLoading = ref(false)
const deliveryStatusFilter = ref<DeliveryStatus | ''>('')
const deliveryRetrying = ref<number | null>(null)

async function loadDeliveries() {
  if (!isTenantAdmin.value) return
  deliveryLoading.value = true
  try {
    const res = await listDeliveries({
      status: deliveryStatusFilter.value || undefined,
      limit: 50
    })
    deliveries.value = res.items || []
    deliveryTotal.value = res.total || 0
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '加载投递记录失败'))
  } finally {
    deliveryLoading.value = false
  }
}

async function retryDeliveryFn(id: number) {
  deliveryRetrying.value = id
  try {
    await retryDelivery(id)
    ElMessage.success('已触发重试')
    await loadDeliveries()
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '重试失败'))
  } finally {
    deliveryRetrying.value = null
  }
}

// ---------------------------------------------------------------- 个人偏好（所有登录角色）
const preferences = ref<NotificationPreferences>({ defaultChannels: [], byType: {} })
const prefLoading = ref(false)
const prefSaving = ref(false)

async function loadPreferences() {
  prefLoading.value = true
  try {
    preferences.value = await getPreferences()
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '加载偏好失败'))
  } finally {
    prefLoading.value = false
  }
}

async function savePreferences() {
  prefSaving.value = true
  try {
    preferences.value = await updatePreferences(preferences.value)
    ElMessage.success('已保存偏好')
  } catch (e: unknown) {
    ElMessage.error(notiErrMsg(e, '保存偏好失败'))
  } finally {
    prefSaving.value = false
  }
}

// ---------------------------------------------------------------- 初始化
onMounted(async () => {
  // 每个数据块独立 try/catch：一块失败不拖垮整页。
  await loadNotifications()
  await loadPreferences()
  // 仅租户管理员才发起通道配置 / 投递记录请求，否则会 403。
  if (isTenantAdmin.value) {
    await loadChannels()
    await loadDeliveries()
  }
})
</script>

<style scoped>
.noti {
  padding: 4px 4px 16px;
}
.noti-tabs {
  --el-tabs-header-height: 44px;
}
.noti-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 4px 0 12px;
}
.noti-sub {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.noti-channel {
  margin-bottom: 12px;
}
.noti-channel-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.noti-channel-name {
  font-weight: 600;
}
.noti-form {
  margin-top: 8px;
  max-width: 640px;
}
.noti-test {
  margin-top: 4px;
}
.noti-pref {
  max-width: 640px;
}
.noti-unread {
  font-weight: 600;
}
.noti-muted {
  color: var(--el-text-color-placeholder);
}
.noti-badge :deep(.el-badge__content) {
  margin-left: 6px;
}
</style>
