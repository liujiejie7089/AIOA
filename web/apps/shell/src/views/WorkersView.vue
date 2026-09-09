<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="数字员工"
      description="自动运行 · 定时产出 · 结果进入用户端待办与消息。停用后历史产出保留，可随时恢复。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>数字员工列表</span>
          <div>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
            <el-button type="primary" size="small" @click="openDlg()">新增数字员工</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="名称" min-width="140">
          <template #default="{ row }">
            <span class="w-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="图标键" prop="icon" width="100" />
        <el-table-column label="说明" prop="description" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.enabled === 1 ? 'success' : 'info'" effect="plain" size="small">
              {{ row.enabled === 1 ? row.status || '运行中' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近产出" prop="lastOutput" min-width="160" show-overflow-tooltip />
        <el-table-column label="运行计划" prop="scheduleText" min-width="160" show-overflow-tooltip />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled === 1"
              size="small"
              @change="() => toggle(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openDlg(row)">编辑</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无数字员工，点击「新增数字员工」创建" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="form.id ? '编辑数字员工' : '新增数字员工'" width="460px">
      <el-form label-width="88px" size="small">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="如：政策快讯员" /></el-form-item>
        <el-form-item label="图标键"><el-input v-model="form.icon" placeholder="bot / bell / pen / megaphone" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="一句话说明这个数字员工做什么" /></el-form-item>
        <el-form-item label="运行计划"><el-input v-model="form.scheduleText" placeholder="如：每日 08:00 / 触发式（有申请即审）" /></el-form-item>
        <el-form-item label="最近产出"><el-input v-model="form.lastOutput" placeholder="如：09-08 早报 · 3 条" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="运行中" value="运行中" />
            <el-option label="待命中" value="待命中" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminCreateWorker,
  adminDeleteWorker,
  adminListWorkers,
  adminToggleWorker,
  adminUpdateWorker,
  type AgentWorker
} from '@/api/resource'

const loading = ref(false)
const rows = ref<AgentWorker[]>([])
const dlg = ref(false)
const form = reactive<Partial<AgentWorker> & { id?: number }>({})

async function reload() {
  loading.value = true
  try {
    rows.value = (await adminListWorkers()) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('数字员工维护仅租户管理员可操作')
      rows.value = []
    } else {
      ElMessage.error('数字员工加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

function openDlg(row?: AgentWorker) {
  Object.assign(form, {
    id: row?.id,
    name: row?.name || '',
    icon: row?.icon || 'bot',
    description: row?.description || '',
    status: row?.status || '运行中',
    lastOutput: row?.lastOutput || '尚未运行',
    scheduleText: row?.scheduleText || ''
  })
  dlg.value = true
}

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  try {
    if (form.id) await adminUpdateWorker(form.id, form)
    else await adminCreateWorker(form)
    ElMessage.success('已保存')
    dlg.value = false
    await reload()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function toggle(row: AgentWorker) {
  try {
    await adminToggleWorker(row.id)
    ElMessage.success(row.enabled === 1 ? '已停用' : '已启用')
    await reload()
  } catch (e: unknown) {
    ElMessage.error('操作失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function remove(row: AgentWorker) {
  try {
    await ElMessageBox.confirm(`确认删除数字员工「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await adminDeleteWorker(row.id)
  ElMessage.success('已删除')
  await reload()
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.w-name {
  font-weight: 600;
}
</style>
