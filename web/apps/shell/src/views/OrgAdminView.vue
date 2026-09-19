<template>
  <div class="org-admin">
    <el-tabs v-model="active" class="org-admin-tabs">
      <!-- 组织与部门：原「组织与员工」页面（机构 / 部门树 / 员工名册），写操作仍由页内 canWrite 收窄。 -->
      <el-tab-pane name="org" label="组织与部门" />
      <!-- 人员管理：按档位分组的名册、角色分配、账号启停。
           原挂在本页的平台级卡片（角色 / 权限点 / 功能管理 / 模型管理）已按功能域
           迁至「权限与安全」「系统配置」两组。 -->
      <el-tab-pane v-if="showPersonnel" name="personnel" label="人员管理" />
    </el-tabs>

    <!--
      页签按需挂载（v-if + 异步分包）：看不到「人员管理」的角色不会去拉
      /admin/personnel 等平台级接口（否则必然 403 横幅）。
      两个页签各自**原样复用**既有视图组件，功能零裁剪 —— 合并的只是菜单入口。
    -->
    <component v-if="active === 'org'" :is="OrgPanel" />
    <component v-if="active === 'personnel' && showPersonnel" :is="PersonnelPanel" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { hasAnyRole, PERSONNEL_VIEW_ROLES } from '@/constants/permissions'

const auth = useAuthStore()
const route = useRoute()
const roles = computed(() => auth.roles)
/** 人员管理页签：四级管理者（平台 / 租户 / 机构 / 部门）可见；普通成员只看「组织与部门」。 */
const showPersonnel = computed(() => hasAnyRole(roles.value, PERSONNEL_VIEW_ROLES))

type TabName = 'org' | 'personnel'
const active = ref<TabName>('org')

/**
 * 默认页签由**入口路由**决定，而不是一律落在第一页：
 * - `/admin`（人员管理深链）→ 人员管理，老书签与老操作路径不变；
 * - `/org-structure`（合并后的正式菜单入口）→ 组织与部门。
 *
 * 用 watch(immediate) 而非 onMounted：两条路由共用本组件，在两者之间跳转时
 * 组件实例会被复用，onMounted 不会再触发，页签就不会跟着切。
 *
 * 目标页签不可见时回落「组织与部门」——绝不让 active 停在一个 `v-if` 为假的页签上：
 * 那样两个面板都不渲染，整页空白，正是「合并后功能看起来丢了」最隐蔽的形态。
 */
function syncTabFromRoute() {
  const want: TabName = route.name === 'admin' ? 'personnel' : 'org'
  active.value = want === 'personnel' && !showPersonnel.value ? 'org' : want
}
watch(() => route.name, syncTabFromRoute, { immediate: true })

/** 两块内容原样复用：OrgStructureView = 「组织与部门」；AdminView = 「人员管理」。 */
const OrgPanel = defineAsyncComponent(() => import('@/views/OrgStructureView.vue'))
const PersonnelPanel = defineAsyncComponent(() => import('@/views/AdminView.vue'))
</script>

<style scoped>
.org-admin-tabs {
  margin-bottom: 4px;
}
</style>
