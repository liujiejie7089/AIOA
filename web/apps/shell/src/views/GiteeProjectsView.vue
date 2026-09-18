<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      :title="headerTitle"
      :description="headerDesc"
      style="margin-bottom: 12px"
    />

    <!-- 配置**拉取失败**：与「服务明确说未启用」是两回事。
         合并成一句「后端尚未配置 xxx.*」会把用户和运维一起引向一个根本不存在的配置问题
         （2026-09-18 实测：后端重启期间前端就是这么报的，而配置一切正常）。 -->
    <el-alert
      v-if="configError"
      type="error"
      :closable="false"
      show-icon
      title="无法获取仓库联动配置"
      style="margin-bottom: 12px"
    >
      <div>{{ configError }}</div>
      <el-button size="small" style="margin-top: 8px" :loading="cfgLoading" @click="reload">
        重试
      </el-button>
    </el-alert>

    <!-- 模块未启用：仅当**服务明确回了 enabled=false** 才走这里，此时 cfgKey 是响应里的真实值 -->
    <el-alert
      v-else-if="!moduleEnabled"
      type="warning"
      :closable="false"
      show-icon
      title="仓库联动模块未启用"
      :description="`后端尚未配置 ${cfgKey}.*（组织、Webhook 回调基址等），「项目与仓库」功能暂不可用。请联系系统管理员在后端开启配置。`"
      style="margin-bottom: 12px"
    />

    <!-- 注意：下面的数据卡只在 moduleEnabled 为真（即配置已成功取到）时渲染，
         所以其中用到的 pName / cfgKey 一定来自服务端响应，不会是回落值。 -->
    <template v-else>

      <!-- (b) 我的 Gitee 账号 -->
      <el-card shadow="never" style="margin-bottom: 12px">
        <template #header>
          <div class="card-header">
            <!-- 整串绑定（而非插值拼接）：既有 UI 套件按「我的 Gitee 账号」这一整串文本定位元素，
                 拼成多段文本节点会让定位方式产生歧义。 -->
            <span>{{ `我的 ${pName} 账号` }}</span>
            <el-button text type="primary" size="small" :loading="bindingLoading" @click="loadBinding">刷新状态</el-button>
          </div>
        </template>

        <!-- 已绑定 -->
        <template v-if="bound">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="头像">
              <el-avatar :size="32" :src="binding?.avatarUrl">{{ avatarFallback }}</el-avatar>
            </el-descriptions-item>
            <el-descriptions-item :label="`${pName} 账号`">{{ binding?.giteeUsername }}</el-descriptions-item>
            <el-descriptions-item label="昵称">{{ binding?.giteeName || '—' }}</el-descriptions-item>
            <el-descriptions-item label="授权范围">{{ binding?.scope || '—' }}</el-descriptions-item>
            <el-descriptions-item label="绑定时间">{{ fmtTime(binding?.boundAt) }}</el-descriptions-item>
            <el-descriptions-item label="最近刷新">{{ fmtTime(binding?.refreshedAt) }}</el-descriptions-item>
            <el-descriptions-item label="令牌到期">
              {{ fmtTime(binding?.tokenExpiresAt) }}
              <el-tag v-if="binding?.tokenExpired" type="warning" size="small" style="margin-left: 6px">已过期（系统将自动刷新）</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="刷新令牌">{{ binding?.hasRefreshToken ? '已保存' : '无' }}</el-descriptions-item>
          </el-descriptions>
          <div style="margin-top: 12px">
            <el-button size="small" :loading="bindingLoading" @click="loadBinding">刷新状态</el-button>
            <el-button size="small" type="danger" plain @click="unbind">解绑</el-button>
          </div>
        </template>

        <!-- 未绑定（含绑定信息加载失败） -->
        <template v-else>
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            :title="`尚未绑定 ${pName} 账号`"
            :description="`创建项目会用到你的 ${pName} 授权（建仓、挂 Webhook、同步协作者）。请先绑定账号后再新建项目。`"
            style="margin-bottom: 12px"
          />
          <el-button type="primary" size="small" :loading="authorizing" @click="authorize">{{ `绑定 ${pName} 账号` }}</el-button>
          <el-button size="small" :loading="bindingLoading" @click="loadBinding">我已授权完成，刷新</el-button>
          <span v-if="polling" class="muted small" style="margin-left: 10px">正在等待授权回调…</span>
        </template>
      </el-card>

      <!-- (b2) 本企业 Gitee 组织：仅租户管理员 -->
      <el-card v-if="isTenantAdmin" shadow="never" style="margin-bottom: 12px">
        <template #header>
          <div class="card-header">
            <span>{{ `本企业 ${pName} 组织` }}</span>
            <el-button text type="primary" size="small" :loading="tenantCfgLoading" @click="loadTenantConfig">刷新</el-button>
          </div>
        </template>
        <div v-loading="tenantCfgLoading">
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
            <span class="muted small">当前生效组织</span>
            <strong>{{ effectiveOrg }}</strong>
            <el-tag v-if="tenantConfig?.source === 'TENANT'" type="success" size="small">企业自配置</el-tag>
            <el-tag v-else type="info" size="small">平台默认</el-tag>
            <el-tag size="small" :type="tenantConfig?.enabled ? 'success' : 'info'">
              企业联动：{{ tenantConfig?.enabled ? '启用' : '停用' }}
            </el-tag>
          </div>
          <el-alert
            v-if="tenantConfig?.source !== 'TENANT'"
            type="info"
            :closable="false"
            show-icon
            title="尚未配置本企业组织"
            :description="`本企业将使用平台默认组织（${tenantConfig?.defaultOrg || '—'}）创建仓库。配置独立的 ${pName} 组织可将本企业的仓库与其他企业隔离。`"
            style="margin: 10px 0"
          />
          <div style="margin-top: 10px">
            <el-button size="small" type="primary" plain @click="openTenantCfg">配置组织</el-button>
            <el-button v-if="tenantConfig?.configured" size="small" @click="clearTenantCfg">恢复平台默认</el-button>
          </div>
        </div>
      </el-card>

      <!-- (b3) 企业 Gitee 初始化：仅租户管理员 -->
      <el-card v-if="isTenantAdmin" shadow="never" style="margin-bottom: 12px">
        <template #header>
          <div class="card-header">
            <span>{{ `企业 ${pName} 初始化` }}</span>
            <div>
              <el-button text type="primary" size="small" :loading="initLoading" @click="loadInitStatus">刷新</el-button>
              <el-button size="small" type="primary" plain @click="openInitDlg">{{ initBtnText }}</el-button>
              <el-button v-if="initStatus?.initialized" size="small" type="danger" plain @click="revokeInit">撤销初始化</el-button>
            </div>
          </div>
        </template>
        <div v-loading="initLoading">
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px">
            <el-tag :type="initStatusType" size="small">{{ initStatusLabel }}</el-tag>
            <span class="muted small">企业令牌：{{ initStatus?.tokenConfigured ? '已配置' : '未配置' }}</span>
            <el-tag v-if="initStatus?.source === 'TENANT'" size="small" type="success">企业自配置</el-tag>
            <el-tag v-else-if="initStatus?.source === 'DEFAULT'" size="small" type="info">平台默认</el-tag>
          </div>

          <!-- ACTIVE：展示生效组织 / 令牌账号 / 范围 / 时间 / 组织校验 -->
          <el-descriptions v-if="initStatus?.initStatus === 'ACTIVE'" :column="2" border size="small">
            <el-descriptions-item label="生效组织">{{ initStatus.orgName || '—' }}</el-descriptions-item>
            <el-descriptions-item label="令牌所属账号">{{ initStatus.tokenOwner || '—' }}</el-descriptions-item>
            <el-descriptions-item label="令牌范围">{{ initStatus.tokenScope || '—' }}</el-descriptions-item>
            <el-descriptions-item label="初始化时间">{{ fmtTime(initStatus.initAt) }}</el-descriptions-item>
            <el-descriptions-item label="组织校验">
              <el-tag :type="initStatus.orgVerified ? 'success' : 'warning'" size="small">
                {{ initStatus.orgVerified ? '已通过' : '未通过' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <!-- FAILED：红色醒目展示 lastError -->
          <el-alert
            v-else-if="initStatus?.initStatus === 'FAILED'"
            type="error"
            :closable="false"
            show-icon
            title="初始化失败"
            :description="initStatus.lastError || '后端未返回失败原因，请重试或查看后端日志'"
          />

          <!-- 未初始化 / PENDING -->
          <el-alert
            v-else
            type="info"
            :closable="false"
            show-icon
            title="尚未初始化"
            description="使用企业自己的访问令牌与组织登录名初始化后，建仓等写操作将使用企业令牌，不依赖个人 OAuth 绑定。"
          />
        </div>
      </el-card>

      <!-- (c) 运维与校准：仅租户管理员 -->
      <el-card v-if="isTenantAdmin" shadow="never" style="margin-bottom: 12px">
        <template #header>
          <div class="card-header">
            <span>运维与校准</span>
            <el-button text type="primary" size="small" :loading="statsLoading" @click="loadTaskStats">刷新</el-button>
          </div>
        </template>
        <div v-loading="statsLoading">
          <div style="display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 10px">
            <el-statistic title="待处理（PENDING）" :value="taskStats.PENDING || 0" />
            <el-statistic title="执行中（RUNNING）" :value="taskStats.RUNNING || 0" />
            <el-statistic title="已完成（DONE）" :value="taskStats.DONE || 0" />
            <el-statistic title="失败（FAILED）" :value="taskStats.FAILED || 0" />
          </div>
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
            <span class="muted small">Worker：{{ taskStats.worker || '—' }}</span>
            <el-tag size="small" :type="config?.syncEnabled ? 'success' : 'info'">
              定时校准：{{ config?.syncEnabled ? '开启' : '关闭' }}
            </el-tag>
            <el-tag size="small" :type="config?.purgeRepoOnDelete ? 'warning' : 'info'">
              删除连仓：{{ config?.purgeRepoOnDelete ? '是' : '否' }}
            </el-tag>
            <el-button size="small" type="primary" plain @click="calibrate">手动校准</el-button>
          </div>
        </div>
      </el-card>

      <!-- (d) 项目列表 -->
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>项目列表（{{ rows.length }}）</span>
            <div>
              <el-button text type="primary" size="small" :loading="loading" @click="loadProjects">刷新</el-button>
              <el-button v-if="canCreateFlag" type="primary" size="small" @click="openCreate">新建项目</el-button>
            </div>
          </div>
        </template>

        <div class="filters">
          <el-select
            v-model="filterDept"
            placeholder="归属部门"
            size="small"
            clearable
            style="width: 200px"
            @change="loadProjects"
          >
            <el-option
              v-for="d in departments"
              :key="d.id"
              :label="d.namespace ? `${d.name}（${d.namespace}）` : (d.name || `部门 #${d.id}`)"
              :value="d.id"
            />
          </el-select>
          <el-input
            v-model="keyword"
            placeholder="项目名称/仓库名"
            size="small"
            clearable
            style="width: 220px"
            @keyup.enter="loadProjects"
          />
          <el-button size="small" type="primary" @click="loadProjects">查询</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>

        <el-table v-loading="loading" :data="rows" stripe empty-text="暂无项目">
          <el-table-column label="项目名称" min-width="160">
            <template #default="{ row }">{{ row.name || '—' }}</template>
          </el-table-column>
          <el-table-column label="归属部门" min-width="140">
            <template #default="{ row }">{{ deptName(row.departmentId) }}</template>
          </el-table-column>
          <el-table-column label="仓库" min-width="200">
            <template #default="{ row }">
              <span v-if="row.repoName">{{ row.repoName }}</span>
              <span v-else class="muted small">—</span>
              <el-link
                v-if="row.htmlUrl"
                type="primary"
                :href="row.htmlUrl"
                target="_blank"
                rel="noopener"
                style="margin-left: 8px"
              >在 {{ pName }} 打开 ↗</el-link>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="(GITEE_PROJECT_STATUS_TAG[row.status] || 'info')" size="small" effect="plain">
                {{ GITEE_PROJECT_STATUS_LABEL[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可见性" width="90">
            <template #default="{ row }">{{ GITEE_VISIBILITY_LABEL[row.visibility] || row.visibility || '—' }}</template>
          </el-table-column>
          <el-table-column label="默认分支" width="120">
            <template #default="{ row }">{{ row.defaultBranch || '—' }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column v-if="hasFailed" label="失败原因" min-width="200">
            <template #default="{ row }">
              <el-text v-if="row.status === 'FAILED'" type="danger" truncated>{{ row.errorMsg }}</el-text>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="goDetail(row)">详情</el-button>
              <el-button
                v-if="row.status === 'FAILED'"
                text
                type="warning"
                size="small"
                @click="retry(row)"
              >重试</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty description="暂无项目" :image-size="70" /></template>
        </el-table>
      </el-card>

      <!-- (e) 新建项目对话框 -->
      <el-dialog v-model="createDlg" title="新建项目" width="600px" @closed="resetCreateForm">
        <el-alert
          v-if="!bound"
          type="warning"
          :closable="false"
          show-icon
          :title="`需先绑定 ${pName} 账号`"
          :description="`建仓将使用你当前登录账号的 ${pName} 授权，请先在上方「我的 ${pName} 账号」中完成绑定。`"
          style="margin-bottom: 12px"
        />
        <el-form :model="createForm" label-width="96px" size="small">
          <el-form-item label="项目名称" required>
            <el-input
              v-model="createForm.name"
              placeholder="项目的仓库名由名称派生，并加上部门命名空间前缀（如 dept11-my-project）"
            />
          </el-form-item>
          <el-form-item label="归属部门" required>
            <el-select v-model="createForm.departmentId" placeholder="选择归属部门" style="width: 100%">
              <el-option
                v-for="d in departments"
                :key="d.id"
                :label="d.namespace ? `${d.name}（${d.namespace}）` : (d.name || `部门 #${d.id}`)"
                :value="d.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="项目描述">
            <el-input v-model="createForm.description" type="textarea" :rows="3" placeholder="可选" />
          </el-form-item>
          <el-form-item label="可见性">
            <el-radio-group v-model="createForm.visibility">
              <el-radio v-for="v in GITEE_VISIBILITIES" :key="v.value" :value="v.value">{{ v.label }}</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <el-text class="muted small" size="small">
          建仓与挂 Webhook 是异步的，提交后状态先为「创建中」，稍后刷新列表即可看到结果。
        </el-text>
        <template #footer>
          <el-button size="small" @click="createDlg = false">取消</el-button>
          <el-button size="small" type="primary" :loading="creating" :disabled="!bound" @click="submitCreate">创建</el-button>
        </template>
      </el-dialog>

      <!-- (b2) 配置本企业组织对话框：托管方随 provider -->
      <el-dialog v-model="tenantCfgDlg" :title="`配置本企业 ${pName} 组织`" width="520px" @closed="resetTenantCfgForm">
        <el-form :model="tenantCfgForm" label-width="120px" size="small">
          <el-form-item :label="`${pName} 组织登录名`" required>
            <el-input v-model="tenantCfgForm.orgName" placeholder="如 my-enterprise-org" />
          </el-form-item>
          <el-form-item>
            <span class="muted small">
              {{ `本企业在 ${pName} 上的组织登录名；本企业的新项目将在此组织下创建仓库。平台 ${pName} 账号须对该组织有访问权限，否则建仓会失败。` }}
            </span>
          </el-form-item>
          <el-form-item label="启用本企业联动">
            <el-switch v-model="tenantCfgForm.enabled" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button size="small" @click="tenantCfgDlg = false">取消</el-button>
          <el-button size="small" type="primary" :loading="tenantCfgSaving" @click="saveTenantCfg">保存</el-button>
        </template>
      </el-dialog>

      <!-- (b3) 企业 Gitee 初始化对话框 -->
      <el-dialog v-model="initDlg" :title="initBtnText" width="560px" @closed="resetInitForm">
        <el-form :model="initForm" label-width="120px" size="small">
          <el-form-item label="访问令牌" :required="tokenRequired">
            <el-input
              v-model="initForm.accessToken"
              type="password"
              show-password
              :placeholder="tokenRequired ? '必填：企业首次初始化需提供访问令牌' : '留空则沿用已有企业令牌'"
              autocomplete="new-password"
            />
            <div v-if="tokenRequired" class="muted small" style="margin-top: 4px">
              本企业<strong>尚未配置企业令牌</strong>，此处必须填写：{{ tokenHint }}
            </div>
            <div v-else class="muted small" style="margin-top: 4px">
              {{ tokenHint }}填写后将轮换企业令牌（rotateToken=true）；留空表示沿用已有令牌（rotateToken=false）。
            </div>
          </el-form-item>
          <el-form-item label="组织登录名" required>
            <el-input v-model="initForm.orgName" placeholder="字母/数字/._-，≤128" />
            <div v-if="orgNameError" class="init-error">{{ orgNameError }}</div>
            <div v-else class="muted small" style="margin-top: 4px">本企业将在该 {{ pName }} 组织下创建仓库。</div>
          </el-form-item>
          <el-form-item label="启用企业联动">
            <el-switch v-model="initForm.enabled" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input
              v-model="initForm.note"
              type="textarea"
              :rows="2"
              maxlength="255"
              show-word-limit
              placeholder="可选，≤255 字"
            />
          </el-form-item>
        </el-form>

        <!-- 校验步骤结果：逐步渲染，失败步骤红色 -->
        <div v-if="initSteps.length" style="margin-top: 8px">
          <div class="muted small" style="margin-bottom: 6px">校验结果：</div>
          <div
            v-for="(s, i) in initSteps"
            :key="i"
            class="init-step"
            :class="{ 'init-step-fail': s.ok === false }"
          >
            <span class="init-step-icon">{{ s.ok ? '✓' : '✗' }}</span>
            <span class="init-step-label">{{ s.label || '—' }}</span>
            <span v-if="s.message" class="init-step-msg">{{ s.message }}</span>
          </div>
        </div>

        <template #footer>
          <el-button size="small" @click="initDlg = false">取消</el-button>
          <el-button size="small" :loading="initVerifying" @click="verifyInit">校验配置</el-button>
          <el-button size="small" type="primary" :loading="initSubmitting" @click="submitInit">立即初始化</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  giteeConfig, giteeDepartments, giteeTaskStats, giteeCalibrate,
  giteeProjects, giteeCreateProject, giteeRetryProject,
  giteeMyBinding, giteeAuthorize, giteeUnbind, giteeErrMsg,
  giteeTenantConfig, giteeSaveTenantConfig, giteeClearTenantConfig,
  giteeInitStatus, giteeInitVerify, giteeInitInitialize, giteeInitRevoke,
  type GiteeConfig, type GiteeDepartment, type GiteeTaskStats, type GiteeProject, type GiteeBinding, type GiteeTenantConfig, type GiteeInitStatus, type GiteeInitStep
} from '@/api/gitee'
import {
  GITEE_PROJECT_STATUS_LABEL, GITEE_PROJECT_STATUS_TAG, GITEE_VISIBILITY_LABEL,
  GITEE_VISIBILITIES, TENANT_SCOPE_ROLES, hasAnyRole
} from '@/constants/permissions'

const router = useRouter()
const auth = useAuthStore()

// ---------------------------------------------------------------- 顶层状态
const config = ref<GiteeConfig | null>(null)
const binding = ref<GiteeBinding | null>(null)
/** 模块是否可用：config 拉取失败或 enabled=false 时为 false，此时跳过所有取数。 */
const moduleEnabled = ref(true)
/**
 * 配置**拉取失败**的说明（成功取到 / 服务明确说未启用时为空串）。
 *
 * <p>与 `moduleEnabled=false` 是**两个不同的状态**，必须分开表达：
 * 前者是「服务/网络拿不到配置」，后者是「服务明确回：没有配置」。
 * 合并的代价在 2026-09-18 实测过：后端重启期间前端报的是
 * 「后端尚未配置 aioa.gitee.*…请联系系统管理员开启配置」——把用户和运维一起
 * 引向一个**根本不存在的配置问题**。</p>
 */
const configError = ref('')
/** 配置拉取中（重试按钮的 loading）。 */
const cfgLoading = ref(false)

/**
 * 托管方展示名。本页所有面向用户的文案（页头、「我的 xx 账号」、对话框标题、提示消息）
 * 都必须走它 —— 写死「Gitee」会让 gitea 接线下的页面谎报托管方。
 *
 * 回落 'Gitee' 有两个理由：与后端 `aioa.repo.provider` 的默认值一致；
 * 且 config 不可达时至少不偏离历史表现（此时也无从得知真实托管方）。
 */
const pName = computed(() => config.value?.providerLabel || 'Gitee')
/**
 * 是否**确实知道**托管方是谁（= 配置已成功取到）。
 *
 * <p>页头据此决定要不要自称托管方：不知道时只能写「项目与仓库」。
 * 曾直接拿 `pName`（回落 'Gitee'）拼页头，于是 gitea 接线下**服务不可达**时
 * 整页回落成「项目与仓库（Gitee 联动）」——用户截图里看到的正是这句
 * （2026-09-18）。「不知道」就说不知道，不要让回落值冒充事实。</p>
 */
const providerKnown = computed(() => !!config.value?.providerLabel)
const headerTitle = computed(() =>
  providerKnown.value ? `项目与仓库（${pName.value} 联动）` : '项目与仓库'
)
const headerDesc = computed(() =>
  providerKnown.value
    ? `平台管理业务（项目、部门、成员、权限），${pName.value} 作为底层代码仓库；此处只显示你有权查看的部门项目。`
    : '平台管理业务（项目、部门、成员、权限）；此处只显示你有权查看的部门项目。'
)
/** 该托管方的后端配置前缀（aioa.gitee / aioa.gitea），让「未启用」提示指向真正生效的配置段。 */
const cfgKey = computed(() => config.value?.configKey || 'aioa.gitee')
/** 企业初始化的令牌权限要求（整句，随托管方）：回落 Gitee 的说法，与后端默认 provider 一致。 */
const tokenHint = computed(
  () => config.value?.tokenRequirementHint || '令牌需具备 projects 权限，且账号须为目标组织成员。'
)

const bound = computed(() => !!binding.value && binding.value.bound)
const avatarFallback = computed(() => {
  const b = binding.value
  const name = b?.giteeName || b?.giteeUsername || 'G'
  return (name || 'G').slice(0, 1).toUpperCase()
})
/** 租户管理员：不仅控制「运维与校准」卡片显隐，也控制 giteeTaskStats 的调用（否则成员会 403）。 */
const isTenantAdmin = computed(() => hasAnyRole(auth.roles, TENANT_SCOPE_ROLES))

// ---------------------------------------------------------------- 我的 Gitee 账号
const bindingLoading = ref(false)
const authorizing = ref(false)

function fmtTime(t?: string): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

async function loadBinding() {
  bindingLoading.value = true
  try {
    binding.value = await giteeMyBinding()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '加载绑定状态失败'))
  } finally {
    bindingLoading.value = false
  }
}

async function unbind() {
  try {
    await ElMessageBox.confirm(
      `确认解绑 ${pName.value} 账号？解绑会同时撤销你在本平台的仓库访问同步，已加入项目的成员会变为「待同步」状态，需要重新授权后才会恢复。`,
      `解绑 ${pName.value} 账号`,
      { type: 'warning', confirmButtonText: '确认解绑', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await giteeUnbind()
  } catch (e: unknown) {
    // 只有**解绑本身**失败才叫「解绑失败」
    ElMessage.error(giteeErrMsg(e, '解绑失败'))
    return
  }
  ElMessage.success('已解绑，正在刷新状态')
  // 解绑已经落库了，后面的刷新失败**不能再报「解绑失败」**：
  // 用户会以为没解开、反复点，而实际状态已经变了（2026-09-18 实测现象：
  // 后端重启期间解绑请求根本没到，提示混在一起后无法分辨到底是哪一步失败）。
  // 两步分开报，并把「刷新失败」的下一步动作指出来。
  try {
    await loadBinding()
    await initData()
  } catch (e: unknown) {
    ElMessage.warning(
      `已解绑，但刷新页面数据失败：${giteeErrMsg(e, '请点上方「刷新状态」重试')}`
    )
  }
}

// 授权后轮询：每 3s 查一次绑定状态，最多 90s，绑定成功后提前结束并刷新数据
const polling = ref(false)
let pollTimer: number | undefined

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
  polling.value = false
}

function startPolling() {
  stopPolling()
  polling.value = true
  let elapsed = 0
  pollTimer = window.setInterval(async () => {
    elapsed += 3000
    try {
      const b = await giteeMyBinding()
      binding.value = b
      if (b.bound) {
        stopPolling()
        ElMessage.success(`${pName.value} 账号已绑定`)
        await initData()
        return
      }
    } catch {
      // 授权页尚未回调完成属预期，继续等待
    }
    if (elapsed >= 90000) stopPolling()
  }, 3000)
}

async function authorize() {
  authorizing.value = true
  try {
    const res = await giteeAuthorize()
    // 授权域不是官方站点（本地桩/代理）时先明确告知：否则随后的「绑定成功」会让人
    // 以为真的走过了平台授权。文案由后端给出，前端不另起一份；
    // 兜底文案同样不写死域名 —— 真实站点地址随托管方变（gitee.com / 自建 Gitea 站点）。
    if (res.sandbox) {
      ElMessage.warning(
        res.warning || `当前授权域不是 ${pName.value} 官方站点，本次不会跳转到真实 ${pName.value}`
      )
    }
    // 注意 features 里**不能**写 'noopener'：按规范设置了 noopener 时 window.open
    // 一律返回 null，于是「是否被拦截」就无从判断。改用打开后手工清空 opener 达到同样
    // 的安全效果，同时保留可判定的返回值。
    const win = window.open(res.url, '_blank')
    if (win) {
      try {
        win.opener = null
      } catch {
        // 跨域窗口不可写，忽略即可（noopener 已由上面的赋值尽力保证）
      }
    }
    if (!win) {
      // 被浏览器拦截（window.open 在 await 之后已脱离用户手势调用栈）：
      // 退化为整页跳转，绝不出现「点了没反应」。
      window.location.href = res.url
      return
    }
    ElMessage.info(`已在新窗口打开 ${pName.value} 授权页；完成授权后本页会自动刷新`)
    startPolling()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '发起授权失败'))
  } finally {
    authorizing.value = false
  }
}

// ---------------------------------------------------------------- 运维与校准
// 初值必须是空对象而不是 null：本卡片在 isTenantAdmin 为真的**首帧**就会渲染，
// 而统计接口要等一拍才回来。若声明成 null，模板里读 taskStats.PENDING 会在首帧抛
// 「Cannot read properties of null」——Vue 会卸载整棵组件，租户管理员看到的是**全白页面**
// （而不是一张空卡片）。类型断言 as GiteeTaskStats 曾把这个错误对编译器藏起来，
// 所以这里刻意不用断言：字段全为可选，{} 合法，且一旦谁改回可空类型，vue-tsc 会立刻报错。
const taskStats = ref<GiteeTaskStats>({})
const statsLoading = ref(false)

async function loadTaskStats() {
  if (!isTenantAdmin.value) return
  statsLoading.value = true
  try {
    taskStats.value = (await giteeTaskStats()) || {}
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '加载任务统计失败'))
  } finally {
    statsLoading.value = false
  }
}

async function calibrate() {
  try {
    await ElMessageBox.confirm(
      `手动校准会重新拉取 ${pName.value} 侧直接变更的成员（如网页上手动添加的协作者），与平台记录对账并修复差异。是否现在执行？`,
      '手动校准成员',
      { type: 'warning', confirmButtonText: '开始校准', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const r = await giteeCalibrate()
    ElMessage.success(`已入队 ${r.enqueued} 条（范围：${r.scope}）${r.note ? '：' + r.note : ''}`)
    await loadTaskStats()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '校准失败'))
  }
}

// ---------------------------------------------------------------- 本企业 Gitee 组织（仅租户管理员）
// 仅 isTenantAdmin 时调用：非管理员调 giteeTenantConfig 会 403。每个调用各自 try/catch，
// 一个失败不影响其余卡片。
const tenantConfig = ref<GiteeTenantConfig | null>(null)
const tenantCfgLoading = ref(false)
const tenantCfgDlg = ref(false)
const tenantCfgSaving = ref(false)
const tenantCfgForm = ref<{ orgName: string; enabled: boolean }>({ orgName: '', enabled: true })

/** 生效组织：自配置取 orgName，回退取平台默认 defaultOrg。 */
const effectiveOrg = computed(() => tenantConfig.value?.orgName || tenantConfig.value?.defaultOrg || '—')

async function loadTenantConfig() {
  if (!isTenantAdmin.value) return
  tenantCfgLoading.value = true
  try {
    tenantConfig.value = (await giteeTenantConfig()) || {}
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '加载企业组织配置失败'))
  } finally {
    tenantCfgLoading.value = false
  }
}

function openTenantCfg() {
  tenantCfgForm.value = {
    orgName: tenantConfig.value?.orgName || '',
    enabled: tenantConfig.value?.enabled ?? true
  }
  tenantCfgDlg.value = true
}

function resetTenantCfgForm() {
  tenantCfgForm.value = { orgName: '', enabled: true }
}

async function saveTenantCfg() {
  if (!tenantCfgForm.value.orgName || !tenantCfgForm.value.orgName.trim()) {
    ElMessage.warning(`请输入 ${pName.value} 组织登录名`)
    return
  }
  tenantCfgSaving.value = true
  try {
    const res = await giteeSaveTenantConfig({
      orgName: tenantCfgForm.value.orgName.trim(),
      enabled: tenantCfgForm.value.enabled
    })
    ElMessage.success('已保存')
    // orgVerified/verifyMessage 仅为探测结果，不阻断保存；校验未通过时给出提示但不报错。
    if (res.orgVerified === false && res.verifyMessage) {
      ElMessage.warning(`组织校验未通过（不影响本次保存）：${res.verifyMessage}`)
    }
    tenantCfgDlg.value = false
    await loadTenantConfig()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '保存失败'))
  } finally {
    tenantCfgSaving.value = false
  }
}

async function clearTenantCfg() {
  try {
    await ElMessageBox.confirm(
      '确认恢复为平台默认组织？此后本企业的新项目将创建在共享的平台默认组织下，不再与本企业隔离。',
      '恢复平台默认组织',
      { type: 'warning', confirmButtonText: '恢复默认', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await giteeClearTenantConfig()
    ElMessage.success('已恢复平台默认组织')
    await loadTenantConfig()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '恢复默认失败'))
  }
}

// ---------------------------------------------------------------- 企业 Gitee 初始化（仅租户管理员）
// 与「本企业 Gitee 组织」不同：这里走企业<b>主动初始化</b>，用企业自己的访问令牌 + 组织名，
// 不依赖个人 OAuth 绑定。状态独立 try/catch 拉取：接口暂未部署会 404（预期内），
// 非管理员调会 403（外层已 isTenantAdmin 守卫），任一失败都不拖垮整页。
const initStatus = ref<GiteeInitStatus | null>(null)
const initLoading = ref(false)
const initDlg = ref(false)
const initVerifying = ref(false)
const initSubmitting = ref(false)
const initSteps = ref<GiteeInitStep[]>([])
const initForm = ref<{ accessToken: string; orgName: string; enabled: boolean; note: string }>({
  accessToken: '',
  orgName: '',
  enabled: true,
  note: ''
})

const ORG_NAME_RE = /^[A-Za-z0-9._-]{1,128}$/
/** 组织名的本地正则校验：不通过就不请求，并在表单原地给出提示。 */
const orgNameError = computed(() => {
  const v = initForm.value.orgName?.trim()
  if (!v) return '请输入组织登录名'
  if (!ORG_NAME_RE.test(v)) return '格式错误：仅允许字母/数字/._-，长度 1-128'
  return ''
})

/**
 * 访问令牌是否必填：由后端权威状态 `tokenConfigured` 决定。
 * 未配置过企业令牌 → 必填（留空必然失败，后端会返回「请填写访问令牌」）；
 * 已配置 → 可留空沿用已有令牌（rotateToken=false）。
 */
const tokenRequired = computed(() => !initStatus.value?.tokenConfigured)

const initStatusLabel = computed(() => {
  const s = initStatus.value?.initStatus
  if (s === 'ACTIVE') return '已激活'
  if (s === 'FAILED') return '初始化失败'
  return '未初始化'
})
const initStatusType = computed(() => {
  const s = initStatus.value?.initStatus
  if (s === 'ACTIVE') return 'success'
  if (s === 'FAILED') return 'danger'
  return 'info'
})
/** 「初始化」（未初始化）/「重新初始化」（已初始化）。 */
const initBtnText = computed(() => (initStatus.value?.initialized ? '重新初始化' : '初始化'))

async function loadInitStatus() {
  if (!isTenantAdmin.value) return
  initLoading.value = true
  try {
    initStatus.value = (await giteeInitStatus()) || {}
  } catch (e: unknown) {
    // 404=接口尚未部署（另一 worker 实现中，预期内），403=非管理员（理论上到不了）。
    // 不假数据兜底，如实提示即可，不影响整页其余卡片。
    ElMessage.error(giteeErrMsg(e, '加载企业初始化状态失败'))
  } finally {
    initLoading.value = false
  }
}

function openInitDlg() {
  initForm.value = {
    accessToken: '',
    orgName: initStatus.value?.orgName || '',
    enabled: initStatus.value?.enabled ?? true,
    note: ''
  }
  initSteps.value = []
  initDlg.value = true
}

function resetInitForm() {
  initForm.value = { accessToken: '', orgName: '', enabled: true, note: '' }
  initSteps.value = []
}

/** 校验配置：不落库，可安全反复点；返回的 steps 逐步渲染。 */
async function verifyInit() {
  if (orgNameError.value) {
    ElMessage.warning(orgNameError.value)
    return
  }
  initVerifying.value = true
  initSteps.value = []
  try {
    const res = await giteeInitVerify({
      accessToken: initForm.value.accessToken || undefined,
      orgName: initForm.value.orgName.trim()
    })
    initSteps.value = res.steps || []
    // 校验也可能顺带回写状态（orgVerified 等），刷新卡片。
    initStatus.value = { ...(initStatus.value || {}), ...res }
    // 顶层 passed 是权威判据（后端由 steps 同源推导）；仅当后端未回该字段时本地兜底。
    const allOk = res.passed ?? (res.steps || []).every((s) => s.ok)
    if (allOk) ElMessage.success('校验通过')
    else ElMessage.warning('校验存在失败项，请查看下方步骤明细')
  } catch (e: unknown) {
    // 业务错误（HTTP 200 + code≠0）：文案在 message 里；同时刷新状态看后端是否写入 lastError。
    ElMessage.error(giteeErrMsg(e, '校验失败'))
    await loadInitStatus()
  } finally {
    initVerifying.value = false
  }
}

/** 立即初始化：成功后提示并刷新；失败时展示 message 并立即刷新状态（后端写 lastError）。 */
async function submitInit() {
  if (orgNameError.value) {
    ElMessage.warning(orgNameError.value)
    return
  }
  // 未配置企业令牌时留空必然失败：本地先拦，省一次请求并给出明确指引（后端同样有兜底校验）。
  if (tokenRequired.value && !initForm.value.accessToken) {
    ElMessage.warning('请填写访问令牌：本企业尚未配置企业令牌，首次初始化必须提供')
    return
  }
  const hasToken = !!initForm.value.accessToken
  initSubmitting.value = true
  try {
    const res = await giteeInitInitialize({
      accessToken: initForm.value.accessToken || undefined,
      orgName: initForm.value.orgName.trim(),
      enabled: initForm.value.enabled,
      note: initForm.value.note || undefined,
      rotateToken: hasToken
    })
    ElMessage.success(`企业 ${pName.value} 初始化成功`)
    initStatus.value = { ...(initStatus.value || {}), ...res }
    initDlg.value = false
    await loadInitStatus()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '初始化失败'))
    // 失败也要刷新状态：后端会把失败步骤原因写进 lastError，要能立刻看到。
    await loadInitStatus()
  } finally {
    initSubmitting.value = false
  }
}

/** 撤销初始化：二次确认后清除企业令牌（不影响组织名与开关设置）。 */
async function revokeInit() {
  try {
    await ElMessageBox.confirm(
      `确认撤销企业 ${pName.value} 初始化？将清除企业令牌，不影响组织名与开关设置。撤销后建仓等操作将回落到平台默认组织。`,
      '撤销企业初始化',
      { type: 'warning', confirmButtonText: '确认撤销', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await giteeInitRevoke()
    ElMessage.success('已撤销企业初始化')
    await loadInitStatus()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '撤销失败'))
  }
}

// ---------------------------------------------------------------- 部门与项目列表
const departments = ref<GiteeDepartment[]>([])
const deptNameById = ref<Record<number, string>>({})
const rows = ref<GiteeProject[]>([])
const loading = ref(false)
const filterDept = ref<number | null>(null)
const keyword = ref('')
const canCreateFlag = ref(false)

const hasFailed = computed(() => rows.value.some((r) => r.status === 'FAILED'))

function deptName(id?: number): string {
  if (id == null) return '—'
  return deptNameById.value[id] || `部门 #${id}`
}

async function loadDepartments() {
  try {
    const ds = (await giteeDepartments()) || []
    departments.value = ds
    const map: Record<number, string> = {}
    ds.forEach((d) => { map[d.id] = d.name || `部门 #${d.id}` })
    deptNameById.value = map
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '加载部门失败'))
  }
}

async function loadProjects() {
  loading.value = true
  try {
    const res = await giteeProjects({
      departmentId: filterDept.value || undefined,
      keyword: keyword.value || undefined
    })
    rows.value = res?.items || []
    canCreateFlag.value = !!res?.canCreate
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '加载项目列表失败'))
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filterDept.value = null
  keyword.value = ''
  loadProjects()
}

function goDetail(row: GiteeProject) {
  if (row.id != null) router.push('/gitee/projects/' + row.id)
}

async function retry(row: GiteeProject) {
  if (row.id == null) return
  try {
    await giteeRetryProject(row.id)
    ElMessage.success('已触发重试，稍后刷新查看结果')
    await loadProjects()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '重试失败'))
  }
}

// ---------------------------------------------------------------- 新建项目
const createDlg = ref(false)
const creating = ref(false)
const createForm = ref<{ name: string; departmentId: number | null; description: string; visibility: 'private' | 'public' }>(
  { name: '', departmentId: null, description: '', visibility: 'private' }
)

function openCreate() {
  createDlg.value = true
}

function resetCreateForm() {
  createForm.value = { name: '', departmentId: null, description: '', visibility: 'private' }
}

async function submitCreate() {
  if (!createForm.value.name || !createForm.value.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  if (createForm.value.departmentId == null) {
    ElMessage.warning('请选择归属部门')
    return
  }
  creating.value = true
  try {
    const res = await giteeCreateProject({
      name: createForm.value.name.trim(),
      departmentId: createForm.value.departmentId,
      description: createForm.value.description || undefined,
      visibility: createForm.value.visibility
    })
    ElMessage.success(res.note || '项目已创建，仓库正在后台创建')
    createDlg.value = false
    await loadProjects()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '创建失败'))
  } finally {
    creating.value = false
  }
}

// ---------------------------------------------------------------- 初始化
async function loadConfig() {
  cfgLoading.value = true
  configError.value = ''
  try {
    config.value = await giteeConfig()
  } catch (e: unknown) {
    // 拉取**失败** ≠ 模块未启用。前者是「拿不到」（服务未起/网络断/5xx），
    // 后者是「服务明确说没配」。把前者说成后者会让用户去查一个不存在的配置问题。
    // 失败时不崩溃、不继续取数，但**要说清是哪一类**，并给一个明确的重试入口。
    moduleEnabled.value = false
    configError.value =
      `${giteeErrMsg(e, '平台服务未响应（服务未启动、正在重启或网络中断）')}。`
      + '这不代表配置缺失：请确认后端服务可用后重试。'
    ElMessage.warning(giteeErrMsg(e, '无法获取仓库联动配置：平台服务未响应'))
    return
  } finally {
    cfgLoading.value = false
  }
  if (config.value.enabled === false) {
    moduleEnabled.value = false
  } else {
    moduleEnabled.value = true
  }
}

/** 配置拉取失败后的重试入口（不必刷新整页）。 */
async function reload() {
  await loadConfig()
  if (!moduleEnabled.value) {
    return
  }
  await initData()
}

/** 模块可用时拉取的数据：绑定 / 部门 / 项目 /（租户管理员）任务统计 + 企业组织配置。 */
async function initData() {
  await Promise.allSettled([loadBinding(), loadDepartments()])
  await loadProjects()
  if (isTenantAdmin.value) {
    await Promise.allSettled([loadTaskStats(), loadTenantConfig(), loadInitStatus()])
  }
}

onMounted(async () => {
  await loadConfig()
  if (!moduleEnabled.value) return
  await initData()
})

onUnmounted(stopPolling)
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.filters { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.muted { color: #909399; }
.small { font-size: 12px; }
.init-error { color: #f56c6c; font-size: 12px; margin-top: 4px; }
.init-step { display: flex; align-items: baseline; gap: 8px; padding: 4px 8px; border-radius: 4px; font-size: 13px; }
.init-step + .init-step { margin-top: 4px; }
.init-step-icon { font-weight: 700; flex: 0 0 auto; }
.init-step-label { flex: 0 0 auto; }
.init-step-msg { color: #909399; }
.init-step-fail { background: #fef0f0; color: #f56c6c; }
.init-step-fail .init-step-icon,
.init-step-fail .init-step-msg { color: #f56c6c; }
</style>
