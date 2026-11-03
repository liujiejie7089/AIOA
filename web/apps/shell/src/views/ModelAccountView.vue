<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="模型账号与用量归属"
      description="你可以用自己注册的账号（供应商官方计费，公司不收费），也可以邀请同事共用你的账号——被邀请人消耗的词元记在你头上。公司提供的账号走公司额度。三类账号分开管，每一笔用量都标注「是否公司收费」。"
      style="margin-bottom: 12px"
    />

    <el-tabs v-model="tab" type="border-card">
      <!-- ============================== 我的账号 ============================== -->
      <el-tab-pane label="我的账号" name="mine">
        <div class="toolbar">
          <el-button type="primary" size="small" @click="openCreate">新增账号</el-button>
          <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
          <span class="hint">自己注册的账号：使用量由供应商按各自账号计费，平台只做统计，不向你收费</span>
        </div>
        <el-table v-loading="loading" :data="mine" stripe size="small">
          <el-table-column label="名称" min-width="150" prop="name" show-overflow-tooltip />
          <el-table-column label="供应商" width="120" prop="providerKey" />
          <el-table-column label="模型" min-width="140">
            <template #default="{ row }">{{ row.modelName || '（跟随供应商默认）' }}</template>
          </el-table-column>
          <el-table-column label="密钥" width="150">
            <template #default="{ row }"><span class="mono">{{ row.keyHint || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="共享" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.shareEnabled ? 'success' : 'info'" effect="plain">
                {{ row.shareEnabled ? '已开启' : '未开启' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="共享人数" width="90" align="right" prop="shareCount" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'danger'" effect="plain">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openInvite(row)">邀请同事</el-button>
              <el-button text type="primary" size="small" @click="toggleShare(row)">
                {{ row.shareEnabled ? '关闭共享' : '开启共享' }}
              </el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 公司账号 ============================== -->
      <el-tab-pane label="公司账号" name="company">
        <div class="toolbar">
          <el-button v-if="isAdmin" type="primary" size="small" @click="openCreate('COMPANY')">新增公司账号</el-button>
          <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
          <span class="hint">公司统一提供的账号：走公司额度，用量标注「公司收费」；{{ isAdmin ? '' : '只有管理员可以创建或修改' }}</span>
        </div>
        <el-table v-loading="loading" :data="company" stripe size="small">
          <el-table-column label="名称" min-width="150" prop="name" show-overflow-tooltip />
          <el-table-column label="供应商" width="120" prop="providerKey" />
          <el-table-column label="密钥" width="150">
            <template #default="{ row }"><span class="mono">{{ row.keyHint || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="共享" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.shareEnabled ? 'success' : 'info'" effect="plain">
                {{ row.shareEnabled ? '已开启' : '未开启' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'danger'" effect="plain">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button v-if="isAdmin" text type="primary" size="small" @click="openInvite(row)">邀请同事</el-button>
              <el-button v-if="isAdmin" text type="primary" size="small" @click="toggleShare(row)">
                {{ row.shareEnabled ? '关闭共享' : '开启共享' }}
              </el-button>
              <span v-if="!isAdmin" class="muted">由管理员维护</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 共享给我 ============================== -->
      <el-tab-pane label="共享给我" name="shared">
        <div class="toolbar">
          <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
          <span class="hint">用这些账号不消耗你自己的额度——词元记在邀请者头上</span>
        </div>
        <el-table v-loading="loading" :data="shared" stripe size="small">
          <el-table-column label="名称" min-width="150" prop="name" show-overflow-tooltip />
          <el-table-column label="供应商" width="120" prop="providerKey" />
          <el-table-column label="密钥" width="150">
            <template #default="{ row }"><span class="mono">{{ row.keyHint || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="来源" min-width="120">
            <template #default="{ row }">{{ ownerName(row) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'danger'" effect="plain">
                {{ row.enabled ? '可用' : '已停用' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 邀请记录 ============================== -->
      <el-tab-pane label="邀请记录" name="invites">
        <div class="toolbar">
          <el-button text type="primary" size="small" :loading="invitesLoading" @click="loadInvites">刷新</el-button>
          <span class="hint">你发起的共享：被邀请人消耗的词元由你承担</span>
        </div>
        <el-table v-loading="invitesLoading" :data="invites" stripe size="small">
          <el-table-column label="账号" min-width="140" prop="credentialName" show-overflow-tooltip />
          <el-table-column label="被邀请人" width="120" prop="granteeName" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="共享额度" width="180" align="right">
            <template #default="{ row }">
              {{ row.quotaTokens ? fmt(row.quotaTokens) : '不限' }}
            </template>
          </el-table-column>
          <el-table-column label="已用" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.usedTokens) }}</template>
          </el-table-column>
          <el-table-column label="到期" width="170">
            <template #default="{ row }">{{ row.expiresAt ? fmtTime(row.expiresAt) : '长期' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'ACTIVE'"
                text type="danger" size="small" @click="revoke(row)">撤销</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 用量归属 ============================== -->
      <el-tab-pane label="用量归属" name="stats">
        <div class="toolbar">
          <el-radio-group v-model="dim" size="small" @change="loadStats">
            <el-radio-button value="credential">按账号</el-radio-button>
            <el-radio-button value="bearer">按使用者</el-radio-button>
            <el-radio-button value="charge">按付费人</el-radio-button>
          </el-radio-group>
          <el-date-picker v-model="period" type="month" value-format="YYYY-MM" size="small"
                          style="width: 130px" :clearable="false" @change="loadStats" />
          <el-button text type="primary" size="small" :loading="statsLoading" @click="loadStats">刷新</el-button>
        </div>

        <div class="stat-row">
          <div class="stat-card">
            <div class="stat-label">公司收费</div>
            <div class="stat-value">{{ fmt(stats?.split.companyCharged) }}</div>
            <div class="stat-sub">走公司额度</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">个人自付</div>
            <div class="stat-value">{{ fmt(stats?.split.personalCharged) }}</div>
            <div class="stat-sub">供应商按各自账号计费</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">未标注</div>
            <div class="stat-value">{{ fmt(stats?.split.unmarked) }}</div>
            <div class="stat-sub">历史账本，无归属记录</div>
          </div>
          <div class="stat-card highlight">
            <div class="stat-label">合计词元</div>
            <div class="stat-value">{{ fmt(stats?.split.total) }}</div>
            <div class="stat-sub">{{ fmt(stats?.split.calls) }} 次调用</div>
          </div>
        </div>

        <el-table v-loading="statsLoading" :data="statsRows" stripe size="small" max-height="360">
          <el-table-column :label="dimLabel" min-width="180" prop="name" show-overflow-tooltip />
          <el-table-column label="来源" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.ownerType" size="small" effect="plain">
                {{ row.ownerType === 'COMPANY' ? '公司提供' : '个人注册' }}
              </el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="是否公司收费" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="chargeType(row.companyCharged)" effect="plain">
                {{ chargeLabel(row.companyCharged) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="消耗词元" width="130" align="right">
            <template #default="{ row }">{{ fmt(row.tokens) }}</template>
          </el-table-column>
          <el-table-column label="调用次数" width="110" align="right" prop="calls" />
          <el-table-column v-if="dim !== 'bearer'" label="涉及人数" width="100" align="right" prop="members" />
        </el-table>

        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 10px"
          title="口径说明"
          description="三个维度聚合的是同一批账本，合计恒等；「是否公司收费」只由账号来源推导（公司提供的账号=公司收费，个人注册=个人自付），不由页面另算。未标注是历史账本——当年没有归属记录，不编造。"
        />
      </el-tab-pane>
    </el-tabs>

    <!-- 新建 / 编辑账号 -->
    <el-dialog v-model="createVisible" :title="form.ownerType === 'COMPANY' ? '新增公司账号' : '新增账号'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：我的 DeepSeek" maxlength="64" />
        </el-form-item>
        <el-form-item label="供应商" required>
          <el-select v-model="form.providerKey" style="width: 100%">
            <el-option v-for="p in PROVIDERS" :key="p.key" :label="p.label" :value="p.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key" required>
          <el-input v-model="form.apiKey" type="password" show-password placeholder="sk-..." />
          <div class="field-hint">密钥加密后入库，任何界面都不再显示明文，只保留前 3 后 4 掩码</div>
        </el-form-item>
        <el-form-item label="接口地址">
          <el-input v-model="form.baseUrl" placeholder="留空 = 用该供应商默认地址" />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.modelName" placeholder="留空 = 用该供应商默认模型" />
        </el-form-item>
        <el-form-item label="允许共享">
          <el-switch v-model="form.shareEnabled" />
          <span class="field-hint">开启后才能邀请同事共用；被邀请人消耗的词元由你承担</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="createVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 邀请同事 -->
    <el-dialog v-model="inviteVisible" title="邀请同事共用账号" width="440px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 10px"
        title="被邀请人消耗的词元由你承担"
        description="用你的账号产生的用量记在你名下（统计里能看到）；你自己的额度也会被扣减。"
      />
      <el-form :model="inviteForm" label-width="90px">
        <el-form-item label="同事账号" required>
          <el-input v-model="inviteForm.granteeUsername" placeholder="用户名，如 fagai_liu" />
        </el-form-item>
        <el-form-item label="共享额度">
          <el-input v-model="inviteForm.quotaTokens" placeholder="0 = 不限">
            <template #append>词元</template>
          </el-input>
        </el-form-item>
        <el-form-item label="到期时间">
          <el-date-picker v-model="inviteForm.expiresAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
                          style="width: 100%" placeholder="留空 = 长期" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="inviteVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="submitInvite">发出邀请</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  myAccounts,
  myInvites,
  incomingInvites,
  createCredential,
  updateCredential,
  deleteCredential,
  inviteShare,
  revokeShare,
  billingStats,
  type MyAccounts,
  type ModelCredentialView,
  type ShareView,
  type StatsView,
} from '@/api/modelAccount'
import { useAuthStore } from '@/stores/auth'

/** 可选供应商（与 agent 侧 provider 注册表 key 对齐；缺省走平台已配置的其余 provider）。 */
const PROVIDERS = [
  { key: 'deepseek', label: 'DeepSeek' },
  { key: 'dashscope', label: '通义百炼' },
  { key: 'minimax', label: 'MiniMax' },
  { key: 'vllm', label: 'vLLM（私有化）' },
  { key: 'ollama', label: 'Ollama（本地）' },
]

const auth = useAuthStore()
const isAdmin = computed(() => {
  const roles = auth.user?.roles || []
  return roles.includes('ROLE_ADMIN') || roles.includes('ROLE_TENANT_ADMIN')
})

const tab = ref('mine')
const loading = ref(false)
const mine = ref<ModelCredentialView[]>([])
const company = ref<ModelCredentialView[]>([])
const shared = ref<ModelCredentialView[]>([])

const invitesLoading = ref(false)
const invites = ref<ShareView[]>([])
/** 共享给我的关系（用来在「共享给我」页显示邀请者姓名）。 */
const sharedOwnerName = ref<Record<number, string>>({})

const createVisible = ref(false)
const saving = ref(false)
const form = reactive({
  ownerType: 'PERSONAL' as 'PERSONAL' | 'COMPANY',
  name: '',
  providerKey: 'deepseek',
  apiKey: '',
  baseUrl: '',
  modelName: '',
  shareEnabled: false,
  remark: '',
})

const inviteVisible = ref(false)
const inviteForm = reactive({ credentialId: 0, granteeUsername: '', quotaTokens: '', expiresAt: '' })

const dim = ref<'credential' | 'bearer' | 'charge'>('credential')
const period = ref(new Date().toISOString().slice(0, 7))
const statsLoading = ref(false)
const stats = ref<StatsView | null>(null)

const statsRows = computed(() => stats.value?.rows || [])
const dimLabel = computed(() =>
  dim.value === 'credential' ? '账号' : dim.value === 'bearer' ? '使用者' : '付费人')

function fmt(v?: number | null) {
  return (v ?? 0).toLocaleString('zh-CN')
}

function fmtTime(v?: string | null) {
  return v ? v.replace('T', ' ').slice(0, 16) : '—'
}

function chargeLabel(v: number | null) {
  if (v === null) return '未标注'
  return v === 1 ? '公司收费' : '个人自付'
}

function chargeType(v: number | null): 'success' | 'info' | 'warning' {
  if (v === null) return 'info'
  return v === 1 ? 'success' : 'warning'
}

function statusLabel(s: string) {
  return s === 'ACTIVE' ? '生效中' : s === 'PENDING' ? '待接受' : s === 'REVOKED' ? '已撤销' : '已过期'
}

function statusType(s: string): 'success' | 'info' | 'danger' {
  if (s === 'ACTIVE') return 'success'
  if (s === 'REVOKED') return 'danger'
  return 'info'
}

function ownerName(row: ModelCredentialView) {
  return sharedOwnerName.value[row.id] || '同事共享'
}

async function load() {
  loading.value = true
  try {
    const data: MyAccounts = await myAccounts()
    mine.value = data.mine || []
    company.value = data.company || []
    shared.value = data.shared || []
  } catch (e: unknown) {
    ElMessage.error('账号加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

async function loadInvites() {
  invitesLoading.value = true
  try {
    // 来往两个方向都要：outgoing 是「我邀请的」，incoming 用来取「谁共享给我」
    // （「共享给我」页显示的是账号，邀请者姓名只能从来往记录里反查）。
    const [outgoing, incoming] = await Promise.all([
      myInvites(),
      incomingInvites().catch(() => [] as ShareView[]),
    ])
    invites.value = outgoing || []
    for (const s of incoming) {
      if (s.credentialId) sharedOwnerName.value[s.credentialId] = s.ownerName || '同事'
    }
  } catch (e: unknown) {
    ElMessage.error('邀请记录加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    invitesLoading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await billingStats(dim.value, period.value)
  } catch (e: unknown) {
    ElMessage.error('统计加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    statsLoading.value = false
  }
}

function openCreate(ownerType?: 'COMPANY') {
  form.ownerType = ownerType || 'PERSONAL'
  form.name = ''
  form.providerKey = 'deepseek'
  form.apiKey = ''
  form.baseUrl = ''
  form.modelName = ''
  form.shareEnabled = false
  form.remark = ''
  createVisible.value = true
}

async function submitCreate() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (!form.apiKey.trim()) {
    ElMessage.warning('请填写 API Key')
    return
  }
  saving.value = true
  try {
    await createCredential({
      ownerType: form.ownerType,
      providerKey: form.providerKey,
      name: form.name.trim(),
      apiKey: form.apiKey.trim(),
      baseUrl: form.baseUrl.trim() || undefined,
      modelName: form.modelName.trim() || undefined,
      shareEnabled: form.shareEnabled,
      remark: form.remark.trim() || undefined,
    })
    ElMessage.success('账号已创建')
    createVisible.value = false
    await load()
  } catch (e: unknown) {
    ElMessage.error('创建失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    saving.value = false
  }
}

async function toggleShare(row: ModelCredentialView) {
  saving.value = true
  try {
    await updateCredential(row.id, { shareEnabled: !row.shareEnabled })
    ElMessage.success(row.shareEnabled ? '已关闭共享' : '已开启共享')
    await load()
  } catch (e: unknown) {
    ElMessage.error('操作失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    saving.value = false
  }
}

async function remove(row: ModelCredentialView) {
  await ElMessageBox.confirm(
    `删除「${row.name}」？已产生的用量记录保留，共享关系保留（审计需要），但该账号立即不可用。`,
    '删除确认',
    { type: 'warning' },
  )
  try {
    await deleteCredential(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: unknown) {
    ElMessage.error('删除失败：' + ((e as Error)?.message || '后端异常'))
  }
}

function openInvite(row: ModelCredentialView) {
  inviteForm.credentialId = row.id
  inviteForm.granteeUsername = ''
  inviteForm.quotaTokens = ''
  inviteForm.expiresAt = ''
  inviteVisible.value = true
}

async function submitInvite() {
  if (!inviteForm.granteeUsername.trim()) {
    ElMessage.warning('请填写同事账号')
    return
  }
  saving.value = true
  try {
    await inviteShare(inviteForm.credentialId, {
      granteeUsername: inviteForm.granteeUsername.trim(),
      quotaTokens: inviteForm.quotaTokens ? Number(inviteForm.quotaTokens) : 0,
      expiresAt: inviteForm.expiresAt || undefined,
    })
    ElMessage.success('已邀请，对方现在就能用这个账号')
    inviteVisible.value = false
    await Promise.all([load(), loadInvites()])
  } catch (e: unknown) {
    ElMessage.error('邀请失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    saving.value = false
  }
}

async function revoke(row: ShareView) {
  await ElMessageBox.confirm(`撤销「${row.granteeName}」的共享？撤销后对方下一轮对话就不能再用这个账号。`, '撤销确认', {
    type: 'warning',
  })
  try {
    await revokeShare(row.id)
    ElMessage.success('已撤销')
    await loadInvites()
  } catch (e: unknown) {
    ElMessage.error('撤销失败：' + ((e as Error)?.message || '后端异常'))
  }
}

onMounted(() => {
  load()
  loadInvites()
  loadStats()
})
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.toolbar .hint { margin-left: auto; font-size: 12px; color: #909399; }
.stat-row { display: flex; gap: 12px; margin-bottom: 12px; }
.stat-card {
  flex: 1; background: #faf9f5; border: 1px solid #e4e7ed; border-radius: 6px; padding: 10px 14px;
}
.stat-card.highlight { background: #f2f6f4; border-color: #cfdcd6; }
.stat-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.stat-value { font-size: 22px; font-weight: 600; color: #1f2933; line-height: 1.2; }
.stat-sub { font-size: 12px; color: #909399; margin-top: 4px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.muted { color: #909399; font-size: 12px; }
.field-hint { font-size: 12px; color: #909399; line-height: 1.5; }
</style>
