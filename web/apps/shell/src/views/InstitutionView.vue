<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="机构管理"
      description="租户管理员在此维护下属机构（企业/单位），分配机构词元配额，并跟踪每家机构的 8 步入驻进度。配额受资源池总量约束，超额分配会被服务端拒绝。已注销机构不在此列出——注销是不可逆终态，机构将退出全部运营面，档案随「删除本租户」一并级联清理。"
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
      <el-alert
        v-if="pool && !pool.delivered"
        type="warning"
        :closable="false"
        show-icon
        title="本周期资源池尚未交付"
        description="机构配额只能从资源池里分配。请先点右上「池扩容 / 调参」交付本周期资源池（总量 > 0）；在此之前任何机构配额分配都会被服务端拒绝（FR-C2）。"
        style="margin-bottom: 8px"
      />
      <el-descriptions :column="5" border size="small" v-if="pool">
        <el-descriptions-item label="总量（词元）">{{ fmt(pool.tokenTotal) }}</el-descriptions-item>
        <el-descriptions-item label="已分配">{{ fmt(pool.allocatedTokens ?? pool.tokenAllocated) }}</el-descriptions-item>
        <el-descriptions-item label="可分配">
          {{ fmt(pool.allocatableTokens) }}
          <span v-if="pool.allocRatio != null" class="muted small">（已占 {{ pool.allocRatio }}%）</span>
        </el-descriptions-item>
        <el-descriptions-item label="已用">{{ fmt(pool.tokenUsed) }}</el-descriptions-item>
        <el-descriptions-item label="预警阈值">{{ pool.warnThreshold ?? '—' }}%</el-descriptions-item>
        <el-descriptions-item label="专家席位">{{ pool.expertUsed ?? 0 }} / {{ pool.expertSeats ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="技能席位">{{ pool.skillUsed ?? 0 }} / {{ pool.skillSeats ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="单价（¥/词元）">{{ pool.unitPrice ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="到期日">{{ pool.expireAt || '—' }}</el-descriptions-item>
        <el-descriptions-item label="统计期">{{ pool.period || period }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="暂无资源池数据" :image-size="48" />
    </el-card>

    <!-- 机构列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>机构列表（{{ rows.length }}）</span>
          <div class="header-ops">
            <!--
              状态筛选：**没有「已注销」这一项**。

              注销是不可逆终态，本清单的默认口径就是「已注销机构不出现」（后端
              `/tenant/institutions` 默认排除 CLOSED）。既然刻意不给用户看，就不该在
              筛选器里再做一个能把它们捞回来的入口 —— 那会让「注销后怎么还能看到」复现。
              需要看档案是运维/审计场景，走接口的 includeClosed=true，不占本页控件。
            -->
            <el-select
              v-model="statusFilter"
              size="small"
              style="width: 130px"
              @change="reloadAll"
            >
              <el-option label="全部在册" value="" />
              <el-option label="正常" value="ACTIVE" />
              <el-option label="已停用" value="SUSPENDED" />
            </el-select>
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
                  <!--
                    「注销」= 置为 CLOSED 状态（可留痕、可查）；「申请删除」= 真删，且必须过上一级审核。
                    两者是不同的事，故意分开放，避免被当成同一操作。

                    已注销行必须**禁用「申请删除」**：CLOSED 是不可达档案 —— 作用域解析对非 ACTIVE
                    机构一律 404，所以点下去必然报「机构不存在或已停用」（用户实测：报的就是
                    机构 id 162 那条）。正确清理路径只有「删租户」的级联；给出这个按钮等于
                    把一条注定失败的路摆给用户走。正常清单里也不会出现 CLOSED 行（后端默认排除），
                    这里禁用是第二道闸门（深链 / 显式 status=CLOSED 时仍然拦得住）。
                  -->
                  <el-dropdown-item
                    command="delete-request"
                    divided
                    :disabled="row.status === 'CLOSED'"
                  >
                    {{ row.status === 'CLOSED' ? '申请删除（已注销，不可直接删）' : '申请删除' }}
                  </el-dropdown-item>
                  <!-- 禁用原因就地说明（不额外挂 tooltip：下拉项里的 tooltip 在 Element Plus
                       的 popper 嵌套下不可靠，用户点了才发现是空的，反而更像坏了）。 -->
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
          <el-select v-model="form.orgType" style="width: 100%" placeholder="请选择机构类型">
            <el-option v-for="t in orgTypes" :key="t.code" :label="t.label" :value="t.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="统一社会信用代码">
          <el-input v-model="form.creditCode" placeholder="18 位统一社会信用代码（GB 32100-2015），如 91330102MA2G10001C" />
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
          <el-input v-model="quotaForm.period" placeholder="留空 = 服务端当前统计期" />
        </el-form-item>
        <el-form-item label="可分配余量">
          <span v-if="!quotaCeiling" class="warn-text">
            本周期资源池尚未交付，无法分配配额。
            <el-button text type="primary" size="small" @click="gotoPool">去交付资源池</el-button>
          </span>
          <span v-else>
            其它机构已占 <b>{{ fmt(quotaCeiling.others) }}</b>，本次最多可分配
            <b>{{ fmt(quotaCeiling.max) }}</b> 词元
          </span>
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
        <el-button type="primary" size="small" :loading="saving" :disabled="!quotaCeiling" @click="submitQuota">保存</el-button>
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
  freezeOrgQuota, unfreezeOrgQuota, listInstitutionTypes, requestInstitutionDelete,
  type Institution, type OrgQuota, type ResourcePool, type InstitutionType
} from '@/api/org'

import { tenantState, loadTenantScope } from '@/api/tenantScope'
import { loadInstitutionScope } from '@/api/institutionScope'

/**
 * 统计期：唯一权威来自服务端（`/tenant/scope` 的 `currentPeriod`）。
 *
 * <p>此前本页自己用 `new Date()` 推导 —— 一旦浏览器与服务器时钟 / 时区不一致，
 * 就会去查一个并不存在的周期，页面表现为「资源池尚未交付」而其实是查错了月份。
 * 留空时不下发该参数，由后端 `Vals.nowPeriod()` 按同一口径兜底；
 * 拿到资源池响应后再用服务端回填的真实 `period` 校准一次。</p>
 */
const period = ref(tenantState.currentPeriod.value)
const rows = ref<Institution[]>([])
const quotas = ref<OrgQuota[]>([])
const pool = ref<ResourcePool | null>(null)
const loading = ref(false)
const saving = ref(false)
/**
 * 机构状态筛选。空串 = 全部在册（后端默认口径，已注销不在其中）；只提供 正常 / 已停用两档，
 * 刻意**不提供「已注销」** —— 注销后该机构就该从本页消失，给个筛选项能把它捞回来等于没修。
 */
const statusFilter = ref('')

function fmt(n?: number) {
  return (n ?? 0).toLocaleString('zh-CN')
}

function quotaOf(id?: number) {
  return quotas.value.find((q) => q.institutionId === id)
}

const STATUS: Record<string, string> = { ACTIVE: '正常', SUSPENDED: '已停用', CLOSED: '已注销' }

/**
 * 机构类型字典：后端 `/tenant/institution-types` 是唯一权威（五类 GOVERNMENT/ENTERPRISE/
 * INSTITUTION/ASSOCIATION/OTHER，顺序即展示顺序）。前端不再硬编一份，避免「同一判定点
 * 两处实现」——此前前端硬编 STATE_OWNED/PRIVATE 而后端不认识、库里最多的 ENTERPRISE 又选不到。
 */
const orgTypes = ref<InstitutionType[]>([])

function orgTypeText(v?: string) {
  const t = orgTypes.value.find((x) => x.code === v)
  if (t) return t.label
  // 取不到时原样显示裸码（便于发现脏数据），为空才显示 —
  return v || '—'
}
function statusText(v?: string) { return STATUS[v || ''] || v || '—' }
function statusType(v?: string) {
  if (v === 'ACTIVE') return 'success'
  if (v === 'SUSPENDED') return 'warning'
  return 'info'
}

async function reloadAll() {
  loading.value = true
  try {
    const [inst, qs, pl, types] = await Promise.all([
      // 机构清单**不再吞错**：`.catch(() => [])` 会把「403 / 500 等失败信封」渲染成一张空表，
      // 用户看到的是「数据没了」而不是「加载失败」——失败必须可见（铁律 #2/#3）。
      // 状态筛选走服务端（口径唯一在后端 InstitutionStatus），前端不再自己过滤一遍。
      listInstitutions(statusFilter.value ? { status: statusFilter.value } : undefined),
      listOrgQuotas(period.value).catch(() => [] as OrgQuota[]),
      getResourcePool(period.value).catch(() => null),
      listInstitutionTypes().catch(() => [] as InstitutionType[])
    ])
    rows.value = inst || []
    quotas.value = qs || []
    pool.value = pl
    orgTypes.value = types || []
    // 用服务端回填的真实周期校准本页展示（本地推导已废弃）
    if (pl?.period) period.value = pl.period
  } catch (e: unknown) {
    ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

/**
 * 同步**全局作用域态**（顶部「租户 / 机构」选择器 + 「机构 N」计数）。
 *
 * <p>本页的本页表格由 {@link reloadAll} 负责，但顶部两个选择器读的是 `tenantState` /
 * `institutionState` —— 它们是模块级全局态，<b>只在登录时 load 一次</b>。于是本页做了
 * 「新增机构 / 注销机构」之后，表格是新的、顶部下拉还是旧的：新机构选不到、已注销的还挂在
 * 列表里、租户后面的「机构 N」也不动，用户必须按 F5 才看到真实状态（用户反馈：
 * 「修改数据的操作后页面数据必须立即刷新，无需手动干预」）。</p>
 *
 * <p>两个都要刷：`institutionState` 是机构下拉本身；`tenantState` 因为租户选项的文案是
 * `${name}（机构 N）`（`MainLayout.vue`），机构增删会改变 N。</p>
 *
 * <p>失败<b>不阻断</b>主流程：本页数据已经刷新成功，作用域态下次进入布局时会再拉一次；
 * 这里吞掉异常避免「明明操作成功却弹一个红色错误」。</p>
 */
async function refreshScopeStores() {
  await Promise.all([
    loadInstitutionScope().catch(() => undefined),
    loadTenantScope().catch(() => undefined)
  ])
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
    await refreshScopeStores()
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

/**
 * FR-C2 门禁的前置预览（与 `QuotaService.allocateOrgQuota` 同口径）：
 * `Σ其它机构配额 + 本次配额 ≤ 资源池总量`。
 *
 * <p>服务端本来就会拒绝超额，但用户看到的只是一句「分配超额」；
 * 这里把「其它机构已占 / 本次最多可分配」提前摆在表单上，
 * 并在提交前拦一次，避免必然失败的请求。资源池未交付时返回 null ⇒ 保存按钮禁用并给出直达入口。</p>
 */
const quotaCeiling = computed(() => {
  const pl = pool.value
  if (!pl || !pl.delivered) return null
  // 本页展示的周期与资源池周期不一致时，余量不可用（否则会拿另一个月的池子算出错误上限）
  if (quotaForm.value.period && pl.period && quotaForm.value.period !== pl.period) return null
  const allocated = pl.allocatedTokens ?? pl.tokenAllocated ?? 0
  const self = quotaForm.value.institutionId
    ? (quotaOf(quotaForm.value.institutionId)?.quotaTokens ?? 0)
    : 0
  const others = Math.max(0, allocated - self)
  return { others, max: Math.max(0, (pl.tokenTotal ?? 0) - others) }
})

/** 配额的来源是资源池：未交付时直接从配额弹窗跳到池交付弹窗，而不是只给一句报错。 */
function gotoPool() {
  quotaDlg.value = false
  openPoolDlg()
}

async function submitQuota() {
  const ceiling = quotaCeiling.value
  if (!ceiling) {
    ElMessage.warning('本周期资源池尚未交付，无法分配机构配额（请先交付资源池）')
    return
  }
  const want = quotaForm.value.quotaTokens ?? 0
  if (want > ceiling.max) {
    ElMessage.warning(`超出可分配余量：本次 ${fmt(want)}，最多可分配 ${fmt(ceiling.max)} 词元`)
    return
  }
  saving.value = true
  try {
    await createOrgQuota({
      institutionId: quotaForm.value.institutionId,
      // 留空即不下发，由服务端按同一口径补齐周期
      ...(quotaForm.value.period ? { period: quotaForm.value.period } : {}),
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
  if (cmd === 'delete-request') {
    // 已注销机构是**不可达档案**：作用域解析对非 ACTIVE 机构一律 404，请求必然失败在
    // 「机构不存在或已停用」（用户实测报的正是机构 id 162 那条）。这里提前拦下并说明
    // 正确路径，而不是放一发注定失败的请求出去让用户对着报错猜。
    // 正常清单里不会有 CLOSED 行（后端默认排除），这是第二道闸门（深链 / 显式 status=CLOSED）。
    if (row.status === 'CLOSED') {
      ElMessage.warning(
        `「${row.name}」已注销（不可逆终态），不能直接删除。` +
        '它的档案与残留数据随「删除本租户」一并级联清理（租户管理 → 申请删除本租户）。'
      )
      return
    }
    // 删除机构走「申请 → 上一级（租户管理员）审核 → 批准后才真删」。
    // 前端**不提供**直接删除：那是绕过审核闸门（需求：任何一层级的首次删除都需上一级审核）。
    let reason = ''
    try {
      const r = await ElMessageBox.prompt(
        `将提交「删除机构」申请：${row.name}\n\n` +
        '前提：该机构下已无部门、无员工（不满足会被服务端拒绝并说明停在哪一级）。\n' +
        '提交后需经上一级（租户管理员）审核，批准后才会真正删除。',
        '申请删除机构',
        { type: 'warning', confirmButtonText: '提交申请', cancelButtonText: '取消',
          inputPlaceholder: '删除理由（选填）', inputValue: '' }
      )
      reason = r.value || ''
    } catch { return }
    try {
      const res = await requestInstitutionDelete(row.id!, reason)
      ElMessage.success(res.hint || '已提交删除申请，等待上一级审核')
      await reloadAll()
      await refreshScopeStores()
    } catch (e: unknown) {
      ElMessage.error(apiMsg(e, '提交删除申请失败'))
    }
    return
  }
  if (cmd === 'close') {
    try {
      // 注销前把**后果**说清楚：机构会从机构管理 / 入驻进度 / 资源授权 / 费用分摊里消失，
      // 其成员也不再作为该机构的人员出现。此前只说「不可恢复」，用户注销后回头看这些页面
      // 还都能看到它，自然怀疑「注销没生效」。文案必须与事实同源（铁律 #1）。
      await ElMessageBox.confirm(
        `注销后机构不可恢复，确认注销「${row.name}」？\n\n` +
        '注销后该机构将退出运营面：机构管理、入驻进度、资源授权、费用分摊中不再显示，' +
        '其成员也不再归属到本机构。档案保留；如需彻底清理，请走「删除本租户」的级联。',
        '危险操作',
        { type: 'warning', confirmButtonText: '确认注销', cancelButtonText: '取消' }
      )
    } catch { return }
  }
  try {
    if (cmd === 'freeze') await freezeOrgQuota(row.id!, '管理端冻结')
    else if (cmd === 'unfreeze') await unfreezeOrgQuota(row.id!, '管理端解冻')
    else await institutionAction(row.id!, cmd, '管理端操作')
    ElMessage.success(ACTION_TEXT[cmd] + '成功')
    await reloadAll()
    await refreshScopeStores()
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
.card-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.header-ops { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.inst-name { font-weight: 600; }
.muted { color: #909399; }
.small { font-size: 12px; line-height: 1.3; }
.warn-text { color: #e6a23c; }
</style>
