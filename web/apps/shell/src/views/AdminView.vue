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
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ENABLED' ? 'success' : 'danger'" effect="plain">
                {{ row.status === 'ENABLED' ? '启用' : row.status || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="tenantId" label="租户 ID" width="100" />
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listPermissions, listRoles, listUsers, type SysPermission, type SysRole, type SysUser } from '@/api/resource'

const loading = ref(false)
const forbidden = ref(false)
const users = ref<SysUser[]>([])
const roles = ref<SysRole[]>([])
const permissions = ref<SysPermission[]>([])
const page = ref(1)
const size = 20
const total = ref(0)

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

onMounted(reload)
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
