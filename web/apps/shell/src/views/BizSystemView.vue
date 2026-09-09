<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="业务系统注册与配置"
      description="统一录入、查看和维护已接入业务系统的接口地址、认证方式与密钥、接口文档。密钥等敏感信息出参自动掩码；存储层抽象可替换，切换不影响已接入系统。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>已接入业务系统</span>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-input
              v-model="q"
              placeholder="按名称 / 编码搜索"
              clearable
              size="small"
              style="width: 200px"
              @keyup.enter="reload"
              @clear="reload"
            />
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
            <el-button type="primary" size="small" @click="openDlg()">注册业务系统</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="系统编码" prop="systemCode" width="150">
          <template #default="{ row }"><span class="code">{{ row.systemCode }}</span></template>
        </el-table-column>
        <el-table-column label="系统名称" min-width="140">
          <template #default="{ row }"><span class="name">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column label="接口地址" prop="baseUrl" min-width="200" show-overflow-tooltip />
        <el-table-column label="认证方式" width="100">
          <template #default="{ row }">
            <el-tag effect="plain" size="small" :type="authTagType(row.authType)">{{ row.authType }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="接口文档" width="90">
          <template #default="{ row }">
            <el-button v-if="row.docUrl || row.docContent" text type="primary" size="small" @click="showDoc(row)">查看</el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ENABLED' ? 'success' : 'info'" effect="plain" size="small">
              {{ row.status === 'ENABLED' ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="110">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openDlg(row)">编辑</el-button>
            <el-button text type="warning" size="small" @click="toggle(row)">{{ row.status === 'ENABLED' ? '停用' : '启用' }}</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="尚未注册业务系统，点击「注册业务系统」开始接入" :image-size="70" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="form.id ? '编辑业务系统' : '注册业务系统'" width="640px">
      <el-form label-width="92px" size="small">
        <el-form-item label="系统编码">
          <el-input v-model="form.systemCode" :disabled="!!form.id" placeholder="如 OA_FINANCE（字母/数字/下划线/中划线）" />
          <div class="hint">租户内唯一，创建后不可修改</div>
        </el-form-item>
        <el-form-item label="系统名称"><el-input v-model="form.name" placeholder="如：财务 OA 系统" /></el-form-item>
        <el-form-item label="系统说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="一句话说明该系统用途" /></el-form-item>
        <el-form-item label="接口地址"><el-input v-model="form.baseUrl" placeholder="如 https://oa.example.com/api" /></el-form-item>
        <el-form-item label="认证方式">
          <el-select v-model="form.authType" style="width: 220px">
            <el-option label="无认证 NONE" value="NONE" />
            <el-option label="请求头密钥 API_KEY" value="API_KEY" />
            <el-option label="基础认证 BASIC" value="BASIC" />
            <el-option label="令牌 BEARER" value="BEARER" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.authType && form.authType !== 'NONE'" label="认证配置">
          <el-input
            v-model="form.authConfig"
            type="textarea"
            :rows="2"
            :placeholder="authPlaceholder"
          />
          <div class="hint">JSON 格式；保存时敏感字段值为 ****** 表示保留原值</div>
        </el-form-item>
        <el-form-item label="接口文档链接"><el-input v-model="form.docUrl" placeholder="如 https://wiki.example.com/oa-api" /></el-form-item>
        <el-form-item label="接口文档内容">
          <el-input v-model="form.docContent" type="textarea" :rows="4" placeholder="Markdown 或纯文本的接口说明（可粘贴自接口文档）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="docDlg" :title="`接口文档 · ${docRow?.name || ''}`" size="44%">
      <template v-if="docRow">
        <div v-if="docRow.docUrl" style="margin-bottom: 10px">
          <el-link type="primary" :href="docRow.docUrl" target="_blank">{{ docRow.docUrl }}</el-link>
        </div>
        <pre v-if="docRow.docContent" class="doc-pre">{{ docRow.docContent }}</pre>
        <el-empty v-else description="未录入文档内容" :image-size="70" />
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createBizSystem,
  deleteBizSystem,
  listBizSystems,
  toggleBizSystem,
  updateBizSystem,
  type BizSystem
} from '@/api/resource'

const loading = ref(false)
const rows = ref<BizSystem[]>([])
const q = ref('')
const dlg = ref(false)
const form = reactive<Partial<BizSystem> & { id?: number }>({})
const docDlg = ref(false)
const docRow = ref<BizSystem | null>(null)

const authPlaceholder = computed(() => {
  switch (form.authType) {
    case 'API_KEY':
      return '{"header": "X-API-Key", "apiKey": "******"}'
    case 'BASIC':
      return '{"username": "svc-oa", "password": "******"}'
    case 'BEARER':
      return '{"token": "******"}'
    default:
      return '{}'
  }
})

async function reload() {
  loading.value = true
  try {
    rows.value = (await listBizSystems(q.value || undefined)) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      ElMessage.error('业务系统管理仅租户管理员可操作')
      rows.value = []
    } else {
      ElMessage.error('业务系统加载失败：' + ((e as Error)?.message || '后端异常'))
    }
  } finally {
    loading.value = false
  }
}

function openDlg(row?: BizSystem) {
  Object.assign(form, {
    id: row?.id,
    systemCode: row?.systemCode || '',
    name: row?.name || '',
    description: row?.description || '',
    baseUrl: row?.baseUrl || '',
    authType: row?.authType || 'NONE',
    authConfig: row?.authConfig || '',
    docUrl: row?.docUrl || '',
    docContent: row?.docContent || ''
  })
  dlg.value = true
}

async function save() {
  if (!form.systemCode?.trim() && !form.id) {
    ElMessage.warning('请填写系统编码')
    return
  }
  if (!form.name?.trim()) {
    ElMessage.warning('请填写系统名称')
    return
  }
  try {
    if (form.id) await updateBizSystem(form.id, form)
    else await createBizSystem(form)
    ElMessage.success('已保存')
    dlg.value = false
    await reload()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function toggle(row: BizSystem) {
  try {
    await toggleBizSystem(row.id)
    ElMessage.success(row.status === 'ENABLED' ? '已停用' : '已启用')
    await reload()
  } catch (e: unknown) {
    ElMessage.error('操作失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function remove(row: BizSystem) {
  try {
    await ElMessageBox.confirm(
      `确认删除业务系统「${row.name}（${row.systemCode}）」？删除后不可恢复`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await deleteBizSystem(row.id)
  ElMessage.success('已删除')
  await reload()
}

function showDoc(row: BizSystem) {
  docRow.value = row
  docDlg.value = true
}

function authTagType(t: string): 'info' | 'warning' | 'danger' | 'success' {
  switch (t) {
    case 'NONE':
      return 'info'
    case 'API_KEY':
      return 'warning'
    case 'BASIC':
      return 'danger'
    default:
      return 'success'
  }
}

function fmtTime(t?: string | null): string {
  return t ? String(t).replace('T', ' ').slice(0, 10) : ''
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.code {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 12px;
}

.name {
  font-weight: 600;
}

.muted {
  color: var(--el-text-color-secondary);
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 2px;
}

.doc-pre {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px;
  margin: 0;
}
</style>
