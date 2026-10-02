<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="项目管理"
      description="立项 → 成员 → 任务 → 文档 → 经费 → 合同。项目分【业务项目】与【开发项目】两类；仅开发项目涉及代码仓库绑定与任务仓库关联。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>项目列表</span>
          <div>
            <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
            <el-button
              v-if="canCreate"
              size="small"
              type="primary"
              @click="openCreate"
            >新建项目</el-button>
          </div>
        </div>
      </template>

      <!-- 筛选区：类型 / 状态 / 关键字 -->
      <div class="filters">
        <el-select v-model="query.projectType" placeholder="项目类型" clearable size="small" style="width: 140px" @change="reload">
          <el-option v-for="t in PM_PROJECT_TYPES" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-select v-model="query.status" placeholder="项目状态" clearable size="small" style="width: 140px" @change="reload">
          <el-option v-for="s in PM_PROJECT_STATUS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-input
          v-model="query.keyword"
          placeholder="按编号或名称搜索"
          clearable
          size="small"
          style="width: 240px"
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-button size="small" @click="reload">查询</el-button>
      </div>

      <el-table :data="projects" v-loading="loading" size="small" style="margin-top: 12px">
        <el-table-column prop="projectNo" label="项目编号" width="140" />
        <el-table-column prop="name" label="项目名称" min-width="180">
          <template #default="{ row }">
            <el-link type="primary" @click="openDetail(row.id)">{{ row.name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.projectType === 'DEV' ? 'warning' : 'info'" size="small" effect="plain">
              {{ PM_PROJECT_TYPE_LABEL[row.projectType] || row.projectType }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="PM_PROJECT_STATUS_TAG[row.status] || 'info'" size="small">
              {{ PM_PROJECT_STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ownerName" label="负责人" width="110">
          <template #default="{ row }">{{ row.ownerName || '—' }}</template>
        </el-table-column>
        <el-table-column label="任务" width="120">
          <template #default="{ row }">{{ row.taskDoneCount || 0 }} / {{ row.taskCount || 0 }}</template>
        </el-table-column>
        <el-table-column prop="memberCount" label="成员" width="70" />
        <!-- 仓库列只对开发项目展示：业务项目恒为 0，展示「0」会让用户以为「该有仓库但没绑」 -->
        <el-table-column label="仓库" width="70">
          <template #default="{ row }">
            <span v-if="row.projectType === 'DEV'">{{ row.repoCount || 0 }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="我的角色" width="110">
          <template #default="{ row }">
            <span v-if="row.myRole">{{ PM_PROJECT_ROLE_LABEL[row.myRole] || row.myRole }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row.id)">详情</el-button>
            <el-button
              v-if="row.canManage"
              size="small"
              text
              type="danger"
              @click="removeProject(row)"
            >删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div style="padding: 24px 0; color: var(--el-text-color-secondary)">暂无项目</div>
        </template>
      </el-table>
    </el-card>

    <!-- ============================ 新建项目 ============================ -->
    <el-dialog v-model="createVisible" title="新建项目" width="720px" :close-on-click-modal="false">
      <!-- 类型是第 ① 步的必选项，也是后续「仓库策略」是否渲染的唯一开关（projectType 单一事实源） -->
      <el-form :model="form" label-width="110px" size="small">
        <el-form-item label="项目类型" required>
          <el-radio-group v-model="form.projectType">
            <el-radio-button v-for="t in PM_PROJECT_TYPES" :key="t.value" :value="t.value">
              {{ t.label }}
            </el-radio-button>
          </el-radio-group>
          <div class="hint">{{ typeHint }}</div>
        </el-form-item>

        <el-form-item label="项目编号" required>
          <el-input v-model="form.projectNo" placeholder="如 PRJ-2026-001（企业内唯一）" />
        </el-form-item>
        <el-form-item label="项目名称" required>
          <el-input v-model="form.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.ownerMemberId" placeholder="选择在册员工（可后补）" clearable filterable style="width: 100%">
            <el-option
              v-for="m in memberOptions"
              :key="m.id"
              :label="m.name + (m.employeeNo ? `（${m.employeeNo}）` : '')"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="预算总额">
          <el-input-number v-model="form.budgetAmount" :min="0" :precision="2" :step="10000" style="width: 220px" />
          <span class="hint">元（计划值，实际发生额在「经费」页签维护）</span>
        </el-form-item>
        <el-form-item label="起止日期">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>

        <!-- ================= 类型相关：仅开发项目渲染代码仓库策略 =================
             业务项目走的是「跳过」：界面直接提示无需仓库配置，且不渲染任何仓库字段。
             前端隐藏只是体验，后端 ProjectTypeGuard 才是边界（BR-01）。 -->
        <template v-if="form.projectType === 'DEV'">
          <el-divider content-position="left">代码仓库策略（仅开发项目）</el-divider>
          <el-form-item label="仓库策略">
            <el-radio-group v-model="repoStrategy">
              <el-radio value="BIND">绑定既有仓库</el-radio>
              <el-radio value="CREATE">自动建仓</el-radio>
              <el-radio value="NONE">暂不绑定</el-radio>
            </el-radio-group>
            <div class="hint">
              绑定既有仓库需该仓库**尚未归属任何项目**（一个仓库只归一个项目）；自动建仓失败不会阻断立项，失败原因会提示并可后补绑定。
            </div>
          </el-form-item>
          <el-form-item v-if="repoStrategy === 'BIND'" label="选择仓库">
            <el-select v-model="form.bindRepoId" placeholder="加载中…" clearable filterable style="width: 100%">
              <el-option
                v-for="r in bindableRepos"
                :key="r.id"
                :label="repoLabel(r)"
                :value="r.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="repoStrategy === 'CREATE'" label="仓库可见性">
            <el-radio-group v-model="form.repoVisibility">
              <el-radio value="private">私有</el-radio>
              <el-radio value="public">公开</el-radio>
            </el-radio-group>
          </el-form-item>
        </template>
        <el-alert
          v-else
          type="info"
          :closable="false"
          show-icon
          title="业务项目无需仓库配置"
          description="业务项目只含业务字段。若后续需要代码仓库，可在项目详情中把类型改为「开发项目」。"
          style="margin-bottom: 8px"
        />
      </el-form>

      <template #footer>
        <el-button size="small" @click="createVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { listMembers, type OrgMember } from '@/api/org'
import {
  pmProjects, pmCreateProject, pmDeleteProject, pmBindableReposForCreate, pmErrMsg,
  type PmProject, type PmRepo
} from '@/api/pm'
import {
  PM_PROJECT_TYPES, PM_PROJECT_TYPE_LABEL, PM_PROJECT_STATUS, PM_PROJECT_STATUS_LABEL,
  PM_PROJECT_STATUS_TAG, PM_PROJECT_ROLE_LABEL, PM_CREATE_ROLES, hasAnyRole
} from '@/constants/permissions'

const router = useRouter()
const auth = useAuthStore()

const projects = ref<PmProject[]>([])
const loading = ref(false)
const query = reactive<{ projectType?: string; status?: string; keyword?: string }>({})

const canCreate = computed(() => hasAnyRole(auth.roles, PM_CREATE_ROLES))

async function reload() {
  loading.value = true
  try {
    projects.value = await pmProjects({ ...query })
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载项目列表失败'))
  } finally {
    loading.value = false
  }
}

function openDetail(id: number) {
  router.push(`/pm/projects/${id}`)
}

async function removeProject(row: PmProject) {
  try {
    await ElMessageBox.confirm(
      `确认删除项目「${row.name}」？将级联软删其成员与任务（仓库仅解绑，不删除代码）。`,
      '删除项目',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await pmDeleteProject(row.id)
    ElMessage.success('项目已删除')
    reload()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '删除失败'))
  }
}

// ---------------------------------------------------------------- 新建项目
const createVisible = ref(false)
const creating = ref(false)
const memberOptions = ref<OrgMember[]>([])
const bindableRepos = ref<PmRepo[]>([])
const dateRange = ref<[string, string] | null>(null)
const repoStrategy = ref<'BIND' | 'CREATE' | 'NONE'>('NONE')

const form = reactive<{
  projectType: 'BUSINESS' | 'DEV'
  projectNo: string
  name: string
  ownerMemberId?: number
  budgetAmount: number
  description: string
  bindRepoId?: number
  repoVisibility: 'private' | 'public'
}>({
  projectType: 'BUSINESS',
  projectNo: '',
  name: '',
  budgetAmount: 0,
  description: '',
  repoVisibility: 'private'
})

const typeHint = computed(
  () => PM_PROJECT_TYPES.find((t) => t.value === form.projectType)?.hint || ''
)

function repoLabel(r: PmRepo) {
  const path = [r.gitee_owner, r.gitee_repo].filter(Boolean).join('/')
  return r.name ? `${r.name}${path ? `（${path}）` : ''}` : (r.repo_name || String(r.id))
}

async function openCreate() {
  createVisible.value = true
  repoStrategy.value = 'NONE'
  dateRange.value = null
  Object.assign(form, {
    projectType: 'BUSINESS', projectNo: '', name: '', ownerMemberId: undefined,
    budgetAmount: 0, description: '', bindRepoId: undefined, repoVisibility: 'private'
  })
  // 负责人候选：只取在册员工（后端 BR-03 同样只认可在册员工，前端不额外放宽）
  try {
    const res = await listMembers({ status: 'ACTIVE' })
    memberOptions.value = res.items || []
  } catch {
    memberOptions.value = []
  }
  // 仓库候选：新建时还没有项目 id，走「新建流程专用」端点（鉴权依据为「有新建项目权限」）。
  // 这里先清空，切到 DEV + 绑定策略时懒加载。
  bindableRepos.value = []
}

/**
 * 拉取可绑仓库候选。
 *
 * <p>只在「开发项目 + 绑定既有仓库」这一组合下才有意义 —— 业务项目连仓库字段都不渲染，
 * 开发项目选「自动建仓 / 暂不绑定」也不需要候选列表。懒加载避免每次打开对话框都白跑一次请求。</p>
 */
async function loadBindableRepos() {
  if (form.projectType !== 'DEV' || repoStrategy.value !== 'BIND') {
    return
  }
  if (bindableRepos.value.length > 0) {
    return
  }
  try {
    bindableRepos.value = await pmBindableReposForCreate()
  } catch (e) {
    bindableRepos.value = []
    ElMessage.warning(pmErrMsg(e, '加载可绑定仓库失败（可先跳过，稍后在项目详情绑定）'))
  }
}

// 类型或策略变化时按需补取候选；切走时清掉已选，避免「业务项目却带着一个 bindRepoId」提交
watch([() => form.projectType, repoStrategy], () => {
  if (form.projectType !== 'DEV' || repoStrategy.value !== 'BIND') {
    form.bindRepoId = undefined
  }
  loadBindableRepos()
})

async function submitCreate() {
  if (!form.projectNo.trim()) {
    ElMessage.warning('请填写项目编号')
    return
  }
  if (!form.name.trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  const body = {
    projectNo: form.projectNo.trim(),
    name: form.name.trim(),
    projectType: form.projectType,
    ownerMemberId: form.ownerMemberId,
    budgetAmount: form.budgetAmount,
    description: form.description || undefined,
    startDate: dateRange.value?.[0],
    endDate: dateRange.value?.[1],
    // 业务项目绝不携带仓库字段（后端 BR-01 会拒；这里也不发，避免制造一次注定失败的请求）
    bindRepoId: form.projectType === 'DEV' && repoStrategy.value === 'BIND' ? form.bindRepoId : undefined,
    createRepo: form.projectType === 'DEV' && repoStrategy.value === 'CREATE' ? true : undefined,
    repoVisibility: form.projectType === 'DEV' && repoStrategy.value === 'CREATE' ? form.repoVisibility : undefined
  }
  creating.value = true
  try {
    const created = await pmCreateProject(body)
    if (created.repoWarning) {
      ElMessage.warning(created.repoWarning)
    } else {
      ElMessage.success('项目已创建')
    }
    createVisible.value = false
    reload()
  } catch (e) {
    // 后端业务规则（如「项目编号已存在」「业务项目不支持代码仓库配置」）都在这里展示原文
    ElMessage.error(pmErrMsg(e, '创建失败'))
  } finally {
    creating.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}
</style>
