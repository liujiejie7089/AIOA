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

      <!-- 以下为平台级基线数据与配置，仅系统管理员可见（租户侧无写权限） -->
      <template v-if="isPlatformAdmin">
        <el-card shadow="never" class="block">
          <template #header><span>角色</span></template>
          <el-table :data="roles" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="roleCode" label="角色编码" min-width="160" />
            <el-table-column prop="roleName" label="角色名称" min-width="160">
              <template #default="{ row }">{{ row.roleName || '—' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无角色数据" :image-size="60" />
            </template>
          </el-table>
        </el-card>

        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-header">
              <span>功能管理</span>
              <el-button text type="primary" size="small" :loading="appsLoading" @click="loadApps">刷新</el-button>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="启用/禁用与可见范围保存后立即生效：禁用的模块从用户端「我的应用」隐藏；「仅管理员」模块对普通用户不可见。"
            style="margin-bottom: 10px"
          />
          <el-table v-loading="appsLoading" :data="apps" stripe>
            <el-table-column prop="appCode" label="模块编码" width="120" />
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="(v: boolean) => saveApp(row, { enabled: v })" />
              </template>
            </el-table-column>
            <el-table-column label="可见范围" width="160">
              <template #default="{ row }">
                <el-select
                  :model-value="row.visibleScope || 'ALL'"
                  size="small"
                  @change="(v: 'ALL' | 'ADMIN') => saveApp(row, { visibleScope: v })"
                >
                  <el-option label="所有人" value="ALL" />
                  <el-option label="仅管理员" value="ADMIN" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column prop="hostType" label="类型" width="100" />
            <template #empty>
              <el-empty description="暂无功能模块" :image-size="60" />
            </template>
          </el-table>
        </el-card>

        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-header">
              <span>模型管理</span>
              <div>
                <el-button text type="primary" size="small" :loading="modelsLoading" @click="loadModels">刷新</el-button>
                <el-button type="primary" size="small" @click="openModelDialog()">新增模型</el-button>
              </div>
            </div>
          </template>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="保存/切换默认后自动推送 agent 热加载，无需重启即可生效。默认模型即用户端会话的默认路由。"
            style="margin-bottom: 10px"
          />
          <el-table v-loading="modelsLoading" :data="models" stripe>
            <el-table-column prop="providerKey" label="标识" width="110" />
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column prop="modelName" label="模型" min-width="150" />
            <el-table-column prop="baseUrl" label="接入地址" min-width="220" show-overflow-tooltip />
            <el-table-column label="默认" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.isDefault" type="success" effect="plain" size="small">默认</el-tag>
                <el-button v-else text type="primary" size="small" @click="makeDefault(row)">设默认</el-button>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="(v: boolean) => toggleModel(row, v)" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="openModelDialog(row)">编辑</el-button>
                <el-button text type="danger" size="small" @click="removeModel(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无模型配置" :image-size="60" />
            </template>
          </el-table>
        </el-card>

        <el-card shadow="never">
          <template #header><span>权限点</span></template>
          <el-table :data="permissions" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="permCode" label="权限编码" min-width="200" />
            <el-table-column prop="permName" label="权限名称" min-width="200">
              <template #default="{ row }">{{ row.permName || '—' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无权限点数据" :image-size="60" />
            </template>
          </el-table>
        </el-card>
      </template>
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

    <!-- 模型弹窗（仅平台管理员可达） -->
    <el-dialog v-model="modelDialog.visible" :title="modelDialog.form.id ? '编辑模型' : '新增模型'" width="480px">
      <el-form label-position="top">
        <el-form-item label="标识（唯一，如 deepseek）">
          <el-input v-model="modelDialog.form.providerKey" :disabled="!!modelDialog.form.id" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="modelDialog.form.name" />
        </el-form-item>
        <el-form-item label="接入地址">
          <el-input v-model="modelDialog.form.baseUrl" />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="modelDialog.form.modelName" />
        </el-form-item>
        <el-form-item label="密钥环境变量名">
          <el-input v-model="modelDialog.form.apiKeyEnv" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="modelDialog.form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="modelDialog.saving" @click="saveModelForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assignUserRoles,
  changeUserStatus,
  deleteModel,
  listAllApps,
  listModels,
  listPermissions,
  listPersonnel,
  listRoles,
  saveModel,
  setDefaultModel,
  updateApp,
  type AppItem,
  type ModelItem,
  type PersonnelClass,
  type PersonnelMember,
  type PersonnelView,
  type SysPermission,
  type SysRole,
} from '@/api/resource'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
/** 平台级配置（角色/权限点/功能管理/模型管理/写操作）仅系统管理员可见。 */
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

// ---------- 平台级：角色分配 / 账号启停 ----------
const roles = ref<SysRole[]>([])
const permissions = ref<SysPermission[]>([])
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

async function loadRolesAndPermissions() {
  const results = await Promise.allSettled([listRoles(), listPermissions()])
  const [r, p] = results
  roles.value = r.status === 'fulfilled' ? r.value || [] : []
  permissions.value = p.status === 'fulfilled' ? p.value || [] : []
}

// ---------- 功能管理 ----------
const apps = ref<AppItem[]>([])
const appsLoading = ref(false)

async function loadApps() {
  appsLoading.value = true
  try {
    apps.value = (await listAllApps()) || []
  } catch {
    apps.value = []
  } finally {
    appsLoading.value = false
  }
}

async function saveApp(row: AppItem, patch: { enabled?: boolean; visibleScope?: 'ALL' | 'ADMIN' }) {
  try {
    const updated = await updateApp(row.appCode, patch)
    Object.assign(row, updated)
    ElMessage.success(`「${row.name}」配置已保存并即时生效`)
  } catch (e) {
    ElMessage.error(apiError(e, '保存失败'))
  }
}

// ---------- 模型管理 ----------
const models = ref<ModelItem[]>([])
const modelsLoading = ref(false)
const modelDialog = reactive({
  visible: false,
  saving: false,
  form: { id: 0, providerKey: '', name: '', baseUrl: '', modelName: '', apiKeyEnv: '', enabled: true },
})

async function loadModels() {
  modelsLoading.value = true
  try {
    models.value = (await listModels()) || []
  } catch {
    models.value = []
  } finally {
    modelsLoading.value = false
  }
}

function openModelDialog(row?: ModelItem) {
  modelDialog.form = row
    ? {
        id: row.id,
        providerKey: row.providerKey,
        name: row.name,
        baseUrl: row.baseUrl,
        modelName: row.modelName,
        apiKeyEnv: row.apiKeyEnv,
        enabled: !!row.enabled,
      }
    : { id: 0, providerKey: '', name: '', baseUrl: 'https://', modelName: '', apiKeyEnv: 'API_KEY', enabled: true }
  modelDialog.visible = true
}

async function saveModelForm() {
  modelDialog.saving = true
  try {
    await saveModel({ ...modelDialog.form })
    ElMessage.success('模型配置已保存并推送 agent 热加载')
    modelDialog.visible = false
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '保存失败'))
  } finally {
    modelDialog.saving = false
  }
}

async function makeDefault(row: ModelItem) {
  try {
    await setDefaultModel(row.providerKey)
    ElMessage.success(`默认模型已切换为「${row.name}」，立即生效`)
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '操作失败'))
  }
}

async function toggleModel(row: ModelItem, enabled: boolean) {
  try {
    await saveModel({ ...row, enabled })
    await loadModels()
  } catch (e) {
    ElMessage.error(apiError(e, '操作失败'))
  }
}

async function removeModel(row: ModelItem) {
  try {
    await ElMessageBox.confirm(`确认删除模型「${row.name}」？`, '删除确认', { type: 'warning' })
    await deleteModel(row.providerKey)
    ElMessage.success('已删除')
    await loadModels()
  } catch (e) {
    if ((e as string) !== 'cancel') ElMessage.error(apiError(e, '删除失败'))
  }
}

onMounted(() => {
  loadPersonnel()
  // 平台级卡片对租户侧不可见，也就不必发注定 403 的请求
  if (isPlatformAdmin.value) {
    loadRolesAndPermissions()
    loadApps()
    loadModels()
  }
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
