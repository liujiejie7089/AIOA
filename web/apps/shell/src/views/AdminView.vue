<template>
  <div>
    <el-alert
      v-if="forbidden"
      type="warning"
      :closable="false"
      show-icon
      title="系统管理仅租户管理员可访问"
      description="当前账号没有 ROLE_ADMIN 角色，如需管理权限请联系租户管理员。"
      style="margin-bottom: 12px"
    />

    <template v-else>
      <el-card shadow="never" class="block">
        <template #header>
          <div class="card-header">
            <span>用户管理</span>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
          </div>
        </template>
        <el-table v-loading="loading" :data="users" stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="username" label="用户名" min-width="140" />
          <el-table-column prop="nickname" label="昵称" min-width="140">
            <template #default="{ row }">{{ row.nickname || '—' }}</template>
          </el-table-column>
          <el-table-column label="角色" min-width="180">
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
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ENABLED' ? 'success' : 'danger'" effect="plain">
                {{ row.status === 'ENABLED' ? '启用' : row.status || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="tenantId" label="租户 ID" width="100" />
          <el-table-column label="操作" width="200" fixed="right">
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
            <el-empty description="暂无用户数据" :image-size="80" />
          </template>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            :page-size="size"
            :total="total"
            layout="total, prev, pager, next"
            background
            @current-change="loadUsers"
          />
        </div>
      </el-card>

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

    <!-- 分配角色对话框 -->
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assignUserRoles,
  changeUserStatus,
  deleteModel,
  listAllApps,
  listModels,
  listPermissions,
  listRoles,
  listUsers,
  saveModel,
  setDefaultModel,
  updateApp,
  type AppItem,
  type ModelItem,
  type SysPermission,
  type SysRole,
  type SysUser,
} from '@/api/resource'

const loading = ref(false)
const forbidden = ref(false)
const users = ref<SysUser[]>([])
const roles = ref<SysRole[]>([])
const permissions = ref<SysPermission[]>([])
const page = ref(1)
const size = 20
const total = ref(0)

const roleDialog = reactive({
  visible: false,
  saving: false,
  userId: 0,
  username: '',
  selected: [] as number[],
})

function openRoleDialog(row: SysUser) {
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
    await loadUsers()
  } catch (e) {
    ElMessage.error((e as { message?: string })?.message || '保存失败')
  } finally {
    roleDialog.saving = false
  }
}

async function toggleStatus(row: SysUser, status: 'ENABLED' | 'DISABLED') {
  try {
    await changeUserStatus(row.id, status)
    ElMessage.success(status === 'ENABLED' ? '已启用' : '已停用，存量令牌即刻失效')
    await loadUsers()
  } catch (e) {
    ElMessage.error((e as { message?: string })?.message || '操作失败')
  }
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
    ElMessage.error((e as { message?: string })?.message || '保存失败')
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
    ElMessage.error((e as { message?: string })?.message || '保存失败')
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
    ElMessage.error((e as { message?: string })?.message || '操作失败')
  }
}

async function toggleModel(row: ModelItem, enabled: boolean) {
  try {
    await saveModel({ ...row, enabled })
    await loadModels()
  } catch (e) {
    ElMessage.error((e as { message?: string })?.message || '操作失败')
  }
}

async function removeModel(row: ModelItem) {
  try {
    await ElMessageBox.confirm(`确认删除模型「${row.name}」？`, '删除确认', { type: 'warning' })
    await deleteModel(row.providerKey)
    ElMessage.success('已删除')
    await loadModels()
  } catch (e) {
    if ((e as string) !== 'cancel') ElMessage.error((e as { message?: string })?.message || '删除失败')
  }
}

async function loadUsers() {
  try {
    const result = await listUsers(page.value, size)
    users.value = result?.records || []
    total.value = Number(result?.total || 0)
  } catch {
    users.value = []
  }
}

async function reload() {
  loading.value = true
  try {
    const results = await Promise.allSettled([listUsers(page.value, size), listRoles(), listPermissions()])
    const [u, r, p] = results
    forbidden.value = u.status === 'rejected' && (u.reason as { response?: { status?: number } })?.response?.status === 403
    if (u.status === 'fulfilled') {
      users.value = u.value?.records || []
      total.value = Number(u.value?.total || 0)
    } else {
      users.value = []
    }
    roles.value = r.status === 'fulfilled' ? r.value || [] : []
    permissions.value = p.status === 'fulfilled' ? p.value || [] : []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  reload()
  loadApps()
  loadModels()
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
