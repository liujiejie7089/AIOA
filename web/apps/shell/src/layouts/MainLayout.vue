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

    <el-container class="layout-body">
      <el-aside class="layout-aside" :width="collapsed ? '64px' : '200px'">
        <el-menu
          class="layout-menu"
          :default-active="menuActive"
          :default-openeds="initialOpenedGroups"
          :collapse="collapsed"
          router
        >
          <!--
            ===== 一级平铺：日常高频，人人都有 =====
            首页 / 审批中心 / 知识库 / 消息中心 —— 使用频次最高，不做折叠，
            避免「点两次才能进」把最常用的入口藏进子菜单。
          -->
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
            ===== 以下按「功能相近程度」收进子菜单 =====
            原先是 21 个一级项平铺（含 2 个既有子菜单），菜单上下溢出 1074px、
            必须整页滚动才能看到最后几项。现按域聚合为 8 个组：

              · 智能服务   —— AI 能力载体的定义与接入（数字员工/专家/工具/业务系统）
              · 成果与项目 —— 平台产出物（成果沉淀 + 代码仓库联动）
              · 运营管理   —— 用量与成本（经营数据 / 配额）
              · 租户与机构 —— 租户级组织与费用（机构/入驻/授权/分摊）
              · 组织与员工 —— 组织人事域（组织与部门 / 人员管理）
              · 权限与安全 —— 权限体系域（角色/权限点/审批流/审计/审核记录）
              · 系统配置   —— 平台运行配置域（系统参数 / 功能管理 / 模型管理）
              · 平台管理   —— 仅平台管理员（内容审核台 / 租户管理）

            每个组的可见性 = 其子项可见性的「或」，子项各自仍带原来的 RBAC 守卫；
            路由 index 与 router/index.ts 完全不变（三层同源不受影响）。
          -->

          <!-- 智能服务：数字员工 / 专家配置 / 业务工具 / 业务系统 -->
          <el-sub-menu v-if="showWorkerMenu || showExpertMenu || showTenantMenu" index="svc">
            <template #title>
              <el-icon><Cpu /></el-icon>
              <span>智能服务</span>
            </template>
            <!-- 创建/管理归属：系统管理员 / 租户管理员 / 企业管理员 / 部门负责人 -->
            <el-menu-item v-if="showWorkerMenu" index="/workers">数字员工</el-menu-item>
            <!-- 专家创建/配置：系统管理员 / 租户管理员 / 企业管理员（不含部门负责人） -->
            <el-menu-item v-if="showExpertMenu" index="/experts">专家配置</el-menu-item>
            <el-menu-item v-if="showTenantMenu" index="/tools">业务工具</el-menu-item>
            <el-menu-item v-if="showTenantMenu" index="/biz-systems">业务系统</el-menu-item>
          </el-sub-menu>

          <!-- 成果与项目：成果沉淀 + 仓库联动 -->
          <el-sub-menu v-if="showTenantMenu || showGiteeMenu" index="output">
            <template #title>
              <el-icon><FolderOpened /></el-icon>
              <span>成果与项目</span>
            </template>
            <el-menu-item v-if="showTenantMenu" index="/results">成果沉淀</el-menu-item>
            <!--
              项目与仓库（V48 Gitee 联动）：菜单 / 路由 meta.allowRoles / 后端 PermissionCatalog
              三处共用 GITEE_VIEW_ROLES —— 只读边界由后端按部门作用域收窄（人人有入口，只能看本部门）。
            -->
            <el-menu-item v-if="showGiteeMenu" index="/gitee/projects">项目与仓库</el-menu-item>
          </el-sub-menu>

          <!-- 运营管理：经营数据 / 配额管理 -->
          <el-sub-menu v-if="showTenantMenu" index="ops">
            <template #title>
              <el-icon><DataAnalysis /></el-icon>
              <span>运营管理</span>
            </template>
            <el-menu-item index="/kpi">经营数据</el-menu-item>
            <el-menu-item index="/quotas">配额管理</el-menu-item>
          </el-sub-menu>

          <!-- 租户与机构：仅平台管理员 / 租户管理员可见 -->
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
            组织与员工（组织人事域）：
            只装「人」相关的两个入口 —— 部门树与员工名册、账号与角色分配。
            原「系统管理」混装的平台级基线配置（角色 / 权限点 / 功能管理 / 模型管理）
            已按功能域分别迁入「权限与安全」「系统配置」，本组不再承担配置职能，
            故一并取消「标题按角色切换」的补丁（平台管理员与其他角色看到同一个名字）。

            可见范围沿用 ORG_VIEW_ROLES（并集，含普通成员）；「人员管理」子项再按
            PERSONNEL_VIEW_ROLES 收口，与路由 meta.allowRoles 同源。
          -->
          <el-sub-menu v-if="showOrgMenu" index="org">
            <template #title>
              <el-icon><UserFilled /></el-icon>
              <span>组织与员工</span>
            </template>
            <el-menu-item index="/org-structure">
              <template #title>组织与部门</template>
            </el-menu-item>
            <el-menu-item v-if="showPersonnelMenu" index="/admin">
              <template #title>人员管理</template>
            </el-menu-item>
          </el-sub-menu>

          <!--
            权限与安全（权限体系域，原「安全与治理」改名）：
            收进「角色 / 权限点」两块授权基线字典（仅平台管理员），它们与审批流配置、
            审计留痕、审核记录同属「规则与留痕」；原挂在组内的「系统参数」是运行配置
            而非治理规则，已迁往「系统配置」。

            组可见性 = 子项的或；子项各自保留原有 RBAC 守卫。
            TENANT_SCOPE_ROLES 含 ROLE_ADMIN，故平台管理员必然落在本组的可见范围内。
          -->
          <el-sub-menu v-if="showTenantMenu || showReviewRecordMenu" index="gov">
            <template #title>
              <el-icon><SetUp /></el-icon>
              <span>权限与安全</span>
            </template>
            <el-menu-item v-if="isPlatformAdmin" index="/sys-roles">角色</el-menu-item>
            <el-menu-item v-if="isPlatformAdmin" index="/sys-permissions">权限点</el-menu-item>
            <!--
              审批流配置（三期 C-02/A3-9）：租户端可视化配置各业务审批流的「知会对象」。
              可见范围与后端 /tenant/approval-flow-defs（requireTenantAdmin）一致 = TENANT_SCOPE_ROLES。
            -->
            <el-menu-item v-if="showTenantMenu" index="/approval-flows">审批流配置</el-menu-item>
            <el-menu-item v-if="showTenantMenu" index="/audit">操作审计</el-menu-item>
            <!-- 审核记录（V36 需求④）：平台管理员看全量，租户管理员看本租户 -->
            <el-menu-item v-if="showReviewRecordMenu" index="/review-records">审核记录</el-menu-item>
          </el-sub-menu>

          <!--
            系统配置（平台运行配置域，新组）：
            「系统参数」原先挂在「安全与治理」下是历史错位 —— 它管的是运行参数，
            与「功能管理」（模块开关）、「模型管理」（大模型接入）同类，现合并为一组。

            租户管理员只看得到「系统参数」（路由 minTier=tenant），平台管理员三项全可见；
            组可见性取 showTenantMenu（TENANT_SCOPE_ROLES 含 ROLE_ADMIN，平台管理员已覆盖）。
          -->
          <el-sub-menu v-if="showTenantMenu" index="syscfg">
            <template #title>
              <el-icon><Tools /></el-icon>
              <span>系统配置</span>
            </template>
            <el-menu-item index="/settings">系统参数</el-menu-item>
            <el-menu-item v-if="isPlatformAdmin" index="/sys-apps">功能管理</el-menu-item>
            <el-menu-item v-if="isPlatformAdmin" index="/sys-models">模型管理</el-menu-item>
          </el-sub-menu>

          <!-- 平台管理：仅平台管理员（内容审核台 / 租户管理） -->
          <el-sub-menu v-if="isPlatformAdmin" index="plat">
            <template #title>
              <el-icon><Stamp /></el-icon>
              <span>平台管理</span>
            </template>
            <el-menu-item index="/content-reviews">内容审核</el-menu-item>
            <el-menu-item index="/tenants">租户管理</el-menu-item>
          </el-sub-menu>
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
import { initBridge, registerAppOrigins } from '@/micro/bridge'
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
  PERSONNEL_VIEW_ROLES,
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
 * 顶层分组「组织与员工」的可见性取 ORG_VIEW_ROLES（并集）；
 * 组内的「人员管理」子项再按 PERSONNEL_VIEW_ROLES 收口（它是前者的真子集），
 * 与路由 meta.allowRoles 同源 —— 普通成员有「组织与部门」，但看不到「人员管理」。
 */
const showOrgMenu = computed(() => hasAnyRole(roles.value, ORG_VIEW_ROLES))
const showPersonnelMenu = computed(() => hasAnyRole(roles.value, PERSONNEL_VIEW_ROLES))

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
 * `/admin` 与 `sys-*` 现在都是菜单里真实存在的条目，直接拿 route.path 当高亮键即可；
 * 早期把 /admin 归并到 /org-structure 上（当时它只是页内页签）的兜底已随之取消。
 */
const menuActive = computed(() => route.path)

/**
 * 子菜单「默认展开」的组。
 *
 * 菜单分组后，子项默认是收起的：若用户从书签/深链直接进 `/quotas`，
 * 其所属组不展开就会出现「菜单里一项都没高亮」（高亮项被藏在收起的分组里）。
 * 这里按落地路由把所属组展开。
 *
 * `default-openeds` 只作为初始值生效，故按 `route.path` 计算即可 ——
 * 之后用户在菜单里手动展开/收起分组，由组件自身状态接管。
 */
/** 键是路由 path，值是该路由所属分组的 index（用于深链时把所属组默认展开）。 */
const PATH_GROUP: Record<string, string> = {
  // 智能服务
  '/workers': 'svc',
  '/experts': 'svc',
  '/tools': 'svc',
  '/biz-systems': 'svc',
  // 成果与项目
  '/results': 'output',
  '/gitee/projects': 'output',
  // 运营管理
  '/kpi': 'ops',
  '/quotas': 'ops',
  // 租户与机构
  '/institutions': 'tenant',
  '/onboarding': 'tenant',
  '/resource-grants': 'tenant',
  '/cost-alloc': 'tenant',
  // 组织与员工
  '/org-structure': 'org',
  '/admin': 'org',
  // 权限与安全
  '/sys-roles': 'gov',
  '/sys-permissions': 'gov',
  '/approval-flows': 'gov',
  '/audit': 'gov',
  '/review-records': 'gov',
  // 系统配置
  '/settings': 'syscfg',
  '/sys-apps': 'syscfg',
  '/sys-models': 'syscfg',
  // 平台管理
  '/content-reviews': 'plat',
  '/tenants': 'plat'
}

const initialOpenedGroups = computed<string[]>(() => {
  const p = route.path
  // 项目详情 `/gitee/projects/:id`、子应用 `/app/:code` 均按前缀归组
  const g = PATH_GROUP[p] || (p.startsWith('/gitee/') ? 'output' : p.startsWith('/app/') ? 'apps' : '')
  return g ? [g] : []
})

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

// 应用注册表一到位就把子应用 origin 收进白名单：在此之前工作台不接收任何桥接消息
watch(
  () => apps.items,
  (items) => registerAppOrigins(items),
  { immediate: true, deep: false }
)

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
