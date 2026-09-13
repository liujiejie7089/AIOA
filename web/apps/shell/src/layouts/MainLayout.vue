<template>
  <el-container class="layout">
    <el-header class="layout-header" height="56px">
      <div class="brand">
        <el-icon class="brand-icon"><Platform /></el-icon>
        <span class="brand-text">AIOA 智能办公基座</span>
      </div>
      <div class="header-right">
        <!-- 平台管理员：切换「当前操作租户」，租户端全部页面共用（机构/入驻/授权/分摊） -->
        <el-select
          v-if="showTenantMenu && canSwitchTenant"
          :model-value="currentTenantId"
          size="small"
          class="tenant-pick"
          placeholder="选择租户"
          @change="onTenantChange"
        >
          <el-option
            v-for="t in tenantOptions"
            :key="t.id"
            :label="`${t.name}（机构 ${t.institutionCount ?? 0}）`"
            :value="t.id"
          />
        </el-select>
        <el-tag v-else-if="showTenantMenu && tenantScopeLoaded" size="small" type="success" effect="plain">
          {{ currentTenantName || auth.tenantName }}
        </el-tag>
        <el-tag v-else size="small" type="info" effect="plain">{{ auth.tenantName }}</el-tag>
        <el-button type="primary" plain size="small" @click="assistant.openDrawer()">
          <el-icon><ChatDotRound /></el-icon>
          <span style="margin-left: 4px">AI 助手</span>
        </el-button>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-avatar :size="26">{{ initial }}</el-avatar>
            <span class="user-name">{{ auth.displayName }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人信息</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-container>
      <el-aside class="layout-aside" :width="collapsed ? '64px' : '200px'">
        <el-menu
          class="layout-menu"
          :default-active="route.path"
          :default-openeds="['apps']"
          :collapse="collapsed"
          router
        >
          <el-menu-item index="/home">
            <el-icon><HomeFilled /></el-icon>
            <template #title>首页</template>
          </el-menu-item>
          <el-sub-menu v-if="apps.menuItems.length" index="apps">
            <template #title>
              <el-icon><Grid /></el-icon>
              <span>我的应用</span>
            </template>
            <el-menu-item v-for="item in apps.menuItems" :key="item.appCode" :index="`/app/${item.appCode}`">
              <template #title>{{ item.appName }}</template>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item index="/approvals">
            <el-icon><Tickets /></el-icon>
            <template #title>审批中心</template>
          </el-menu-item>
          <el-menu-item index="/kb">
            <el-icon><Collection /></el-icon>
            <template #title>知识库</template>
          </el-menu-item>

          <!-- 租户域：仅平台管理员 / 租户管理员可见 -->
          <el-sub-menu v-if="showTenantMenu" index="tenant">
            <template #title>
              <el-icon><OfficeBuilding /></el-icon>
              <span>租户与机构</span>
            </template>
            <el-menu-item index="/institutions">
              <template #title>机构管理</template>
            </el-menu-item>
            <el-menu-item index="/onboarding">
              <template #title>入驻进度</template>
            </el-menu-item>
            <el-menu-item index="/resource-grants">
              <template #title>资源授权</template>
            </el-menu-item>
            <el-menu-item index="/cost-alloc">
              <template #title>费用分摊</template>
            </el-menu-item>
          </el-sub-menu>

          <!-- 企业域：机构成员（企业管理员 / 部门负责人 / 成员）可见 -->
          <el-menu-item v-if="showOrgMenu" index="/org-structure">
            <el-icon><UserFilled /></el-icon>
            <template #title>组织与员工</template>
          </el-menu-item>

          <el-menu-item v-if="showTenantMenu" index="/kpi">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>经营数据</template>
          </el-menu-item>
          <el-menu-item v-if="showWorkerMenu" index="/workers">
            <el-icon><Cpu /></el-icon>
            <template #title>数字员工</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/biz-systems">
            <el-icon><Connection /></el-icon>
            <template #title>业务系统</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/quotas">
            <el-icon><Coin /></el-icon>
            <template #title>配额管理</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/audit">
            <el-icon><Document /></el-icon>
            <template #title>操作审计</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/settings">
            <el-icon><Tools /></el-icon>
            <template #title>系统参数</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/results">
            <el-icon><FolderOpened /></el-icon>
            <template #title>成果沉淀</template>
          </el-menu-item>
          <el-menu-item v-if="showExpertMenu" index="/experts">
            <el-icon><MagicStick /></el-icon>
            <template #title>专家配置</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/tools">
            <el-icon><Switch /></el-icon>
            <template #title>业务工具</template>
          </el-menu-item>
          <el-menu-item v-if="isPlatformAdmin" index="/content-reviews">
            <el-icon><Stamp /></el-icon>
            <template #title>内容审核</template>
          </el-menu-item>
          <el-menu-item v-if="isPlatformAdmin" index="/tenants">
            <el-icon><OfficeBuilding /></el-icon>
            <template #title>租户管理</template>
          </el-menu-item>
          <el-menu-item v-if="isPlatformAdmin" index="/admin">
            <el-icon><Setting /></el-icon>
            <template #title>系统管理</template>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-main class="layout-main">
        <!--
          租户端页面按「当前租户」重新挂载：平台管理员切换租户后，
          机构/入驻/授权/分摊四个页面必须重新取数，否则会留着上一个租户的数据。
          作用域就绪前不放行子路由，避免首帧用「空租户」打一次注定为空的请求。

          sessionActive 是登出闸门：退出登录会先清空登录态，此时必须立即卸下当前页面，
          否则登录态清空会让 showTenantMenu 翻转、:key 又随租户清空而改变，
          两者叠加会把「已登出」的页面重新挂载一次并打出一发注定 401 的请求
          （用户实测「管理端退出登录时报 401」的根因）。
        -->
        <router-view
          v-if="sessionActive && (!showTenantMenu || tenantScopeLoaded)"
          v-slot="{ Component }"
        >
          <component :is="Component" :key="`${route.path}@${currentTenantId ?? 0}`" />
        </router-view>
      </el-main>
    </el-container>
  </el-container>

  <AssistantDrawer />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AssistantDrawer from '@/components/assistant/AssistantDrawer.vue'
import { useAppsStore } from '@/stores/apps'
import { useAuthStore } from '@/stores/auth'
import { useAssistantStore } from '@/stores/assistant'
import { initBridge } from '@/micro/bridge'
import {
  loadTenantScope,
  resetTenantScope,
  setCurrentTenant,
  tenantState
} from '@/api/tenantScope'
import {
  EXPERT_MANAGER_ROLES,
  ORG_VIEW_ROLES,
  ROLE,
  TENANT_SCOPE_ROLES,
  WORKER_MANAGER_ROLES,
  hasAnyRole
} from '@/constants/permissions'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const apps = useAppsStore()
const assistant = useAssistantStore()

const collapsed = ref(false)

// 租户端作用域：平台管理员可切换租户（详见 api/tenantScope.ts）
const tenantOptions = tenantState.tenants
const canSwitchTenant = tenantState.canSwitch
const tenantScopeLoaded = tenantState.loaded
const currentTenantId = tenantState.currentId
const currentTenantName = tenantState.currentName

function onTenantChange(id: number) {
  setCurrentTenant(id)
  const name = tenantState.tenants.value.find((t) => t.id === id)?.name || ''
  ElMessage.success(`已切换到「${name}」`)
}

const initial = computed(() => auth.displayName.slice(0, 1).toUpperCase())

/**
 * 菜单按角色可见（RBAC）。
 * 之前所有角色看到完全一样的菜单，导致普通成员也能进「系统管理 / 系统参数 / 业务系统」，
 * 且 V24 的租户端 / 企业端能力没有任何入口 —— 菜单既能见又点不开，是典型的数据锚点缺陷。
 */
const roles = computed(() => auth.roles)
/** 登录态闸门：登出瞬间即卸下当前页面，避免其在无令牌状态下重新挂载并打 401。 */
const sessionActive = computed(() => auth.isLogin)
const isPlatformAdmin = computed(() => hasAnyRole(roles.value, [ROLE.ADMIN]))
const showTenantMenu = computed(() => hasAnyRole(roles.value, TENANT_SCOPE_ROLES))
/**
 * 机构成员（企业管理员 / 部门负责人 / 成员）看本机构；租户管理员与平台管理员
 * 也开放入口——前者需按部门分发数字员工、后者需运维巡检，均为只读或本租户范围。
 */
const showOrgMenu = computed(() => hasAnyRole(roles.value, ORG_VIEW_ROLES))

/**
 * 数字员工 / 专家配置的创建与管理权限归属（V33），与后端 PermissionCatalog
 * 和路由 meta.allowRoles 共用同一份常量，避免三处口径漂移：
 * - 数字员工：系统管理员 / 租户管理员 / 企业管理员 / 部门负责人；
 * - 专家配置：系统管理员 / 租户管理员 / 企业管理员（不含部门负责人）。
 */
const showWorkerMenu = computed(() => hasAnyRole(roles.value, WORKER_MANAGER_ROLES))
const showExpertMenu = computed(() => hasAnyRole(roles.value, EXPERT_MANAGER_ROLES))

async function onCommand(command: string | number | object) {
  if (command === 'logout') {
    // auth.logout() 同步清空本地会话（触发上面的 sessionActive 闸门卸下当前页面），
    // 随后才 best-effort 通知后端；因此这里不 await 远端往返 —— 后端不通时
    // 最长要等 30s 超时，登出流程不能被它阻塞，本地登出必须立即生效。
    const remote = auth.logout()
    resetTenantScope()
    ElMessage.success('已退出登录')
    void router.replace('/login')
    await remote
  } else if (command === 'profile') {
    router.push('/profile')
  }
}

onMounted(async () => {
  initBridge()
  void apps.list()
  // 租户端页面（机构/入驻/授权/分摊）依赖作用域，先解析再放行子路由
  if (showTenantMenu.value) {
    try {
      await loadTenantScope()
    } catch {
      tenantState.loaded.value = true // 失败也要放行，避免页面永久空白
    }
  }
})
</script>
