<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="组织与员工"
      description="企业管理员维护本机构部门树（最多 5 层）与员工名册。新增员工会自动开通登录账号并授予机构成员角色；支持按部门编码批量导入，导入结果逐行返回成功/失败原因。"
      style="margin-bottom: 12px"
    />

    <!-- 机构作用域：机构成员固定本单位；租户管理员 / 平台管理员可切换 -->
    <div class="scope-bar">
      <span class="scope-label">当前机构</span>
      <el-select
        v-if="instOptions.length > 1"
        v-model="instId"
        size="small"
        style="width: 280px"
        placeholder="选择机构"
        @change="reloadAll"
      >
        <el-option
          v-for="i in instOptions"
          :key="i.id"
          :label="i.name ? `${i.name}（${i.code || i.id}）` : `机构 ${i.id}`"
          :value="i.id"
        />
      </el-select>
      <el-tag v-else-if="instOptions.length === 1" size="small" effect="plain" type="info">
        {{ instOptions[0].name }}（{{ instOptions[0].code || instOptions[0].id }}）
      </el-tag>
      <span v-else class="muted small">暂无可用机构</span>

      <el-tag v-if="scopeKind === 'TENANT'" size="small" effect="plain" type="warning">
        租户管理员视角：可查看并维护本租户全部机构
      </el-tag>
      <el-tag v-else-if="scopeKind === 'PLATFORM'" size="small" effect="plain" type="info">
        平台管理员视角：跨租户只读
      </el-tag>
      <el-tag v-else-if="!canWrite" size="small" effect="plain" type="info">
        只读：组织维护由企业管理员执行
      </el-tag>
    </div>

    <el-empty
      v-if="noInstitution"
      description="当前账号尚未关联任何机构，无法展示部门与员工。请联系本租户管理员完成机构入驻。"
    />

    <el-row v-if="!noInstitution" :gutter="12">
      <!-- 部门树 -->
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>部门（{{ deptTotal }}，最深 {{ maxDepth }} 层 / 上限 {{ depthLimit }}）</span>
              <div>
                <el-button text type="primary" size="small" :loading="loading" @click="reloadAll">刷新</el-button>
                <el-button v-if="canWrite" type="primary" size="small" @click="openDeptDlg()">新增部门</el-button>
              </div>
            </div>
          </template>
          <el-tree
            v-loading="loading"
            :data="tree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            default-expand-all
            :expand-on-click-node="false"
          >
            <template #default="{ data }">
              <div class="tree-node">
                <span>{{ data.name }}</span>
                <el-tag size="small" effect="plain" type="info">{{ data.code }}</el-tag>
                <span class="muted small">L{{ data.level }}</span>
                <span class="muted small">{{ data.memberCount ?? 0 }} 人</span>
                <span class="muted small">负责人：{{ data.leaderName || '未设置' }}</span>
                <span v-if="canWrite" class="ops">
                  <el-button text type="primary" size="small" @click.stop="openDeptDlg(data, data.id)">加下级</el-button>
                  <el-button text type="primary" size="small" @click.stop="openDeptDlg(data)">编辑</el-button>
                  <el-button text type="danger" size="small" @click.stop="removeDept(data)">删除</el-button>
                </span>
              </div>
            </template>
          </el-tree>
        </el-card>
      </el-col>

      <!-- 员工 -->
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>员工名册（{{ memberTotal }}）</span>
              <div>
                <el-button v-if="canWrite" text type="primary" size="small" @click="importDlg = true">批量导入</el-button>
                <el-button text type="primary" size="small" :loading="mLoading" @click="loadMembers">刷新</el-button>
                <el-button v-if="canWrite" type="primary" size="small" @click="openMemberDlg()">新增员工</el-button>
              </div>
            </div>
          </template>

          <div class="filters">
            <el-input v-model="keyword" placeholder="姓名 / 账号 / 工号" size="small" clearable style="width: 200px" @keyup.enter="loadMembers" />
            <el-select v-model="filterDept" placeholder="全部部门" size="small" clearable style="width: 170px" @change="loadMembers">
              <el-option v-for="d in flatDepts" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
            <el-button size="small" @click="loadMembers">查询</el-button>
          </div>

          <el-table v-loading="mLoading" :data="members" stripe height="460">
            <el-table-column label="姓名" width="100">
              <template #default="{ row }">{{ row.name }}</template>
            </el-table-column>
            <el-table-column label="账号" prop="username" width="120" />
            <el-table-column label="部门" min-width="110">
              <template #default="{ row }">{{ row.departmentName || '—' }}</template>
            </el-table-column>
            <el-table-column label="工号" prop="employeeNo" width="100" />
            <el-table-column label="岗位" prop="jobTitle" min-width="110" show-overflow-tooltip />
            <el-table-column label="手机" prop="mobile" width="120" />
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canWrite" text type="primary" size="small" @click="openMemberDlg(row)">编辑</el-button>
                <el-button v-if="canWrite" text type="primary" size="small" @click="openBalanceDlg(row)">假期</el-button>
                <span v-if="!canWrite" class="muted small">—</span>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="page"
            :page-size="size"
            :total="memberTotal"
            layout="prev, pager, next, total"
            size="small"
            style="margin-top: 8px"
            @current-change="loadMembers"
          />
        </el-card>
      </el-col>
    </el-row>

    <!-- 部门表单 -->
    <el-dialog v-model="deptDlg" :title="deptForm.id ? '编辑部门' : '新增部门'" width="480">
      <el-form :model="deptForm" label-width="100px" size="small">
        <el-form-item label="部门名称" required><el-input v-model="deptForm.name" /></el-form-item>
        <el-form-item label="部门编码" required><el-input v-model="deptForm.code" placeholder="如：SCJG-BGS" /></el-form-item>
        <el-form-item label="上级部门">
          <el-tree-select
            v-model="deptForm.parentId"
            :data="tree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            check-strictly
            :render-after-expand="false"
            placeholder="根节点（留空为一级部门）"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="负责人 ID">
          <el-input-number v-model="deptForm.leaderUserId" :min="0" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="负责人姓名"><el-input v-model="deptForm.leaderName" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="deptForm.sort" :min="0" style="width: 100%" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="deptDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitDept">保存</el-button>
      </template>
    </el-dialog>

    <!-- 员工表单 -->
    <el-dialog v-model="memberDlg" :title="memberForm.id ? '编辑员工' : '新增员工（自动开户）'" width="500">
      <el-form :model="memberForm" label-width="100px" size="small">
        <el-form-item label="姓名" required><el-input v-model="memberForm.name" /></el-form-item>
        <el-form-item label="登录账号" required>
          <el-input v-model="memberForm.username" :disabled="!!memberForm.id" placeholder="不存在时自动开通" />
        </el-form-item>
        <el-form-item label="所属部门">
          <el-tree-select
            v-model="memberForm.departmentId"
            :data="tree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            check-strictly
            :render-after-expand="false"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="工号"><el-input v-model="memberForm.employeeNo" /></el-form-item>
        <el-form-item label="岗位"><el-input v-model="memberForm.jobTitle" /></el-form-item>
        <el-form-item label="手机"><el-input v-model="memberForm.mobile" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="memberForm.email" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="memberDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitMember">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入 -->
    <el-dialog v-model="importDlg" title="批量导入员工" width="640">
      <el-alert
        type="info"
        :closable="false"
        title="每行一条，字段用逗号分隔：姓名,账号,工号,岗位,手机,部门编码"
        description="部门编码必须已存在，否则该行失败并返回原因。首行可为表头（含「姓名」时自动跳过）。"
        style="margin-bottom: 8px"
      />
      <el-input v-model="importText" type="textarea" :rows="10" placeholder="张岚,scjg_zhang,SC2020001,办公室主任,13805750001,SCJG-BGS" />
      <template #footer>
        <el-button size="small" @click="importDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 假期额度 -->
    <el-dialog v-model="balanceDlg" title="设置假期额度" width="420">
      <el-form :model="balanceForm" label-width="100px" size="small">
        <el-form-item label="员工">{{ balanceForm.name }}</el-form-item>
        <el-form-item label="假种编码">
          <el-select v-model="balanceForm.leaveTypeCode" style="width: 100%">
            <el-option label="年假 ANNUAL" value="ANNUAL" />
            <el-option label="病假 SICK" value="SICK" />
            <el-option label="事假 CASUAL" value="CASUAL" />
            <el-option label="婚假 MARRIAGE" value="MARRIAGE" />
            <el-option label="产假 MATERNITY" value="MATERNITY" />
            <el-option label="调休 COMP" value="COMP" />
          </el-select>
        </el-form-item>
        <el-form-item label="年度">
          <el-input-number v-model="balanceForm.year" :min="2000" :max="2100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="额度（天）">
          <el-input-number v-model="balanceForm.totalDays" :min="0" :step="0.5" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="balanceDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitBalance">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getOrgScope, getDepartments, createDepartment, updateDepartment, deleteDepartment,
  listMembers, createMember, updateMember, importMembers, upsertLeaveBalance,
  type OrgDepartment, type OrgMember, type SelectableInstitution
} from '@/api/org'

const loading = ref(false)
const mLoading = ref(false)
const saving = ref(false)
const tree = ref<OrgDepartment[]>([])
const deptTotal = ref(0)
const depthLimit = ref(5)
const maxDepth = ref(0)
const members = ref<OrgMember[]>([])
const memberTotal = ref(0)
const keyword = ref('')
const filterDept = ref<number | null>(null)
const page = ref(1)
const size = 50

// ---------------------------------------------------------------- 机构作用域
// 机构成员只有一家机构（选择器隐藏）；租户管理员可在本租户内切换；平台管理员跨租户只读。
const instOptions = ref<SelectableInstitution[]>([])
const instId = ref<number | null>(null)
const canWrite = ref(false)
const scopeKind = ref<string>('ORG')
/** 无机构时给出空态提示，而不是抛 403 报错横幅。 */
const noInstitution = ref(false)

const flatDepts = computed(() => {
  const out: OrgDepartment[] = []
  const walk = (ns: OrgDepartment[]) => (ns || []).forEach((n) => { out.push(n); walk(n.children || []) })
  walk(tree.value)
  return out
})

async function loadDepts() {
  loading.value = true
  try {
    const d = await getDepartments(instId.value)
    tree.value = d?.tree || []
    deptTotal.value = d?.total ?? flatDepts.value.length
    depthLimit.value = d?.depthLimit ?? 5
    maxDepth.value = d?.maxDepth ?? 0
  } catch (e: unknown) {
    ElMessage.error('部门加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

async function loadMembers() {
  mLoading.value = true
  try {
    const d = await listMembers({
      page: page.value, size,
      keyword: keyword.value || undefined,
      departmentId: filterDept.value || undefined
    }, instId.value)
    members.value = d?.items || []
    memberTotal.value = d?.total ?? members.value.length
  } catch (e: unknown) {
    ElMessage.error('员工加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    mLoading.value = false
  }
}

async function reloadAll() { await loadDepts(); await loadMembers() }

/**
 * 先解析机构作用域，再拉数据。
 *
 * <p>此前直接拉数据，导致「菜单能进、接口全 403」时页面只剩两条错误横幅。
 * 现在把作用域解析前置：无机构时走空态提示；能写才渲染维护按钮。</p>
 */
async function init() {
  try {
    const s = await getOrgScope()
    instOptions.value = s?.items || []
    canWrite.value = !!s?.canWrite
    scopeKind.value = s?.scope || 'ORG'
    noInstitution.value = instOptions.value.length === 0
    if (instId.value == null) {
      instId.value = s?.boundInstitutionId ?? instOptions.value[0]?.id ?? null
    }
  } catch (e: unknown) {
    noInstitution.value = true
    ElMessage.error('机构信息加载失败：' + ((e as Error)?.message || '后端异常'))
    return
  }
  if (noInstitution.value) return
  await reloadAll()
}

onMounted(init)

function apiMsg(e: unknown, fallback: string) {
  return (e as { response?: { data?: { message?: string } } })?.response?.data?.message || fallback
}

// ---------------------------------------------------------------- 部门
const deptDlg = ref(false)
const deptForm = ref<Partial<OrgDepartment>>({})

function openDeptDlg(row?: OrgDepartment, asChildOf?: number) {
  if (row && asChildOf) {
    deptForm.value = { parentId: row.id, sort: 10 }
  } else if (row) {
    deptForm.value = { ...row }
  } else {
    deptForm.value = { parentId: 0, sort: 10 }
  }
  deptDlg.value = true
}

async function submitDept() {
  if (!deptForm.value.name || !deptForm.value.code) {
    ElMessage.warning('部门名称与编码必填')
    return
  }
  saving.value = true
  try {
    if (deptForm.value.id) await updateDepartment(deptForm.value.id, deptForm.value)
    else await createDepartment(deptForm.value)
    ElMessage.success('已保存')
    deptDlg.value = false
    await loadDepts()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function removeDept(row: OrgDepartment) {
  try {
    await ElMessageBox.confirm(`确认删除部门「${row.name}」？存在子部门或成员时会被服务端拒绝。`, '删除部门', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消'
    })
  } catch { return }
  try {
    await deleteDepartment(row.id!)
    ElMessage.success('已删除')
    await loadDepts()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '删除失败'))
  }
}

// ---------------------------------------------------------------- 员工
const memberDlg = ref(false)
const memberForm = ref<Partial<OrgMember>>({})

function openMemberDlg(row?: OrgMember) {
  memberForm.value = row ? { ...row } : {}
  memberDlg.value = true
}

async function submitMember() {
  if (!memberForm.value.name || !memberForm.value.username) {
    ElMessage.warning('姓名与登录账号必填')
    return
  }
  saving.value = true
  try {
    if (memberForm.value.id) await updateMember(memberForm.value.id, memberForm.value)
    else await createMember(memberForm.value)
    ElMessage.success(memberForm.value.id ? '已保存' : '员工已新增并开通账号')
    memberDlg.value = false
    await loadMembers()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 导入
const importDlg = ref(false)
const importText = ref('')

async function submitImport() {
  const lines = importText.value.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!lines.length) { ElMessage.warning('请输入导入内容'); return }
  const rows = lines
    .filter((l) => !l.includes('姓名'))
    .map((l) => {
      const p = l.split(/[,，\t]/).map((s) => s.trim())
      return { name: p[0], username: p[1], employeeNo: p[2], jobTitle: p[3], mobile: p[4], departmentCode: p[5] }
    })
  saving.value = true
  try {
    const r = await importMembers(rows, instId.value)
    const failed = (r?.failed as unknown[]) || []
    ElMessage.success(`导入完成：成功 ${r?.success ?? 0} 条，失败 ${r?.failedCount ?? failed.length} 条`)
    if (failed.length) {
      ElMessageBox.alert(
        failed.slice(0, 20).map((f) => JSON.stringify(f)).join('\n'),
        '失败明细（最多 20 条）',
        { confirmButtonText: '关闭' }
      )
    }
    importDlg.value = false
    await reloadAll()
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '导入失败'))
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 假期额度
const balanceDlg = ref(false)
const balanceForm = ref<{ userId?: number; name?: string; leaveTypeCode: string; year: number; totalDays: number }>(
  { leaveTypeCode: 'ANNUAL', year: new Date().getFullYear(), totalDays: 10 }
)

function openBalanceDlg(row: OrgMember) {
  balanceForm.value = {
    userId: row.userId, name: row.name,
    leaveTypeCode: 'ANNUAL', year: new Date().getFullYear(), totalDays: 10
  }
  balanceDlg.value = true
}

async function submitBalance() {
  saving.value = true
  try {
    await upsertLeaveBalance({ ...balanceForm.value }, instId.value)
    ElMessage.success('额度已设置')
    balanceDlg.value = false
  } catch (e: unknown) {
    ElMessage.error(apiMsg(e, '设置失败'))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.filters { display: flex; gap: 8px; margin-bottom: 8px; }
.tree-node { display: flex; align-items: center; gap: 6px; width: 100%; font-size: 13px; }
.tree-node .ops { margin-left: auto; opacity: 0; transition: opacity .15s; }
.tree-node:hover .ops { opacity: 1; }
.muted { color: #909399; }
.small { font-size: 12px; }
</style>
