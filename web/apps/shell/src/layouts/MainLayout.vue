<template>
  <el-container class="layout">
    <el-header class="layout-header" height="56px">
      <div class="brand">
        <el-icon class="brand-icon"><Platform /></el-icon>
        <span class="brand-text">AIOA 智能办公基座</span>
      </div>
      <div class="header-right">
        <el-tag size="small" type="info" effect="plain">{{ auth.tenantName }}</el-tag>
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
          <el-menu-item v-if="showTenantMenu" index="/workers">
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
          <el-menu-item v-if="showTenantMenu" index="/experts">
            <el-icon><MagicStick /></el-icon>
            <template #title>专家配置</template>
          </el-menu-item>
          <el-menu-item v-if="showTenantMenu" index="/tools">
            <el-icon><Switch /></el-icon>
            <template #title>业务工具</template>
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
        <router-view />
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

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const apps = useAppsStore()
const assistant = useAssistantStore()

const collapsed = ref(false)

const initial = computed(() => auth.displayName.slice(0, 1).toUpperCase())

/**
 * 菜单按角色可见（RBAC）。
 * 之前所有角色看到完全一样的菜单，导致普通成员也能进「系统管理 / 系统参数 / 业务系统」，
 * 且 V24 的租户端 / 企业端能力没有任何入口 —— 菜单既能见又点不开，是典型的数据锚点缺陷。
 */
const roles = computed(() => auth.roles)
const isPlatformAdmin = computed(() => roles.value.includes('ROLE_ADMIN'))
const showTenantMenu = computed(
  () => roles.value.includes('ROLE_ADMIN') || roles.value.includes('ROLE_TENANT_ADMIN')
)
/**
 * 机构成员（企业管理员 / 部门负责人 / 成员）看本机构；租户管理员与平台管理员
 * 也开放入口——前者需按部门分发数字员工、后者需运维巡检，均为只读或本租户范围。
 */
const showOrgMenu = computed(
  () => roles.value.includes('ROLE_ORG_ADMIN')
    || roles.value.includes('ROLE_DEPT_LEADER')
    || roles.value.includes('ROLE_MEMBER')
    || roles.value.includes('ROLE_TENANT_ADMIN')
    || roles.value.includes('ROLE_ADMIN')
)

async function onCommand(command: string | number | object) {
  if (command === 'logout') {
    await auth.logout()
    ElMessage.success('已退出登录')
    router.replace('/login')
  } else if (command === 'profile') {
    router.push('/profile')
  }
}

onMounted(() => {
  initBridge()
  void apps.list()
})
</script>
