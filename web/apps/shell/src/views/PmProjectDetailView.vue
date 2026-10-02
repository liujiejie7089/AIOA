<template>
  <div v-loading="loading">
    <el-page-header @back="router.push('/pm/projects')" style="margin-bottom: 12px">
      <template #content>
        <span style="font-weight: 500">{{ project?.name || '项目详情' }}</span>
        <el-tag v-if="project" size="small" effect="plain" style="margin-left: 8px">
          {{ PM_PROJECT_TYPE_LABEL[project.projectType] || project.projectType }}
        </el-tag>
        <el-tag v-if="project" :type="PM_PROJECT_STATUS_TAG[project.status] || 'info'" size="small" style="margin-left: 6px">
          {{ PM_PROJECT_STATUS_LABEL[project.status] || project.status }}
        </el-tag>
        <span v-if="project?.myRole" class="hint" style="margin-left: 8px">我的角色：{{ PM_PROJECT_ROLE_LABEL[project.myRole] || project.myRole }}</span>
      </template>
    </el-page-header>

    <el-tabs v-model="tab">
      <!-- ============================ 概览 ============================ -->
      <el-tab-pane label="概览" name="overview">
        <el-card shadow="never">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="项目编号">{{ project?.projectNo }}</el-descriptions-item>
            <el-descriptions-item label="负责人">{{ project?.ownerName || '—' }}</el-descriptions-item>
            <el-descriptions-item label="预算总额">{{ fmtMoney(project?.budgetAmount) }}</el-descriptions-item>
            <el-descriptions-item label="开始日期">{{ project?.startDate || '—' }}</el-descriptions-item>
            <el-descriptions-item label="结束日期">{{ project?.endDate || '—' }}</el-descriptions-item>
            <el-descriptions-item label="任务完成">{{ project?.taskDoneCount || 0 }} / {{ project?.taskCount || 0 }}</el-descriptions-item>
            <el-descriptions-item label="成员数">{{ project?.memberCount || 0 }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{ PM_PROJECT_TYPE_LABEL[project?.projectType || ''] || '—' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ PM_PROJECT_STATUS_LABEL[project?.status || ''] || '—' }}</el-descriptions-item>
          </el-descriptions>
          <p v-if="project?.description" class="desc">{{ project.description }}</p>

          <div style="margin-top: 12px">
            <el-select v-model="newStatus" size="small" placeholder="变更状态" style="width: 160px">
              <el-option v-for="s in PM_PROJECT_STATUS" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <el-button size="small" :disabled="!project?.canManage" @click="changeStatus">变更状态</el-button>
            <span v-if="!project?.canManage" class="hint" style="margin-left: 8px">仅项目负责人/项目经理或机构管理员及以上可操作</span>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ==================== 仓库（仅开发项目渲染） ==================== -->
      <el-tab-pane v-if="isDev" label="代码仓库" name="repos">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>已绑定仓库</span>
              <el-button v-if="project?.canManage" size="small" type="primary" @click="openBind">绑定仓库</el-button>
            </div>
          </template>
          <el-table :data="boundRepos" size="small">
            <el-table-column prop="name" label="仓库名" min-width="160" />
            <el-table-column label="路径" min-width="200">
              <template #default="{ row }">{{ [row.gitee_owner, row.gitee_repo].filter(Boolean).join('/') || '—' }}</template>
            </el-table-column>
            <el-table-column prop="default_branch" label="默认分支" width="120" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-link v-if="row.gitee_html_url" :href="row.gitee_html_url" target="_blank" type="primary" style="margin-right: 8px">打开</el-link>
                <el-button v-if="project?.canManage" size="small" text type="danger" @click="unbind(row)">解绑</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div style="padding: 16px 0" class="hint">尚未绑定代码仓库</div>
            </template>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============================ 任务 ============================ -->
      <el-tab-pane :label="`任务（${tasks.length}）`" name="tasks">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>任务列表</span>
              <el-button v-if="taskList?.canManage" size="small" type="primary" @click="openTask()">新建任务</el-button>
            </div>
          </template>
          <el-table :data="tasks" size="small">
            <el-table-column prop="title" label="任务" min-width="200" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="PM_TASK_STATUS_TAG[row.status] || 'info'" size="small">
                  {{ PM_TASK_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="优先级" width="90">
              <template #default="{ row }">{{ PM_TASK_PRIORITY_LABEL[row.priority || ''] || '—' }}</template>
            </el-table-column>
            <el-table-column label="负责人" width="120">
              <template #default="{ row }">{{ memberName(row.assigneeMemberId) }}</template>
            </el-table-column>
            <el-table-column label="进度" width="90">
              <template #default="{ row }">{{ row.progress ?? 0 }}%</template>
            </el-table-column>
            <!-- 仓库列只对开发项目展示（与后端返回口径一致：业务项目的 repoId 恒为 null） -->
            <el-table-column v-if="isDev" label="关联 Issue" width="130">
              <template #default="{ row }">{{ row.repoIssueNo || '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-select
                  :model-value="row.status"
                  size="small"
                  style="width: 110px"
                  @change="(v: string) => changeTaskStatus(row, v)"
                >
                  <el-option v-for="s in PM_TASK_STATUS" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
                <el-button size="small" text type="primary" @click="openTask(row)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeTask(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div style="padding: 16px 0" class="hint">暂无任务</div>
            </template>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============================ 成员 ============================ -->
      <el-tab-pane :label="`成员（${members.length}）`" name="members">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>项目成员</span>
              <el-button v-if="memberList?.canManage" size="small" type="primary" @click="openAddMember">添加成员</el-button>
            </div>
          </template>
          <el-alert
            v-if="memberList?.repoSyncNote"
            type="info"
            :closable="false"
            show-icon
            :title="memberList.repoSyncNote"
            style="margin-bottom: 8px"
          />
          <el-table :data="members" size="small">
            <el-table-column prop="name" label="姓名" width="120" />
            <el-table-column prop="employeeNo" label="工号" width="120" />
            <el-table-column prop="jobTitle" label="职务" width="140" />
            <el-table-column label="项目角色" width="150">
              <template #default="{ row }">
                <el-select
                  :model-value="row.roleCode"
                  size="small"
                  :disabled="!memberList?.canManage"
                  @change="(v: string) => changeMemberRole(row, v)"
                >
                  <el-option v-for="r in memberList?.roleOptions || []" :key="r.value" :label="r.label" :value="r.value" />
                </el-select>
              </template>
            </el-table-column>
            <!-- 仓库同步列只对开发项目展示 -->
            <el-table-column v-if="isDev" label="仓库同步" width="110">
              <template #default="{ row }">{{ PM_REPO_SYNC_STATUS_LABEL[row.repoSyncStatus || ''] || row.repoSyncStatus || '—' }}</template>
            </el-table-column>
            <el-table-column prop="joinedAt" label="加入时间" width="120" />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button v-if="memberList?.canManage" size="small" text type="danger" @click="removeMember(row)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ 文档 / 经费 / 合同：随批次 3/4 交付（不做假界面） ============ -->
      <el-tab-pane
        v-for="ph in placeholders"
        :key="ph.name"
        :label="ph.label"
        :name="ph.name"
      >
        <el-card shadow="never">
          <el-empty :description="ph.hint" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ==================== 绑定仓库 ==================== -->
    <el-dialog v-model="bindVisible" title="绑定代码仓库" width="560px">
      <el-select v-model="bindRepoId" placeholder="选择尚未归属任何项目的仓库" filterable style="width: 100%">
        <el-option v-for="r in bindableRepos" :key="r.id" :label="repoLabel(r)" :value="r.id" />
      </el-select>
      <div class="hint" style="margin-top: 8px">仅显示状态为「可用」且尚未归属任何项目的仓库。</div>
      <template #footer>
        <el-button size="small" @click="bindVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="binding" @click="doBind">绑定</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 新建/编辑任务 ==================== -->
    <el-dialog v-model="taskVisible" :title="taskForm.id ? '编辑任务' : '新建任务'" width="640px">
      <el-form :model="taskForm" label-width="110px" size="small">
        <el-form-item label="任务标题" required>
          <el-input v-model="taskForm.title" placeholder="请输入任务标题" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="taskForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="taskForm.assigneeMemberId" clearable filterable placeholder="选择本项目成员" style="width: 100%">
            <el-option v-for="m in members" :key="m.memberId" :label="m.name || String(m.memberId)" :value="m.memberId" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="taskForm.priority" style="width: 160px">
            <el-option v-for="p in PM_TASK_PRIORITIES" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="起止日期">
          <el-date-picker
            v-model="taskDateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="截止"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="进度">
          <el-input-number v-model="taskForm.progress" :min="0" :max="100" />
        </el-form-item>

        <!-- ============ 仓库关联：仅开发项目渲染（业务项目连字段都不出现） ============ -->
        <template v-if="isDev">
          <el-divider content-position="left">代码仓库关联（仅开发项目）</el-divider>
          <el-form-item label="关联仓库">
            <el-select v-model="taskForm.repoId" clearable placeholder="选择本项目已绑定的仓库" style="width: 100%">
              <el-option v-for="r in boundRepos" :key="r.id" :label="repoLabel(r)" :value="r.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="Issue 号">
            <el-input v-model="taskForm.repoIssueNo" placeholder="选择仓库后必填，如 #12 或 12" />
          </el-form-item>
          <el-form-item label="分支">
            <el-input v-model="taskForm.repoBranch" placeholder="选填，如 feature/login" />
          </el-form-item>
          <el-form-item label="提交 SHA">
            <el-input v-model="taskForm.repoCommitSha" placeholder="选填" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button size="small" @click="taskVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="savingTask" @click="saveTask">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 添加成员 ==================== -->
    <el-dialog v-model="memberVisible" title="添加项目成员" width="560px">
      <el-form label-width="90px" size="small">
        <el-form-item label="员工">
          <el-select v-model="newMemberId" filterable placeholder="从本企业在册员工中选择" style="width: 100%">
            <el-option
              v-for="c in candidates"
              :key="c.memberId"
              :label="`${c.name || c.memberId}${c.employeeNo ? '（' + c.employeeNo + '）' : ''}`"
              :value="c.memberId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="项目角色">
          <el-select v-model="newMemberRole" style="width: 100%">
            <el-option v-for="r in memberList?.roleOptions || []" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="memberVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="savingMember" @click="doAddMember">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  pmProjectDetail, pmChangeProjectStatus, pmBoundRepos, pmBindableRepos, pmBindRepo, pmUnbindRepo,
  pmTasks, pmCreateTask, pmUpdateTask, pmChangeTaskStatus, pmDeleteTask,
  pmMembers, pmMemberCandidates, pmAddMember, pmChangeMemberRole, pmRemoveMember, pmErrMsg,
  type PmProject, type PmRepo, type PmTask, type PmTaskList, type PmMember, type PmMemberList,
  type PmMemberCandidate
} from '@/api/pm'
import {
  PM_PROJECT_TYPE_LABEL, PM_PROJECT_STATUS, PM_PROJECT_STATUS_LABEL, PM_PROJECT_STATUS_TAG,
  PM_PROJECT_ROLE_LABEL, PM_TASK_STATUS, PM_TASK_STATUS_LABEL, PM_TASK_STATUS_TAG,
  PM_TASK_PRIORITIES, PM_TASK_PRIORITY_LABEL, PM_REPO_SYNC_STATUS_LABEL
} from '@/constants/permissions'

const route = useRoute()
const router = useRouter()
const projectId = Number(route.params.id)

const loading = ref(false)
const tab = ref('overview')
const project = ref<PmProject | null>(null)
const newStatus = ref('')

const boundRepos = ref<PmRepo[]>([])
const bindableRepos = ref<PmRepo[]>([])
const bindVisible = ref(false)
const bindRepoId = ref<number>()
const binding = ref(false)

const taskList = ref<PmTaskList | null>(null)
const tasks = ref<PmTask[]>([])
const taskVisible = ref(false)
const savingTask = ref(false)
const taskDateRange = ref<[string, string] | null>(null)
const taskForm = reactive<{
  id?: number; title: string; description: string; priority: string
  assigneeMemberId?: number | null; progress: number
  repoId?: number | null; repoIssueNo?: string; repoBranch?: string; repoCommitSha?: string
}>({
  title: '', description: '', priority: 'MEDIUM', assigneeMemberId: null, progress: 0
})

const memberList = ref<PmMemberList | null>(null)
const members = ref<PmMember[]>([])
const candidates = ref<PmMemberCandidate[]>([])
const memberVisible = ref(false)
const savingMember = ref(false)
const newMemberId = ref<number>()
const newMemberRole = ref('MEMBER')

/**
 * 类型是页面所有「配置面」的唯一开关。
 *
 * <p>业务项目：不渲染「代码仓库」页签、不渲染任务的仓库列与仓库关联表单。
 * 后端同样是这个口径（{@code ProjectTypeGuard}），前端隐藏不是安全边界。</p>
 */
const isDev = computed(() => project.value?.projectType === 'DEV')

const placeholders = [
  { name: 'docs', label: '文档', hint: '项目文档（企业级公共 / 项目专属文件夹）随批次 3 交付' },
  { name: 'budget', label: '经费', hint: '项目经费收支流水随批次 4 交付' },
  { name: 'contract', label: '合同', hint: '合同、收付款明细与里程碑随批次 4 交付' }
]

function fmtMoney(v?: number | string) {
  if (v === undefined || v === null || v === '') return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
}

function memberName(memberId?: number | null) {
  if (!memberId) return '—'
  return members.value.find((m) => m.memberId === memberId)?.name || String(memberId)
}

function repoLabel(r: PmRepo) {
  const path = [r.gitee_owner, r.gitee_repo].filter(Boolean).join('/')
  return r.name ? `${r.name}${path ? `（${path}）` : ''}` : (r.repo_name || String(r.id))
}

async function loadAll() {
  loading.value = true
  try {
    project.value = await pmProjectDetail(projectId)
    newStatus.value = project.value.status
    await Promise.all([loadRepos(), loadMembers(), loadTasks()])
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载项目详情失败'))
  } finally {
    loading.value = false
  }
}

async function loadRepos() {
  if (!isDev.value) {
    boundRepos.value = []
    return
  }
  try {
    boundRepos.value = await pmBoundRepos(projectId)
  } catch (e) {
    boundRepos.value = []
    ElMessage.warning(pmErrMsg(e, '加载已绑仓库失败'))
  }
}

async function loadTasks() {
  try {
    const res = await pmTasks(projectId)
    taskList.value = res
    tasks.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载任务失败'))
  }
}

async function loadMembers() {
  try {
    const res = await pmMembers(projectId)
    memberList.value = res
    members.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载成员失败'))
  }
}

async function changeStatus() {
  if (!newStatus.value) return
  try {
    project.value = await pmChangeProjectStatus(projectId, newStatus.value)
    ElMessage.success('状态已更新')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更状态失败'))
  }
}

// ---------------------------------------------------------------- 仓库
async function openBind() {
  bindVisible.value = true
  bindRepoId.value = undefined
  try {
    bindableRepos.value = await pmBindableRepos(projectId)
  } catch (e) {
    bindableRepos.value = []
    ElMessage.warning(pmErrMsg(e, '加载可绑定仓库失败'))
  }
}

async function doBind() {
  if (!bindRepoId.value) {
    ElMessage.warning('请选择要绑定的仓库')
    return
  }
  binding.value = true
  try {
    const res = await pmBindRepo(projectId, bindRepoId.value)
    boundRepos.value = res.boundRepos
    bindVisible.value = false
    ElMessage.success('仓库已绑定')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '绑定失败'))
  } finally {
    binding.value = false
  }
}

async function unbind(row: PmRepo) {
  try {
    await ElMessageBox.confirm(`确认解绑仓库「${repoLabel(row)}」？仅解除与本项目的关联，不删除仓库。`, '解绑仓库', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await pmUnbindRepo(projectId, row.id)
    boundRepos.value = res.boundRepos
    ElMessage.success('已解绑')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '解绑失败'))
  }
}

// ---------------------------------------------------------------- 任务
function openTask(row?: PmTask) {
  if (row) {
    Object.assign(taskForm, {
      id: row.id, title: row.title, description: row.description || '', priority: row.priority || 'MEDIUM',
      assigneeMemberId: row.assigneeMemberId ?? null, progress: row.progress ?? 0,
      repoId: row.repoId ?? null, repoIssueNo: row.repoIssueNo || '', repoBranch: row.repoBranch || '',
      repoCommitSha: row.repoCommitSha || ''
    })
    taskDateRange.value = row.startDate && row.dueDate ? [row.startDate, row.dueDate] : null
  } else {
    Object.assign(taskForm, {
      id: undefined, title: '', description: '', priority: 'MEDIUM', assigneeMemberId: null,
      progress: 0, repoId: null, repoIssueNo: '', repoBranch: '', repoCommitSha: ''
    })
    taskDateRange.value = null
  }
  taskVisible.value = true
}

async function saveTask() {
  if (!taskForm.title.trim()) {
    ElMessage.warning('请填写任务标题')
    return
  }
  const body = {
    title: taskForm.title.trim(),
    description: taskForm.description,
    priority: taskForm.priority,
    assigneeMemberId: taskForm.assigneeMemberId ?? null,
    progress: taskForm.progress,
    startDate: taskDateRange.value?.[0] ?? null,
    dueDate: taskDateRange.value?.[1] ?? null,
    // 业务项目不发仓库字段（后端 BR-01/BR-12 会拒；不发即不制造注定失败的请求）
    repoId: isDev.value ? (taskForm.repoId ?? null) : undefined,
    repoIssueNo: isDev.value ? (taskForm.repoIssueNo || null) : undefined,
    repoBranch: isDev.value ? (taskForm.repoBranch || null) : undefined,
    repoCommitSha: isDev.value ? (taskForm.repoCommitSha || null) : undefined
  }
  savingTask.value = true
  try {
    if (taskForm.id) {
      await pmUpdateTask(projectId, taskForm.id, body)
    } else {
      await pmCreateTask(projectId, body)
    }
    taskVisible.value = false
    ElMessage.success('已保存')
    loadTasks()
  } catch (e) {
    // 状态机 / 成对约束 / 仓库绑定校验的原文都在这里展示
    ElMessage.error(pmErrMsg(e, '保存任务失败'))
  } finally {
    savingTask.value = false
  }
}

async function changeTaskStatus(row: PmTask, status: string) {
  if (status === row.status) return
  try {
    await pmChangeTaskStatus(projectId, row.id, status)
    ElMessage.success('状态已更新')
    loadTasks()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更状态失败'))
    loadTasks()
  }
}

async function removeTask(row: PmTask) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.title}」？`, '删除任务', { type: 'warning' })
  } catch {
    return
  }
  try {
    await pmDeleteTask(projectId, row.id)
    ElMessage.success('已删除')
    loadTasks()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '删除失败'))
  }
}

// ---------------------------------------------------------------- 成员
async function openAddMember() {
  memberVisible.value = true
  newMemberId.value = undefined
  newMemberRole.value = 'MEMBER'
  try {
    candidates.value = await pmMemberCandidates(projectId)
  } catch (e) {
    candidates.value = []
    ElMessage.warning(pmErrMsg(e, '加载员工候选失败'))
  }
}

async function doAddMember() {
  if (!newMemberId.value) {
    ElMessage.warning('请选择员工')
    return
  }
  savingMember.value = true
  try {
    const res = await pmAddMember(projectId, newMemberId.value, newMemberRole.value)
    memberList.value = res
    members.value = res.items
    memberVisible.value = false
    ElMessage.success('已添加')
    loadTasks()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '添加成员失败'))
  } finally {
    savingMember.value = false
  }
}

async function changeMemberRole(row: PmMember, roleCode: string) {
  if (roleCode === row.roleCode) return
  try {
    const res = await pmChangeMemberRole(projectId, row.id, roleCode)
    memberList.value = res
    members.value = res.items
    ElMessage.success('角色已更新')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更角色失败'))
    loadMembers()
  }
}

async function removeMember(row: PmMember) {
  try {
    await ElMessageBox.confirm(`确认将「${row.name}」移出本项目？`, '移除成员', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await pmRemoveMember(projectId, row.id)
    memberList.value = res
    members.value = res.items
    ElMessage.success('已移除')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '移除失败'))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.desc {
  margin: 12px 0 0;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
</style>
