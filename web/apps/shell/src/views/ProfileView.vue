<template>
  <div class="profile-page">
    <el-card shadow="never" class="block">
      <template #header><span>个人信息</span></template>
      <div class="profile-head">
        <div class="avatar">{{ initial }}</div>
        <div>
          <div class="name">{{ auth.displayName }}</div>
          <div class="sub">{{ auth.tenantName }}</div>
        </div>
      </div>
      <el-descriptions :column="2" border style="margin-top: 16px">
        <el-descriptions-item label="用户名">{{ user?.username || '—' }}</el-descriptions-item>
        <el-descriptions-item label="昵称">{{ user?.nickname || user?.displayName || '—' }}</el-descriptions-item>
        <el-descriptions-item label="用户 ID">{{ user?.userId ?? user?.id ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="所属租户">
          <template v-if="tenantId">
            {{ tenantName || ('#' + tenantId) }}
            <span class="muted">（ID {{ tenantId }}）</span>
          </template>
          <span v-else class="muted">未归属租户（平台级）</span>
        </el-descriptions-item>
        <el-descriptions-item label="所属机构">
          <template v-if="institutionId">
            {{ institutionName || ('#' + institutionId) }}
            <span class="muted">（ID {{ institutionId }}）</span>
          </template>
          <span v-else class="muted">未加入机构</span>
        </el-descriptions-item>
        <el-descriptions-item label="角色" :span="2">
          <el-tag v-for="r in roles" :key="r" size="small" effect="plain" style="margin-right: 6px">{{ roleText(r) }}</el-tag>
          <span v-if="!roles.length" class="muted">—</span>
        </el-descriptions-item>
        <el-descriptions-item label="账号状态">
          <el-tag type="success" effect="plain">正常</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header><span>额度与用量</span></template>
      <div v-if="quota" class="quota-line">
        <el-progress :percentage="quota.percent" :stroke-width="14" />
        <div class="quota-text">
          套餐额度 {{ fmt(quota.quota) }} 词元 · 已用 {{ fmt(quota.used) }} · 剩余
          <b :class="{ danger: quota.exhausted }">{{ fmt(quota.left) }}</b>
        </div>
      </div>
      <el-empty v-else-if="quotaError" description="额度数据加载失败" :image-size="60" />
      <div v-else class="loading">加载中…</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { myQuota, type QuotaView } from '@/api/resource'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const user = computed(() => auth.user as Record<string, unknown> | null)
const initial = computed(() => auth.displayName.slice(0, 1).toUpperCase())
const roles = computed<string[]>(() => {
  const u = auth.user as { roles?: string[] } | null
  return u?.roles || []
})

/** 数据锚点：租户 / 机构归属。登录与 /me 均已下发，前端不再另行反查。 */
const tenantId = computed(() => (auth.user as { tenantId?: number } | null)?.tenantId ?? 0)
const tenantName = computed(() => (auth.user as { tenantName?: string } | null)?.tenantName || '')
const institutionId = computed(() => (auth.user as { institutionId?: number } | null)?.institutionId ?? null)
const institutionName = computed(() => (auth.user as { institutionName?: string } | null)?.institutionName || '')

const ROLE_TEXT: Record<string, string> = {
  ROLE_ADMIN: '平台管理员',
  ROLE_TENANT_ADMIN: '租户管理员',
  ROLE_ORG_ADMIN: '企业管理员',
  ROLE_DEPT_LEADER: '部门负责人',
  ROLE_MEMBER: '机构成员',
  ROLE_USER: '普通用户'
}
function roleText(r: string) { return ROLE_TEXT[r] || r }

const quota = ref<QuotaView | null>(null)
const quotaError = ref(false)

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}

onMounted(async () => {
  try {
    quota.value = await myQuota()
  } catch {
    quotaError.value = true
  }
})
</script>

<style scoped>
.block {
  margin-bottom: 12px;
}

.profile-head {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--aioa-primary);
  color: #fff;
  font-size: 22px;
  font-weight: 600;
}

.name {
  font-size: 17px;
  font-weight: 600;
}

.sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.quota-line {
  max-width: 560px;
}

.quota-text {
  margin-top: 8px;
  font-size: 13px;
  color: var(--aioa-text-sub);
}

.danger {
  color: var(--el-color-danger);
}

.muted {
  color: var(--aioa-text-sub);
}

.loading {
  color: var(--aioa-text-sub);
  font-size: 13px;
}
</style>
