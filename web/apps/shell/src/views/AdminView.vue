<template>
  <div>
    <!-- 取数失败：把后端真实原因显示出来（旧实现在 403 时静默留空表，用户只看到「全部空白」） -->
    <el-alert
      v-if="errorMsg"
      type="error"
      :closable="false"
      show-icon
      :title="errorMsg"
      description="人员列表按账号权限范围下发：平台管理员=全平台；租户管理员=本租户；机构管理员=本机构；部门负责人=本部门。若需查看更大范围，请让上级管理员调整角色。"
      style="margin-bottom: 12px"
    />

    <template v-else>
      <el-alert
        v-if="view"
        type="info"
        :closable="false"
        show-icon
        :title="`当前数据范围：${view.scopeName} · 共 ${view.total} 人`"
        :description="view.hint"
        style="margin-bottom: 12px"
      />

      <el-card shadow="never" class="block">
        <template #header>
          <div class="card-header">
            <span>人员管理</span>
            <div class="header-ops">
              <el-input
                v-model="keyword"
                placeholder="搜索用户名 / 昵称"
                clearable
                size="small"
                style="width: 200px"
                @keyup.enter="loadPersonnel"
                @clear="loadPersonnel"
              />
              <el-button type="primary" size="small" :loading="loading" @click="loadPersonnel">查询</el-button>
            </div>
          </div>
        </template>

        <div v-loading="loading">
          <div v-if="view" class="stat-row">
            <el-tag
              v-for="cls in classOrder"
              :key="cls"
              :type="classTagType(cls)"
              effect="plain"
              size="small"
            >
              {{ classLabel(cls) }} {{ view.classCounts?.[cls] ?? 0 }}
            </el-tag>
            <span class="stat-total">按{{ groupByLabel }}自动分类</span>
          </div>

          <div v-for="g in view?.groups || []" :key="g.key" class="group">
            <div class="group-head">
              <span class="group-title">{{ g.label }}</span>
              <el-tag size="small" effect="plain">{{ g.count }} 人</el-tag>
            </div>
            <el-table :data="g.members" stripe size="small">
              <el-table-column prop="nickname" label="姓名" min-width="110">
                <template #default="{ row }">{{ row.nickname || '—' }}</template>
              </el-table-column>
              <el-table-column prop="username" label="用户名" min-width="140" />
              <el-table-column label="档位" width="112">
                <template #default="{ row }">
                  <el-tag :type="classTagType(row.scopeClass)" effect="plain" size="small">
                    {{ row.scopeLabel }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="角色" min-width="190">
                <template #default="{ row }">
                  <el-tag
                    v-for="code in row.roles || []"
                    :key="code"
                    :type="code === 'ROLE_ADMIN' ? 'danger' : 'info'"
                    effect="plain"
                    size="small"
                    style="margin-right: 4px"
                  >
                    {{ code }}
                  </el-tag>
                  <span v-if="!(row.roles || []).length" style="color: var(--el-text-color-placeholder)">—</span>
                </template>
              </el-table-column>
              <el-table-column v-if="showInstitutionColumn" prop="institutionName" label="机构" min-width="170">
                <template #default="{ row }">{{ row.institutionName || '—' }}</template>
              </el-table-column>
              <el-table-column prop="departmentName" label="部门" min-width="130">
                <template #default="{ row }">{{ row.departmentName || '—' }}</template>
              </el-table-column>
              <el-table-column prop="jobTitle" label="职务" min-width="130">
                <template #default="{ row }">{{ row.jobTitle || '—' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'ENABLED' ? 'success' : 'danger'" effect="plain" size="small">
                    {{ row.status === 'ENABLED' ? '启用' : row.status || '—' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column
                v-if="canWrite"
                label="操作"
                width="180"
                fixed="right"
              >
                <template #default="{ row }">
                  <el-button text type="primary" size="small" @click="openRoleDialog(row)">分配角色</el-button>
                  <el-button
                    v-if="row.status === 'ENABLED'"
                    text
                    type="danger"
                    size="small"
                    @click="toggleStatus(row, 'DISABLED')"
                  >
                    停用
                  </el-button>
                  <el-button v-else text type="success" size="small" @click="toggleStatus(row, 'ENABLED')">
                    启用
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="该分组暂无人员" :image-size="60" />
              </template>
            </el-table>
          </div>

          <el-empty
            v-if="view && !view.total"
            :description="keyword ? `没有匹配「${keyword}」的人员` : '当前范围内暂无人员数据'"
            :image-size="80"
          />
        </div>
      </el-card>
    </template>

    <!-- 分配角色对话框（仅平台管理员可达） -->
    <el-dialog v-model="roleDialog.visible" :title="`分配角色 — ${roleDialog.username}`" width="420px">
      <el-checkbox-group v-model="roleDialog.selected">
        <el-checkbox v-for="r in roles" :key="r.id" :value="r.id" style="display: block; margin-bottom: 6px">
          {{ r.roleCode }}（{{ r.roleName || '—' }}）
        </el-checkbox>
      </el-checkbox-group>
      <div style="margin-top: 8px; color: var(--el-text-color-secondary); font-size: 12px">
        保存后立即生效，该用户无需重新登录。
      </div>
      <template #footer>
        <el-button @click="roleDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="roleDialog.saving" @click="saveRoles">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  assignUserRoles,
  changeUserStatus,
  listPersonnel,
  listRoles,
  type PersonnelClass,
  type PersonnelMember,
  type PersonnelView,
  type SysRole,
} from '@/api/resource'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
/**
 * 本页只保留「人」相关的能力：名册、账号启停、分配角色。
 * 原挂在页内的平台级基线配置（角色 / 权限点 → 「权限与安全」；
 * 功能管理 / 模型管理 → 「系统配置」）已按功能域迁出，见 views/PlatformConfigView.vue。
 */
const isPlatformAdmin = computed(() => auth.isPlatformAdmin)

const loading = ref(false)
const errorMsg = ref('')
const view = ref<PersonnelView | null>(null)
const keyword = ref('')

const classOrder: PersonnelClass[] = ['PLATFORM', 'TENANT', 'ORG', 'DEPT', 'MEMBER']
const CLASS_LABELS: Record<string, string> = {
  PLATFORM: '平台管理员',
  TENANT: '租户管理员',
  ORG: '机构管理员',
  DEPT: '部门负责人',
  MEMBER: '普通成员',
}
type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'
const CLASS_TAG: Record<string, TagType> = {
  PLATFORM: 'danger',
  TENANT: 'warning',
  ORG: 'primary',
  DEPT: 'success',
  MEMBER: 'info',
}

function classLabel(cls: string): string {
  return CLASS_LABELS[cls] || cls
}
function classTagType(cls: string): TagType {
  return CLASS_TAG[cls] || 'info'
}

const groupByLabel = computed(() => {
  switch (view.value?.groupBy) {
    case 'TENANT':
      return '租户'
    case 'INSTITUTION':
      return '机构'
    default:
      return '权限档位'
  }
})
/** 按档位分组时（机构/部门视角）机构列恒为同一家，展示它只是噪音。 */
const showInstitutionColumn = computed(() => view.value?.groupBy !== 'TIER')
const canWrite = computed(() => !!view.value?.capability?.canAssignRole)

/**
 * 从 axios 错误里取出后端真实文案。
 *
 * <p>业务失败是 HTTP 200 + code≠0（由 unwrap 之外的地方处理），鉴权类失败才是 HTTP 403/404，
 * 此时后端消息在 {@code response.data.message} 里 —— 旧实现只读 {@code error.message}
 * 得到「Request failed with status code 403」，干脆什么都不显示，于是页面「全部空白」。</p>
 */
function apiError(e: unknown, fallback: string): string {
  const resp = (e as { response?: { status?: number; data?: { message?: string } } })?.response
  if (resp?.data?.message) return resp.data.message
  if (resp?.status === 403) return '当前账号无权查看人员列表'
  return (e as { message?: string })?.message || fallback
}

async function loadPersonnel() {
  loading.value = true
  errorMsg.value = ''
  try {
    view.value = await listPersonnel({ keyword: keyword.value.trim() || undefined })
  } catch (e) {
    view.value = null
    errorMsg.value = apiError(e, '人员列表加载失败')
  } finally {
    loading.value = false
  }
}

// ---------- 角色分配 / 账号启停 ----------
const roles = ref<SysRole[]>([])
const roleDialog = reactive({
  visible: false,
  saving: false,
  userId: 0,
  username: '',
  selected: [] as number[],
})

function openRoleDialog(row: PersonnelMember) {
  roleDialog.userId = row.id
  roleDialog.username = row.username
  roleDialog.selected = (row.roles || [])
    .map((code) => roles.value.find((r) => r.roleCode === code)?.id)
    .filter((v): v is number => typeof v === 'number')
  roleDialog.visible = true
}

async function saveRoles() {
  roleDialog.saving = true
  try {
    const res = await assignUserRoles(roleDialog.userId, roleDialog.selected)
    ElMessage.success(`已保存，当前角色：${(res.roles || []).join(', ') || '无'}`)
    roleDialog.visible = false
    await loadPersonnel()
  } catch (e) {
    ElMessage.error(apiError(e, '保存失败'))
  } finally {
    roleDialog.saving = false
  }
}

async function toggleStatus(row: PersonnelMember, status: 'ENABLED' | 'DISABLED') {
  try {
    await changeUserStatus(row.id, status)
    ElMessage.success(status === 'ENABLED' ? '已启用' : '已停用，存量令牌即刻失效')
    await loadPersonnel()
  } catch (e) {
    ElMessage.error(apiError(e, '操作失败'))
  }
}

/**
 * 角色列表只作为「分配角色」对话框的选项来源。
 *
 * 后端 `GET /admin/roles` 是 requireAdmin()（仅平台管理员）—— 沿用原口径按
 * 平台管理员收口，非平台管理员不发这发注定 403 的请求。
 */
async function loadRoles() {
  try {
    roles.value = (await listRoles()) || []
  } catch {
    roles.value = []
  }
}

onMounted(() => {
  loadPersonnel()
  if (isPlatformAdmin.value) loadRoles()
})
</script>

<style scoped>
.block {
  margin-bottom: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-ops {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.stat-total {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.group {
  margin-bottom: 16px;
}

.group:last-child {
  margin-bottom: 0;
}

.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.group-title {
  font-size: 14px;
  font-weight: 600;
}
</style>
