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
          :default-active="menuActive"
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
          <!--
            审批中心：菜单右上角红点 = 「待我处理」条数。
            口径与后端 /workflow/tasks?scope=todo 一致（指派给我 + 已轮到我这一级的 PENDING 节点），
            只取计数不下发明细（见 api/resource.ts workflowTodoSummary）。
          -->
          <el-menu-item index="/approvals" style="position: relative">
            <el-icon><Tickets /></el-icon>
            <template #title>审批中心</template>
            <span
              v-if="todoCount > 0"
              :title="`${todoCount} 条待你处理`"
              style="
                position: absolute;
                right: 10px;
                top: 50%;
                transform: translateY(-50%);
                min-width: 16px;
                height: 16px;
                line-height: 16px;
                padding: 0 4px;
                border-radius: 8px;
                background: #e24b4a;
                color: #fff;
                font-size: 11px;
                text-align: center;
              "
              >{{ collapsed ? '' : todoCount > 99 ? '99+' : todoCount }}</span
            >
          </el-menu-item>
          <!--
            审批流配置（三期 C-02/A3-9）：租户端可视化配置各业务审批流的「知会对象」。
            可见范围与后端 /tenant/approval-flow-defs（requireTenantAdmin）一致 = TENANT_SCOPE_ROLES。
          -->
          <el-menu-item v-if="showTenantMenu" index="/approval-flows">
            <el-icon><SetUp /></el-icon>
            <template #title>审批流配置</template>
          </el-menu-item>
          <el-menu-item index="/kb">
            <el-icon><Collection /></el-icon>
            <template #title>知识库</template>
          </el-menu-item>
          <!--
            消息中心（V5x）：对所有已登录角色可见（人人都要看自己的通知），
            故不加 v-if 守卫。通道配置 / 投递记录两个页签由页内 isTenantAdmin 收起，
            菜单 / 路由 meta / 后端三层同源（均不限制角色）。
          -->
          <el-menu-item index="/notifications">
            <el-icon><Bell /></el-icon>
            <template #title>消息中心</template>
          </el-menu-item>
          <!--
            项目与仓库（V48 Gitee 联动）：菜单 / 路由 meta.allowRoles / 后端 PermissionCatalog
            三处共用 GITEE_VIEW_ROLES —— 只读边界由后端按部门作用域收窄（人人有入口，只能看本部门）。
          -->
          <el-menu-item v-if="showGiteeMenu" index="/gitee/projects">
            <el-icon><Link /></el-icon>
            <template #title>项目与仓库</template>
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

          <!--
            组织与员工 / 系统管理（单入口，多页签）：
            原「组织与员工」(/org-structure) 与「人员管理 / 系统管理」(/admin) 两个菜单
            指向同一批人、同一批数据（前者部门树+员工名册，后者人事操作+平台配置），
            并列展示会让用户在两处反复横跳。现合并为一个入口：

            - 可见范围用 ORG_VIEW_ROLES（并集）：普通成员原本就能进「组织与员工」，
              合并后不能反而丢掉入口；PERSONNEL_VIEW_ROLES 是它的真子集，无需另判。
            - 标签按角色切换：平台管理员要的是「系统管理」（含角色/权限点/模型管理），
              其余管理者要的是「组织与员工」。
            - 页内是「组织与部门 | 人员管理」两个页签，后者由 OrgAdminView 按
              PERSONNEL_VIEW_ROLES 收起 —— 普通成员看不到它，也就不会打出注定 403 的平台级接口。
          -->
          <el-menu-item v-if="showOrgMenu" index="/org-structure">
            <el-icon><UserFilled /></el-icon>
            <template #title>{{ isPlatformAdmin ? '系统管理' : '组织与员工' }}</template>
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
          <el-menu-item v-if="showReviewRecordMenu" index="/review-records">
            <el-icon><DocumentChecked /></el-icon>
            <template #title>审核记录</template>
          </el-menu-item>
          <el-menu-item v-if="isPlatformAdmin" index="/tenants">
            <el-icon><OfficeBuilding /></el-icon>
            <template #title>租户管理</template>
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
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AssistantDrawer from '@/components/assistant/AssistantDrawer.vue'
import { workflowTodoSummary } from '@/api/resource'
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
  GITEE_VIEW_ROLES,
  ORG_VIEW_ROLES,
  REVIEW_RECORD_ROLES,
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
 *
 * 合并「组织与员工」与「人员管理 / 系统管理」后，本判据同时兼作合并入口的可见性：
 * PERSONNEL_VIEW_ROLES ⊂ ORG_VIEW_ROLES，故取并集即 ORG_VIEW_ROLES。
 * 细粒度的「人员与账号 / 平台配置」页签由 OrgAdminView 内部再按角色收起。
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
/** 审核记录（V36 需求④）：平台管理员看全量，租户管理员看本租户。 */
const showReviewRecordMenu = computed(() => hasAnyRole(roles.value, REVIEW_RECORD_ROLES))
/** 项目与仓库（V48 Gitee 联动）：与路由 meta.allowRoles、后端 PermissionCatalog 共用 GITEE_VIEW_ROLES。 */
const showGiteeMenu = computed(() => hasAnyRole(roles.value, GITEE_VIEW_ROLES))

/**
 * 侧边菜单的高亮项。
 *
 * `/admin` 是保留下来的**旧深链**（菜单里不再单独列出），直接拿 route.path 当高亮键，
 * 会让合并后的唯一入口失去高亮 —— 用户从旧书签进来会看到「菜单里一项都没选中」。
 * 因此把 /admin 归并到合并入口 /org-structure 上。
 */
const menuActive = computed(() => (route.path === '/admin' ? '/org-structure' : route.path))

/**
 * 「审批中心」未处理红点。
 *
 * <p>只取计数、不拉整棵待办树：红点要轮询，回明细（每单还带 timeline）代价过高。
 * 后端 {@code /workflow/tasks/summary} 与 {@code ?scope=todo} 同口径 ——
 * 「指派给我 + 已轮到我这一级的 PENDING 节点 + 单据未终态」。</p>
 *
 * <p>失败一律熄灭而不是弹错：非审批人拿到 403 属预期，后端不可达也不该打断工作。</p>
 */
const todoCount = ref(0)
let todoTimer: number | undefined

async function refreshTodo() {
  try {
    const s = await workflowTodoSummary()
    todoCount.value = Number(s?.todo || 0)
  } catch {
    todoCount.value = 0
  }
}

// 处理完一单跳回列表时要立刻回落，不能等下一次轮询（否则红点看着像没消）
watch(() => route.fullPath, () => void refreshTodo())

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
  // 红点：进入即拉一次，之后每 60s 兜底刷新（另有路由切换时的即时刷新）
  void refreshTodo()
  todoTimer = window.setInterval(() => void refreshTodo(), 60000)
  // 租户端页面（机构/入驻/授权/分摊）依赖作用域，先解析再放行子路由
  if (showTenantMenu.value) {
    try {
      await loadTenantScope()
    } catch {
      tenantState.loaded.value = true // 失败也要放行，避免页面永久空白
    }
  }
})

onUnmounted(() => {
  if (todoTimer !== undefined) {
    window.clearInterval(todoTimer)
  }
})
</script>
