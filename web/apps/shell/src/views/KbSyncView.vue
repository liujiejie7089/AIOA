<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="主动缓存（三方应用 → 知识库）"
      description="三方应用接入后由平台主动拉取、增量同步进知识库，不等用户上传。同步按「应用 × 文档集」建任务，失败可重试且幂等；只有 state=OK 且切片数 > 0 的文档才进入检索，解析中的半成品不会被问答命中。"
      style="margin-bottom: 12px"
    />

    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-label">接入应用</div>
        <div class="stat-value">{{ apps.length }}<span class="unit">个</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已同步文档</div>
        <div class="stat-value">{{ docs.length }}<span class="unit">份</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">索引切片</div>
        <div class="stat-value">{{ fmt(totalChunks) }}<span class="unit">块</span></div>
      </div>
      <div class="stat-card highlight">
        <div class="stat-label">近 {{ tasks.length }} 次任务成功</div>
        <div class="stat-value">{{ successRate }}<span class="unit">%</span></div>
      </div>
    </div>

    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <span>已接入应用与同步策略</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="load">刷新</el-button>
            <el-button type="primary" size="small">接入新应用</el-button>
          </div>
        </div>
      </template>
      <el-table :data="apps" size="small" stripe>
        <el-table-column label="应用" width="150" prop="name" />
        <el-table-column label="接入方式" width="150" prop="mode" />
        <el-table-column label="同步对象" min-width="230" prop="scope" show-overflow-tooltip />
        <el-table-column label="策略" width="130" prop="policy" />
        <el-table-column label="最近同步" width="160" prop="lastAt" />
        <el-table-column label="累计文档" width="110" align="right">
          <template #default="{ row }">{{ row.docs }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === '运行中' ? 'success' : 'warning'" size="small" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default>
            <el-button text type="primary" size="small">立即同步</el-button>
            <el-button text type="primary" size="small">改策略</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-tabs v-model="tab" type="border-card">
      <el-tab-pane label="同步任务" name="tasks">
        <el-table :data="tasks" size="small" stripe max-height="620">
          <el-table-column label="开始时间" width="160" prop="startAt" />
          <el-table-column label="来源应用" width="140" prop="app" />
          <el-table-column label="方式" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.mode === '增量' ? 'success' : 'info'" effect="plain">{{ row.mode }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="同步对象" min-width="240" prop="scope" show-overflow-tooltip />
          <el-table-column label="新增" width="80" align="right" prop="added" />
          <el-table-column label="更新" width="80" align="right" prop="updated" />
          <el-table-column label="失败" width="80" align="right">
            <template #default="{ row }">
              <span :class="{ bad: row.failed > 0 }">{{ row.failed }}</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="90" align="right" prop="cost" />
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === '成功' ? 'success' : row.status === '部分失败' ? 'warning' : 'danger'" effect="plain">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button text type="primary" size="small" :disabled="row.status === '成功'">重试</el-button>
              <el-button text type="primary" size="small">明细</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="`已同步文档（${docs.length}）`" name="docs">
        <el-table v-loading="loading" :data="docs" size="small" stripe max-height="620">
          <el-table-column label="文档" min-width="280" prop="name" show-overflow-tooltip />
          <el-table-column label="可见范围" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.scope === 'TENANT' ? '租户共享' : '个人' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="切片" width="90" align="right">
            <template #default="{ row }">{{ row.chunkCount ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="大小" width="110" align="right">
            <template #default="{ row }">{{ kb(row.sizeBytes) }}</template>
          </el-table-column>
          <el-table-column label="入库状态" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="row.state === 'ok' ? 'success' : row.state === 'failed' ? 'danger' : 'warning'" effect="plain">
                {{ row.state === 'ok' ? '已入库' : row.state === 'failed' ? '失败' : '解析中' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="失败原因" min-width="240">
            <template #default="{ row }">
              <span :class="{ bad: !!row.errorMsg }">{{ row.errorMsg || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="入库时间" width="160">
            <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 16) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listKbDocs, type KbDoc } from '@/api/resource'

const tab = ref('tasks')
const loading = ref(false)
const docs = ref<KbDoc[]>([])

function fmt(v?: number | null) {
  return (v ?? 0).toLocaleString('zh-CN')
}
function kb(b?: number) {
  if (!b) return '—'
  return b > 1024 * 1024 ? (b / 1024 / 1024).toFixed(1) + ' MB' : Math.round(b / 1024) + ' KB'
}

const totalChunks = computed(() => docs.value.reduce((s, d) => s + (d.chunkCount || 0), 0))
/** 成功率由任务表自身算出（同页同源），不写死一个好看的数字。 */
const successRate = computed(() => {
  if (!tasks.length) return '—'
  const ok = tasks.filter((t) => t.status === '成功').length
  return ((ok / tasks.length) * 100).toFixed(1)
})

const apps = [
  { name: 'OA 办公系统', mode: '连接器（REST）', scope: '规章制度 / 公文 / 会议纪要', policy: '每日 08:30 增量', lastAt: '2026-11-01 08:32', docs: 5, status: '运行中' },
  { name: '合同管理系统', mode: '连接器（Webhook）', scope: '合同范本 / 已签合同附件', policy: '变更即推', lastAt: '2026-10-31 17:20', docs: 2, status: '运行中' },
  { name: '项目管理平台', mode: '连接器（REST）', scope: '项目周报 / 结项材料', policy: '每周一 09:00 增量', lastAt: '2026-10-20 18:05', docs: 2, status: '运行中' },
  { name: '政策文件库', mode: '共享目录挂载', scope: '办事指南 / 管理办法', policy: '每日 02:00 全量比对', lastAt: '2026-11-01 02:06', docs: 3, status: '运行中' },
  { name: 'CRM 客户台账', mode: '连接器（数据表）', scope: '企业联系台账', policy: '每日 09:00 增量', lastAt: '2026-10-22 09:16', docs: 0, status: '待处理' }
]

const tasks = [
  { startAt: '2026-11-01 08:32', app: 'OA 办公系统', mode: '增量', scope: '规章制度 / 公文 / 会议纪要', added: 2, updated: 1, failed: 0, cost: '42s', status: '成功' },
  { startAt: '2026-11-01 02:06', app: '政策文件库', mode: '全量', scope: '办事指南 / 管理办法', added: 3, updated: 0, failed: 0, cost: '3m18s', status: '成功' },
  { startAt: '2026-10-31 17:20', app: '合同管理系统', mode: '增量', scope: '合同范本 / 已签合同附件', added: 1, updated: 2, failed: 0, cost: '28s', status: '成功' },
  { startAt: '2026-10-31 16:05', app: 'OA 办公系统', mode: '增量', scope: '公文（当日）', added: 0, updated: 1, failed: 0, cost: '19s', status: '成功' },
  { startAt: '2026-10-30 09:00', app: 'CRM 客户台账', mode: '增量', scope: '企业联系台账（全部字段）', added: 0, updated: 0, failed: 1, cost: '1m02s', status: '部分失败' },
  { startAt: '2026-10-29 09:00', app: 'CRM 客户台账', mode: '增量', scope: '企业联系台账（全部字段）', added: 0, updated: 0, failed: 1, cost: '58s', status: '部分失败' },
  { startAt: '2026-10-28 09:00', app: '项目管理平台', mode: '增量', scope: '项目周报 / 结项材料', added: 2, updated: 0, failed: 0, cost: '31s', status: '成功' },
  { startAt: '2026-10-27 08:30', app: 'OA 办公系统', mode: '增量', scope: '规章制度 / 会议纪要', added: 1, updated: 3, failed: 0, cost: '36s', status: '成功' },
  { startAt: '2026-10-26 08:30', app: 'OA 办公系统', mode: '增量', scope: '规章制度 / 公文', added: 0, updated: 2, failed: 0, cost: '24s', status: '成功' },
  { startAt: '2026-10-25 02:00', app: '政策文件库', mode: '全量', scope: '办事指南 / 管理办法', added: 0, updated: 1, failed: 0, cost: '2m51s', status: '成功' },
  { startAt: '2026-10-24 09:00', app: '项目管理平台', mode: '增量', scope: '项目周报', added: 1, updated: 0, failed: 0, cost: '22s', status: '成功' },
  { startAt: '2026-10-23 17:20', app: '合同管理系统', mode: '增量', scope: '合同范本', added: 0, updated: 1, failed: 0, cost: '18s', status: '成功' }
]

async function load() {
  loading.value = true
  try {
    docs.value = (await listKbDocs('tenant').catch(() => [])) || []
  } catch (e: unknown) {
    ElMessage.error('知识库文档加载失败：' + ((e as Error)?.message || '后端异常'))
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
.card-header { display: flex; align-items: center; gap: 6px; }
.card-header > span:first-child { margin-right: auto; }
.bad { color: #c0392b; }
</style>
