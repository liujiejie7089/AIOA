<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="机构管理"
      description="租户管理员在此维护下属机构（企业/单位），分配机构词元配额，并跟踪每家机构的 8 步入驻进度。配额受资源池总量约束，超额分配会被服务端拒绝。"
      style="margin-bottom: 12px"
    />

    <!-- 资源池 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <span>资源池（{{ period }}）</span>
          <div>
            <el-button text type="primary" size="small" @click="openPoolDlg">池扩容 / 调参</el-button>
            <el-button text type="primary" size="small" :loading="loading" @click="reloadAll">刷新</el-button>
          </div>
        </div>
      </template>
      <el-descriptions :column="5" border size="small" v-if="pool">
        <el-descriptions-item label="总量（词元）">{{ fmt(pool.tokenTotal) }}</el-descriptions-item>
        <el-descriptions-item label="已分配">{{ fmt(pool.tokenAllocated) }}</el-descriptions-item>
        <el-descriptions-item label="可分配">{{ fmt(pool.allocatableTokens) }}</el-descriptions-item>
        <el-descriptions-item label="已用">{{ fmt(pool.tokenUsed) }}</el-descriptions-item>
        <el-descriptions-item label="预警阈值">{{ pool.warnThreshold ?? '—' }}%</el-descriptions-item>
        <el-descriptions-item label="专家席位">{{ pool.expertUsed ?? 0 }} / {{ pool.expertSeats ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="技能席位">{{ pool.skillUsed ?? 0 }} / {{ pool.skillSeats ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="单价（¥/词元）">{{ pool.unitPrice ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="到期日">{{ pool.expireAt || '—' }}</el-descriptions-item>
        <el-descriptions-item label="统计期">{{ period }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="暂无资源池数据" :image-size="48" />
    </el-card>

    <!-- 机构列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>机构列表（{{ rows.length }}）</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="reloadAll">刷新</el-button>
            <el-button type="primary" size="small" @click="openDlg()">新增机构</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe row-key="id">
        <el-table-column label="机构名称" min-width="180">
          <template #default="{ row }">
            <span class="inst-name">{{ row.name }}</span>
            <div class="muted small">{{ row.code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ orgTypeText(row.orgType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="企业管理员" width="130">
          <template #default="{ row }">
            {{ row.adminName || '—' }}
            <div class="muted small">{{ row.adminUsername }}</div>
          </template>
        </el-table-column>
        <el-table-column label="部门 / 成员" width="100">
          <template #default="{ row }">{{ row.departmentCount ?? 0 }} / {{ row.memberCount ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="配额（词元）" width="150">
          <template #default="{ row }">
            <template v-if="quotaOf(row.id)">
              {{ fmt(quotaOf(row.id)!.quotaTokens) }}
              <div class="muted small">剩余 {{ fmt(quotaOf(row.id)!.remainTokens) }}</div>
            </template>
            <span v-else class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="入驻进度" width="120">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round(((row.onboardStep ?? 0) / 8) * 100)"
              :stroke-width="6"
              :status="(row.onboardStep ?? 0) >= 8 ? 'success' : undefined"
            />
            <div class="muted small">{{ row.onboardStep ?? 0 }} / 8 步</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="290" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openDlg(row)">编辑</el-button>
            <el-button text type="primary" size="small" @click="openQuotaDlg(row)">配额</el-button>
            <el-button text type="primary" size="small" @click="openAdminDlg(row)">交接</el-button>
            <el-dropdown trigger="click" @command="(c: string) => onAction(row, c)">
              <el-button text type="primary" size="small">更多<el-icon class="el-icon--right"><arrow-down /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="suspend" :disabled="row.status !== 'ACTIVE'">停用</el-dropdown-item>
                  <el-dropdown-item command="resume" :disabled="row.status !== 'SUSPENDED'">恢复</el-dropdown-item>
                  <el-dropdown-item command="freeze" :disabled="!quotaOf(row.id) || !!quotaOf(row.id)!.frozen">冻结配额</el-dropdown-item>
                  <el-dropdown-item command="unfreeze" :disabled="!quotaOf(row.id) || !quotaOf(row.id)!.frozen">解冻配额</el-dropdown-item>
                  <el-dropdown-item command="close" divided :disabled="row.status === 'CLOSED'">注销</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增 / 编辑 -->
    <el-dialog v-model="dlg" :title="form.id ? '编辑机构' : '新增机构'" width="640">
      <el-form :model="form" label-width="110px" size="small">
        <el-form-item label="机构名称" required>
          <el-input v-model="form.name" placeholder="如：某某区市场监督管理局" />
        </el-form-item>
        <el-form-item label="机构编码" required>
          <el-input v-model="form.code" :disabled="!!form.id" placeholder="如：ORG-SCJG（租户内唯一）" />
        </el-form-item>
        <el-form-item label="机构类型">
          <el-select v-model="form.orgType" style="width: 100%">
            <el-option label="政府机关" value="GOVERNMENT" />
            <el-option label="事业单位" value="INSTITUTION" />
            <el-option label="国有企业" value="STATE_OWNED" />
            <el-option label="民营企业" value="PRIVATE" />
            <el-option label="社会团体" value="ASSOCIATION" />
          </el-select>
        </el-form-item>
        <el-form-item label="统一社会信用代码">
          <el-input v-model="form.creditCode" placeholder="如：11330102MB5566778E" />
        </el-form-item>
        <el-form-item label="法定代表人">
          <el-input v-model="form.legalPerson" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="form.contactMobile" />
        </el-form-item>
        <el-form-item label="联系邮箱">
          <el-input v-model="form.contactEmail" />
        </el-form-item>
        <el-form-item label="成立日期">
          <el-date-picker v-model="form.establishedAt" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="管理员账号">
          <el-col :span="11"><el-input v-model="form.adminUsername" placeholder="登录账号" /></el-col>
          <el-col :span="2" style="text-align: center">—</el-col>
          <el-col :span="11"><el-input v-model="form.adminName" placeholder="姓名" /></el-col>
        </el-form-item>
        <el-form-item v-if="!form.id" label="初始密码">
          <el-input v-model="form.adminPassword" placeholder="留空则使用默认密码" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 配额分配 -->
    <el-dialog v-model="quotaDlg" title="机构配额分配" width="520">
      <el-form :model="quotaForm" label-width="120px" size="small">
        <el-form-item label="机构">{{ quotaForm.institutionName }}</el-form-item>
        <el-form-item label="统计期">
          <el-input v-model="quotaForm.period" placeholder="2026-09" />
        </el-form-item>
        <el-form-item label="配额（词元）">
          <el-input-number v-model="quotaForm.quotaTokens" :min="0" :step="10000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="赠送（词元）">
          <el-input-number v-model="quotaForm.freeTokens" :min="0" :step="1000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="生效区间">
          <el-date-picker
            v-model="quotaRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="生效日"
            end-placeholder="到期日"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="quotaForm.reason" type="textarea" :rows="2" placeholder="如：入驻第 3 步配额下发" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="quotaDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitQuota">保存</el-button>
      </template>
    </el-dialog>

    <!-- 管理员交接 -->
    <el-dialog v-model="adminDlg" title="企业管理员交接" width="460">
      <el-form :model="adminForm" label-width="100px" size="small">
        <el-form-item label="机构">{{ adminForm.institutionName }}</el-form-item>
        <el-form-item label="原管理员">{{ adminForm.oldName || '—' }}</el-form-item>
        <el-form-item label="新账号" required>
          <el-input v-model="adminForm.username" placeholder="新管理员登录账号（不存在则自动开户）" />
        </el-form-item>
        <el-form-item label="新管理员" required>
          <el-input v-model="adminForm.name" placeholder="姓名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="adminDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitAdmin">确认交接</el-button>
      </template>
    </el-dialog>

    <!-- 资源池扩容 -->
    <el-dialog v-model="poolDlg" title="资源池扩容 / 参数调整" width="520">
      <el-form :model="poolForm" label-width="130px" size="small">
        <el-form-item label="统计期">
          <el-input v-model="poolForm.period" placeholder="2026-09" />
        </el-form-item>
        <el-form-item label="总量（词元）">
          <el-input-number v-model="poolForm.tokenTotal" :min="0" :step="100000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="专家席位">
          <el-input-number v-model="poolForm.expertSeats" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="技能席位">
          <el-input-number v-model="poolForm.skillSeats" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="预警阈值(%)">
          <el-input-number v-model="poolForm.warnThreshold" :min="0" :max="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单价（¥/词元）">
          <el-input-number v-model="poolForm.unitPrice" :min="0" :step="0.000001" :precision="6" style="width: 100%" />
        </el-form-item>
        <el-form-item label="到期日">
          <el-date-picker v-model="poolForm.expireAt" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="poolDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitPool">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import {
  listInstitutions, createInstitution, updateInstitution, institutionAction, transferInstitutionAdmin,
  getResourcePool, saveResourcePool, listOrgQuotas, createOrgQuota,
  freezeOrgQuota, unfreezeOrgQuota,
  type Institution, type OrgQuota, type ResourcePool
} from '@/api/org'

const period = ref(currentPeriod())
const rows = ref<Institution[]>([])
const quotas = ref<OrgQuota[]>([])
const pool = ref<ResourcePool | null>(null)
const loading = ref(false)
const saving = ref(false)

function currentPeriod() {
  const d = new Date()
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
}

function fmt(n?: number) {
  return (n ?? 0).toLocaleString('zh-CN')
}

function quotaOf(id?: number) {
  return quotas.value.find((q) => q.institutionId === id)
}

const ORG_TYPES: Record<string, string> = {
  GOVERNMENT: '政府机关', INSTITUTION: '事业单位', STATE_OWNED: '国有企业',
  PRIVATE: '民营企业', ASSOCIATION: '社会团体'
}
const STATUS: Record<string, string> = { ACTIVE: '正常', SUSPENDED: '已停用', CLOSED: '已注销' }
function orgTypeText(v?: string) { return ORG_TYPES[v || ''] || v || '—' }
function statusText(v?: string) { return STATUS[v || ''] || v || '—' }
function statusType(v?: string) {
  if (v === 'ACTIVE') return 'success'
  if (v === 'SUSPENDED') return 'warning'
  return 'info'
}

async function reloadAll() {
  loading.value = true
  try {
    const [inst, qs, pl] = await Promise.all([
      listInstitutions().catch(() => [] as Institution[]),
      listOrgQuotas(period.value).catch(() => [] as OrgQuota[]),
      getResourcePool(period.value).catch(() => null)
    ])
    rows.value = inst || []
    quotas.value = qs || []
    pool.value = pl
  } catch (e: unknown) {
    ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}
onMounted(reloadAll)

// ---------------------------------------------------------------- 机构表单
const dlg = ref(false)
const form = ref<Partial<Institution> & { adminPassword?: string }>({})

function openDlg(row?: Institution) {
  form.value = row ? { ...row } : { orgType: 'GOVERNMENT' }
  dlg.value = true
}

async function submit() {
  if (!form.value.name || !form.value.code) {
    ElMessage.warning('机构名称与编码必填')
    return
  }
  saving.value = true
  try {
    if (form.value.id) {
      await updateInstitution(form.value.id, form.value)
      ElMessage.success('已保存')
    } else {
      await createInstitution(form.value)
      ElMessage.success('机构已创建（并同步开通企业管理员账号）')
    }
    dlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 配额
const quotaDlg = ref(false)
const quotaRange = ref<string[]>([])
const quotaForm = ref<Partial<OrgQuota> & { institutionName?: string }>({})

function openQuotaDlg(row: Institution) {
  const q = quotaOf(row.id)
  quotaForm.value = {
    institutionId: row.id,
    institutionName: row.name,
    period: period.value,
    quotaTokens: q?.quotaTokens ?? 0,
    freeTokens: q?.freeTokens ?? 0,
    reason: ''
  }
  quotaRange.value = q?.effectiveFrom && q.effectiveTo ? [q.effectiveFrom, q.effectiveTo] : []
  quotaDlg.value = true
}

async function submitQuota() {
  saving.value = true
  try {
    await createOrgQuota({
      institutionId: quotaForm.value.institutionId,
      period: quotaForm.value.period,
      quotaTokens: quotaForm.value.quotaTokens,
      freeTokens: quotaForm.value.freeTokens,
      effectiveFrom: quotaRange.value?.[0],
      effectiveTo: quotaRange.value?.[1],
      reason: quotaForm.value.reason
    })
    ElMessage.success('配额已分配')
    quotaDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '配额分配失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 交接
const adminDlg = ref(false)
const adminForm = ref<{ institutionId?: number; institutionName?: string; oldName?: string; username: string; name: string }>(
  { username: '', name: '' }
)

function openAdminDlg(row: Institution) {
  adminForm.value = {
    institutionId: row.id, institutionName: row.name, oldName: row.adminName, username: '', name: ''
  }
  adminDlg.value = true
}

async function submitAdmin() {
  if (!adminForm.value.username || !adminForm.value.name) {
    ElMessage.warning('新管理员账号与姓名必填')
    return
  }
  saving.value = true
  try {
    await transferInstitutionAdmin(adminForm.value.institutionId!, adminForm.value.username, adminForm.value.name)
    ElMessage.success('交接完成')
    adminDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '交接失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 资源池
const poolDlg = ref(false)
const poolForm = ref<Partial<ResourcePool>>({})

function openPoolDlg() {
  poolForm.value = { ...(pool.value || {}), period: period.value }
  poolDlg.value = true
}

async function submitPool() {
  saving.value = true
  try {
    await saveResourcePool(poolForm.value)
    ElMessage.success('资源池已更新')
    poolDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '资源池保存失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 状态流转
const ACTION_TEXT: Record<string, string> = {
  suspend: '停用', resume: '恢复', close: '注销', freeze: '冻结配额', unfreeze: '解冻配额'
}

async function onAction(row: Institution, cmd: string) {
  if (cmd === 'close') {
    try {
      await ElMessageBox.confirm(`注销后机构不可恢复，确认注销「${row.name}」？`, '危险操作', {
        type: 'warning', confirmButtonText: '确认注销', cancelButtonText: '取消'
      })
    } catch { return }
  }
  try {
    if (cmd === 'freeze') await freezeOrgQuota(row.id!, '管理端冻结')
    else if (cmd === 'unfreeze') await unfreezeOrgQuota(row.id!, '管理端解冻')
    else await institutionAction(row.id!, cmd, '管理端操作')
    ElMessage.success(ACTION_TEXT[cmd] + '成功')
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, ACTION_TEXT[cmd] + '失败'))
  }
}

/** 后端业务错误：HTTP 200 + code != 0，错误信息在 message */
function apiMsg(e: unknown, fallback: string) {
  const d = (e as { response?: { data?: { message?: string } } })?.response?.data
  return d?.message || fallback
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; }
.inst-name { font-weight: 600; }
.muted { color: #909399; }
.small { font-size: 12px; line-height: 1.3; }
</style>
