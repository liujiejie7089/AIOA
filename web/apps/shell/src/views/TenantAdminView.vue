<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="租户管理"
      description="平台管理员在此开通多租户。开通动作会在同一事务内完成：建租户主体 + 开通租户管理员账号 + 初始化资源池，避免出现「有租户但没人能登录」或「能登录但没有额度」的半开通状态。停用租户会同步冻结该租户全部账号。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>租户列表（{{ rows.length }}）</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
            <el-button type="primary" size="small" @click="openDlg()">开通租户</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="租户" min-width="220">
          <template #default="{ row }">
            <span class="t-name">{{ row.name }}</span>
            <div class="muted small">{{ row.code }} · ID {{ row.id }} · {{ row.status === 'ENABLED' ? '启用' : '停用' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="管理员" width="140">
          <template #default="{ row }">
            <template v-if="row.adminUsername">
              {{ row.adminName || row.adminUsername }}
              <div class="muted small">{{ row.adminUsername }}</div>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="机构" width="80" prop="institutionCount" />
        <el-table-column label="成员" width="80" prop="memberCount" />
        <el-table-column label="账号" width="80" prop="userCount" />
        <el-table-column label="登录域名" width="160">
          <template #default="{ row }">
            <span v-if="row.domain">{{ row.domain }}</span>
            <span v-else class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="资源池（词元）" width="150" align="right">
          <template #default="{ row }">{{ (row.quotaTokens ?? 0).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="已分配" width="130" align="right">
          <template #default="{ row }">{{ (row.allocatedTokens ?? 0).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="已用" width="110" align="right">
          <template #default="{ row }">{{ (row.usedTokens ?? 0).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ENABLED' ? 'success' : 'danger'" effect="plain" size="small">
              {{ row.status === 'ENABLED' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openDlg(row)">编辑</el-button>
            <el-button text type="primary" size="small" @click="openQuota(row)">调整资源</el-button>
            <el-button text type="primary" size="small" @click="resetPwd(row)">重置密码</el-button>
            <el-button
              text
              :type="row.status === 'ENABLED' ? 'danger' : 'primary'"
              size="small"
              :disabled="row.id === 1"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'ENABLED' ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 开通 / 编辑 -->
    <el-dialog v-model="dlg" :title="form.id ? '编辑租户' : '开通租户'" width="580">
      <el-form :model="form" label-width="130px" size="small">
        <el-form-item label="租户名称" required>
          <el-input v-model="form.name" placeholder="如：某某市城市建设投资集团" />
        </el-form-item>
        <el-form-item label="租户编码" required>
          <el-input v-model="form.code" :disabled="!!form.id" placeholder="如：CTJT-DEMO（全局唯一）" />
        </el-form-item>
        <el-form-item label="登录域名">
          <el-input v-model="form.domain" placeholder="如：xxx.aioa.cn（留空则未分配）" />
        </el-form-item>
        <template v-if="!form.id">
          <el-divider content-position="left">开通管理员账号</el-divider>
          <el-form-item label="管理员账号" required>
            <el-input v-model="form.adminUsername" placeholder="如：ctjt_admin" />
          </el-form-item>
          <el-form-item label="管理员姓名">
            <el-input v-model="form.adminName" placeholder="如：赵文博" />
          </el-form-item>
          <el-form-item label="初始密码">
            <el-input v-model="form.adminPassword" placeholder="留空则使用 User@123" />
          </el-form-item>
          <el-divider content-position="left">初始化资源池</el-divider>
          <el-form-item label="统计期">
            <el-input v-model="form.period" placeholder="2026-09" />
          </el-form-item>
          <el-form-item label="词元总量">
            <el-input-number v-model="form.tokenTotal" :min="0" :step="100000" style="width: 100%" />
          </el-form-item>
          <el-form-item label="专家席位">
            <el-input-number v-model="form.expertSeats" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item label="技能席位">
            <el-input-number v-model="form.skillSeats" :min="0" style="width: 100%" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 调整资源 -->
    <el-dialog v-model="quotaDlg" title="调整资源" width="520">
      <el-form :model="quotaForm" label-width="120px" size="small">
        <el-form-item label="统计期">
          <el-input v-model="quotaForm.period" placeholder="2026-09（留空为当前周期）" />
        </el-form-item>
        <el-form-item label="词元上限">
          <el-input-number v-model="quotaForm.tokenTotal" :min="0" :step="100000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="专家席位">
          <el-input-number v-model="quotaForm.expertSeats" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="技能席位">
          <el-input-number v-model="quotaForm.skillSeats" :min="0" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="quotaDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="quotaSaving" @click="submitQuota">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http, unwrap } from '@/api'
import { updateTenantQuota } from '@/api/tenantQuota'
import { tenantState } from '@/api/tenantScope'

interface TenantRow {
  id: number
  code?: string
  name?: string
  status?: string
  /** 登录域名（后端新增回吐字段，可能为 null） */
  domain?: string | null
  adminUsername?: string
  adminName?: string
  institutionCount?: number
  memberCount?: number
  userCount?: number
  quotaTokens?: number
  allocatedTokens?: number
  usedTokens?: number
  /** 席位（后端 list 回吐；「调整资源」弹窗必须预填，否则一保存就把席位清零） */
  expertSeats?: number
  expertUsed?: number
  skillSeats?: number
  skillUsed?: number
}

const rows = ref<TenantRow[]>([])
const loading = ref(false)
const saving = ref(false)

async function reload() {
  loading.value = true
  try {
    rows.value = (await http.get('/admin/tenants').then((r) => unwrap<TenantRow[]>(r))) || []
  } catch (e: unknown) {
    ElMessage.error('租户加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}
onMounted(reload)

function apiMsg(e: unknown, fallback: string) {
  return (e as { response?: { data?: { message?: string } } })?.response?.data?.message || fallback
}

const dlg = ref(false)
const form = ref<Record<string, unknown>>({})

function openDlg(row?: TenantRow) {
  if (row) {
    form.value = { id: row.id, code: row.code, name: row.name, domain: row.domain ?? '' }
  } else {
    // 统计期取服务端权威值（见 tenantScope：前端 new Date() 与服务器时钟/时区不一致会建错周期）
    form.value = {
      name: '', code: '', adminUsername: '', adminName: '', adminPassword: '',
      period: tenantState.currentPeriod.value || undefined,
      tokenTotal: 1000000, expertSeats: 8, skillSeats: 12
    }
  }
  dlg.value = true
}

async function submit() {
  if (!form.value.name || !form.value.code) {
    ElMessage.warning('租户名称与编码必填')
    return
  }
  saving.value = true
  try {
    if (form.value.id) {
      await http.put('/admin/tenants/' + form.value.id, {
        name: form.value.name,
        code: form.value.code,
        domain: form.value.domain
      })
      ElMessage.success('已保存')
    } else {
      await http.post('/admin/tenants', form.value)
      ElMessage.success('租户已开通：管理员账号与资源池同步就绪')
    }
    dlg.value = false
    await reload()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: TenantRow) {
  const to = row.status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
  if (to === 'DISABLED') {
    try {
      await ElMessageBox.confirm(
        `停用后「${row.name}」的全部成员将无法登录，确认停用？`, '危险操作',
        { type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消' }
      )
    } catch { return }
  }
  try {
    await http.post('/admin/tenants/' + row.id + '/status', { status: to })
    ElMessage.success(to === 'DISABLED' ? '已停用' : '已启用')
    await reload()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '操作失败'))
  }
}

const quotaDlg = ref(false)
const quotaSaving = ref(false)
const quotaForm = reactive({ id: 0, name: '', period: '', tokenTotal: 0, expertSeats: 0, skillSeats: 0 })

function openQuota(row: TenantRow) {
  Object.assign(quotaForm, {
    id: row.id,
    name: row.name || '',
    period: tenantState.currentPeriod.value || '',
    tokenTotal: row.quotaTokens ?? 0,
    // 席位必须预填**当前值**：后端 list 早就回吐了 expertSeats/skillSeats（它加这四个字段的
    // 注释写的就是「弹窗要能预填当前值，否则用户看不到自己正在改什么」），而这里原先硬写 0 ——
    // 于是打开弹窗看到的是 0，点保存就把租户真实席位（如 8/12）静默清零，
    // 且 upsertPool 对席位**没有**「不得低于已用」的兜底 ⇒ 直接丢数据、无任何提示。
    // 2026-09-28 由本轮的「保留能力仍在」核查发现。
    expertSeats: row.expertSeats ?? 0,
    skillSeats: row.skillSeats ?? 0
  })
  quotaDlg.value = true
}

async function submitQuota() {
  quotaSaving.value = true
  try {
    const res = await updateTenantQuota(quotaForm.id, {
      period: quotaForm.period || undefined,
      tokenTotal: quotaForm.tokenTotal,
      expertSeats: quotaForm.expertSeats,
      skillSeats: quotaForm.skillSeats
    })
    const show = (v: unknown) => (v == null ? '—' : String(v))
    const b = res.before || {}
    const a = res.after || {}
    ElMessage.success(
      `资源已调整（${quotaForm.name}）：词元 ${show(b.tokenTotal)}→${show(a.tokenTotal)}，` +
        `专家席位 ${show(b.expertSeats)}→${show(a.expertSeats)}，` +
        `技能席位 ${show(b.skillSeats)}→${show(a.skillSeats)}`
    )
    quotaDlg.value = false
    await reload()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '调整失败'))
  } finally {
    quotaSaving.value = false
  }
}

async function resetPwd(row: TenantRow) {
  try {
    const { value } = await ElMessageBox.prompt(
      `为「${row.name}」的租户管理员 ${row.adminUsername || ''} 重置密码`,
      '重置密码',
      { inputPlaceholder: '留空则重置为 User@123', inputValue: '' }
    )
    await http.post('/admin/tenants/' + row.id + '/reset-admin-password', { password: value })
    ElMessage.success('密码已重置')
  } catch (e: unknown) {
    if (e === 'cancel') return
    ElMessage.error(apiMsg(e, '重置失败'))
  }
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; }
.t-name { font-weight: 600; }
.muted { color: #909399; }
.small { font-size: 12px; }
</style>
