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
        <el-descriptions-item label="租户 ID">{{ user?.tenantId ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="角色">
          <el-tag v-for="r in roles" :key="r" size="small" effect="plain" style="margin-right: 6px">{{ r }}</el-tag>
          <span v-if="!roles.length">—</span>
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

.loading {
  color: var(--aioa-text-sub);
  font-size: 13px;
}
</style>
