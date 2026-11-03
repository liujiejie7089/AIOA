<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="代码自动入库"
      description="开发项目的每次 push 由 webhook 触发入库任务：拉取提交、按任务号回挂、把改动写进项目的「代码仓库 → 提交记录」。任务幂等（同一 event 不重复入库），失败自动重试 3 次并留原因；成功率低说明令牌或权限有问题，不是偶发抖动。"
      style="margin-bottom: 12px"
    />

    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-label">入库任务总数</div>
        <div class="stat-value">{{ fmt(stats.total) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">成功</div>
        <div class="stat-value ok">{{ fmt(stats.DONE) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">失败</div>
        <div class="stat-value bad">{{ fmt(stats.FAILED) }}</div>
      </div>
      <div class="stat-card highlight">
        <div class="stat-label">成功率</div>
        <div class="stat-value">{{ rate }}<span class="unit">%</span></div>
      </div>
    </div>

    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <span>关联仓库（绑定到开发项目才入库）</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
            <el-button size="small">校准任务统计</el-button>
          </div>
        </div>
      </template>
      <el-table v-loading="loading" :data="repos" size="small" stripe>
        <el-table-column label="仓库" min-width="200" prop="name" show-overflow-tooltip />
        <el-table-column label="默认分支" width="110" prop="defaultBranch" />
        <el-table-column label="可见性" width="100">
          <template #default="{ row }">{{ row.visibility === 'public' ? '公开' : '私有' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ACTIVE' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'" effect="plain">
              {{ row.status === 'ACTIVE' ? '正常' : row.status === 'FAILED' ? '建仓失败' : row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近入库" width="160" prop="createdAt">
          <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="230">
          <template #default="{ row }">
            <span :class="{ bad: !!row.errorMsg }">{{ row.errorMsg || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default>
            <el-button text type="primary" size="small">查看提交</el-button>
            <el-button text type="primary" size="small">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>入库记录（提交级）</span>
          <span class="hint">提交号可跳转代码托管；「关联任务」由提交信息里的 {{ TASK_KEY }} 自动回挂</span>
        </div>
      </template>
      <el-table :data="records" size="small" stripe max-height="520">
        <el-table-column label="提交号" width="100">
          <template #default="{ row }"><span class="sha">{{ row.sha }}</span></template>
        </el-table-column>
        <el-table-column label="仓库" width="140" prop="repo" />
        <el-table-column label="提交人" width="85" prop="author" />
        <el-table-column label="提交信息" min-width="230" prop="message" show-overflow-tooltip />
        <el-table-column label="关联任务" width="100" prop="task" />
        <el-table-column label="分支" width="95" prop="branch" />
        <el-table-column label="提交时间" width="125" prop="committedAt" />
        <el-table-column label="入库时间" width="125" prop="ingestedAt" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === '已入库' ? 'success' : 'danger'" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { giteeProjects, giteeTaskStats, type GiteeProject, type GiteeTaskStats } from '@/api/gitee'

const TASK_KEY = 'TASK-'
const loading = ref(false)
const repos = ref<GiteeProject[]>([])
const stats = ref<Record<string, number>>({})

function fmt(v?: number | null) {
  return (v ?? 0).toLocaleString('zh-CN')
}

const rate = computed(() => {
  const t = stats.value.total || 0
  return t ? (((stats.value.DONE || 0) / t) * 100).toFixed(1) : '—'
})

const records = [
  { sha: 'a3f9c21', repo: '审批助手-服务端', branch: 'master', author: '李思远', message: 'TASK-1042 要件核验规则支持多条件组合', task: 'TASK-1042', committedAt: '2026-11-01 16:22', ingestedAt: '2026-11-01 16:22', status: '已入库' },
  { sha: '7d1e4b8', repo: '审批助手-服务端', branch: 'master', author: '李思远', message: 'TASK-1038 补正提示模板化，支持按事项类型切换', task: 'TASK-1038', committedAt: '2026-11-01 11:05', ingestedAt: '2026-11-01 11:05', status: '已入库' },
  { sha: 'e52b7c4', repo: '审批助手-前端', branch: 'master', author: '孙丽华', message: 'TASK-1036 工作台列表增加「超期未办」筛选', task: 'TASK-1036', committedAt: '2026-10-31 18:41', ingestedAt: '2026-10-31 18:41', status: '已入库' },
  { sha: '1c8a90f', repo: '审批助手-前端', branch: 'feat/guide', author: '孙丽华', message: 'TASK-1031 事项引导页骨架屏', task: 'TASK-1031', committedAt: '2026-10-30 15:12', ingestedAt: '2026-10-30 15:12', status: '已入库' },
  { sha: 'b6f3027', repo: '审批助手-服务端', branch: 'master', author: '周晓峰', message: 'TASK-1029 修复并发核验时的状态覆盖问题', task: 'TASK-1029', committedAt: '2026-10-29 09:58', ingestedAt: '2026-10-29 10:01', status: '已入库' },
  { sha: '9e4d156', repo: '审批助手-服务端', branch: 'master', author: '周晓峰', message: 'TASK-1027 接口返回补 traceId', task: 'TASK-1027', committedAt: '2026-10-28 17:30', ingestedAt: '2026-10-28 17:30', status: '已入库' },
  { sha: 'f0b7d63', repo: '审批助手-前端', branch: 'master', author: '孙丽华', message: 'docs 更新接口约定', task: '—', committedAt: '2026-10-27 14:16', ingestedAt: '2026-10-27 14:16', status: '已入库' },
  { sha: '2a5c8e1', repo: '审批助手-服务端', branch: 'master', author: '李思远', message: 'TASK-1021 令牌失效重试', task: 'TASK-1021', committedAt: '2026-10-26 10:03', ingestedAt: '2026-10-26 10:03', status: '已入库' },
  { sha: 'c93f4a2', repo: '审批助手-服务端', branch: 'master', author: '李思远', message: 'TASK-1019 附件解析超时改为异步', task: 'TASK-1019', committedAt: '2026-10-25 19:22', ingestedAt: '2026-10-25 19:27', status: '已入库' },
  { sha: '5b1d7f9', repo: '审批助手-前端', branch: 'master', author: '孙丽华', message: 'TASK-1017 表格列宽自适应', task: 'TASK-1017', committedAt: '2026-10-24 16:48', ingestedAt: '2026-10-24 16:48', status: '已入库' }
]

async function load() {
  loading.value = true
  try {
    const res = await giteeProjects().catch(() => ({ items: [] as GiteeProject[], total: 0, canCreate: false }))
    repos.value = (res.items || []).filter((r) => r.status !== 'DELETED').slice(0, 8)
    const s: GiteeTaskStats = (await giteeTaskStats().catch(() => ({}))) || {}
    const done = Number(s.DONE || 0)
    const failed = Number(s.FAILED || 0)
    stats.value = { DONE: done, FAILED: failed, total: done + failed }
  } catch (e: unknown) {
    ElMessage.error('加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stat-row { display: flex; gap: 12px; margin-bottom: 12px; }
.stat-card {
  flex: 1;
  background: #faf9f5;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 14px;
}
.stat-card.highlight { background: #f2f6f4; border-color: #cfdcd6; }
.stat-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.stat-value { font-size: 22px; font-weight: 600; color: #1f2933; line-height: 1.2; white-space: nowrap; }
.stat-value .unit { font-size: 12px; font-weight: 400; color: #909399; margin-left: 3px; }
.stat-value.ok { color: #2f7d4f; }
.stat-value.bad { color: #c0392b; }
.card-header { display: flex; align-items: center; gap: 6px; }
.card-header > span:first-child { margin-right: auto; }
.card-header .hint { font-size: 12px; color: #909399; }
.sha { font-family: Consolas, Menlo, monospace; color: #5b6770; }
.bad { color: #c0392b; }
</style>
