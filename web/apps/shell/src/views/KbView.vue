<template>
  <div>
    <el-alert
      v-if="tenantForbidden"
      type="info"
      :closable="false"
      show-icon
      title="「租户全部资料」仅租户管理员可见"
      description="普通用户可在下方「我的资料」上传与管理自己的知识文档。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <el-tabs v-model="tab" class="flex-tabs" @tab-change="reload">
            <el-tab-pane label="租户全部资料" name="tenant" />
            <el-tab-pane label="我的资料" name="mine" />
          </el-tabs>
          <div class="actions">
            <span class="scope-label">上传范围</span>
            <el-select v-model="uploadScope" size="small" style="width: 116px">
              <el-option label="租户共享" value="TENANT" />
              <el-option label="仅我个人" value="PERSONAL" />
            </el-select>
            <el-upload
              class="upload-btn"
              :show-file-list="false"
              :accept="KB_ACCEPT"
              :http-request="onUpload"
              :multiple="true"
            >
              <el-button type="primary" size="small">上传文件</el-button>
            </el-upload>
            <el-button text type="primary" size="small" :loading="loading" @click="reload">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="hint">
        支持 PDF、Word（doc/docx）、Excel（xls/xlsx）、TXT、Markdown、CSV，单文件最大 {{ KB_MAX_MB }}MB；
        上传后自动解析正文 → 切片入库，状态为「已入库」即可被 AI 检索并引用溯源。
      </div>

      <div v-if="uploading.length" class="uploading">
        <div v-for="u in uploading" :key="u.name" class="up-row">
          <span class="up-name">{{ u.name }}</span>
          <el-progress :percentage="u.percent" :status="u.percent >= 100 ? 'success' : undefined" style="flex: 1" />
        </div>
      </div>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="资料" min-width="260">
          <template #default="{ row }">
            <span class="doc-name">
              <span class="doc-icon">{{ iconOf(row) }}</span>
              <span class="doc-title">{{ row.name }}</span>
            </span>
            <div v-if="row.errorMsg" class="err">解析失败：{{ row.errorMsg }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="stateTag(row.state)" effect="plain">{{ stateLabel(row.state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="切片" width="80">
          <template #default="{ row }">{{ row.chunkCount ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ fmtSize(row.sizeBytes) }}</template>
        </el-table-column>
        <el-table-column label="可见范围" width="120">
          <template #default="{ row }">
            <el-select
              v-model="row.scope"
              size="small"
              style="width: 100px"
              @change="(v: string) => changeScope(row, v)"
            >
              <el-option label="租户共享" value="TENANT" />
              <el-option label="仅我个人" value="PERSONAL" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column v-if="tab === 'tenant'" label="归属用户" width="100">
          <template #default="{ row }">{{ row.ownerUserId ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="登记时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.state !== 'ok'" text type="warning" size="small" @click="retry(row)">重试</el-button>
            <el-button text type="primary" size="small" @click="rename(row)">重命名</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="tab === 'tenant' ? '租户内暂无资料' : '还没有上传资料，点击右上角「上传文件」开始'"
            :image-size="80"
          />
        </template>
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-top: 12px">
      <template #header>
        <div class="card-header">
          <span>检索测试</span>
          <span class="sub">验证入库内容可被检索到，并会作为引用来源返回给 AI</span>
        </div>
      </template>
      <div class="search-bar">
        <el-input v-model="keyword" placeholder="输入关键词，如：报销、产业扶持、公积金" clearable @keyup.enter="doSearch" />
        <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
      </div>
      <div v-if="searched" class="hits">
        <el-empty v-if="!hits.length" description="未命中任何资料" :image-size="60" />
        <div v-for="(h, i) in hits" :key="i" class="hit">
          <div class="hit-head">
            <span class="hit-idx">#{{ i + 1 }}</span>
            <span class="hit-doc">{{ h.docName }}</span>
            <el-tag v-if="h.chunkIndex !== null && h.chunkIndex !== undefined" size="small" effect="plain">
              片段 {{ h.chunkIndex }}
            </el-tag>
          </div>
          <div class="hit-text">{{ h.snippet || '（该资料仅有元信息，无正文片段）' }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import {
  KB_ACCEPT,
  KB_MAX_MB,
  deleteKbDoc,
  listKbDocs,
  retryKbDoc,
  searchKb,
  updateKbDoc,
  uploadKbFile,
  type KbDoc,
  type KbHit,
} from '@/api/resource'

const tab = ref<'tenant' | 'mine'>('tenant')
const loading = ref(false)
const tenantRows = ref<KbDoc[]>([])
const mineRows = ref<KbDoc[]>([])
const tenantForbidden = ref(false)
const uploadScope = ref<'TENANT' | 'PERSONAL'>('TENANT')

const uploading = ref<{ name: string; percent: number }[]>([])

const keyword = ref('')
const hits = ref<KbHit[]>([])
const searched = ref(false)
const searching = ref(false)

const rows = computed(() => (tab.value === 'tenant' ? tenantRows.value : mineRows.value))

const ICONS: Record<string, string> = { pdf: '📕', doc: '📄', sheet: '📊', file: '📁' }

function iconOf(row: KbDoc): string {
  if (row.icon && ICONS[row.icon]) return ICONS[row.icon]
  const n = (row.name || '').toLowerCase()
  if (n.endsWith('.pdf')) return '📕'
  if (n.endsWith('.xlsx') || n.endsWith('.xls') || n.endsWith('.csv')) return '📊'
  if (n.endsWith('.docx') || n.endsWith('.doc') || n.endsWith('.txt') || n.endsWith('.md')) return '📄'
  return '📁'
}

function stateLabel(s: string): string {
  if (s === 'ok') return '已入库'
  if (s === 'failed') return '解析失败'
  return '解析中'
}
function stateTag(s: string): 'success' | 'danger' | 'warning' {
  if (s === 'ok') return 'success'
  if (s === 'failed') return 'danger'
  return 'warning'
}
function fmtSize(b?: number): string {
  if (!b) return '—'
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}
function fmtTime(t?: string): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

async function loadTenant() {
  tenantForbidden.value = false
  try {
    tenantRows.value = (await listKbDocs('tenant')) || []
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      tenantForbidden.value = true
      tenantRows.value = []
    } else {
      ElMessage.error('资料列表加载失败，请确认后端已启动')
    }
  }
}

async function loadMine() {
  try {
    mineRows.value = (await listKbDocs()) || []
  } catch {
    mineRows.value = []
  }
}

async function reload() {
  loading.value = true
  try {
    await Promise.allSettled([loadTenant(), loadMine()])
  } finally {
    loading.value = false
  }
}

async function onUpload(opt: UploadRequestOptions) {
  const file = opt.file as File
  const mb = file.size / 1024 / 1024
  if (mb > KB_MAX_MB) {
    ElMessage.error(`${file.name} 超过 ${KB_MAX_MB}MB 上限，请拆分后上传`)
    return
  }
  const item = { name: file.name, percent: 0 }
  uploading.value.push(item)
  try {
    const doc = await uploadKbFile(file, uploadScope.value, (p) => (item.percent = p))
    item.percent = 100
    if (doc.state === 'ok') {
      ElMessage.success(`「${doc.name}」已入库，共 ${doc.chunkCount ?? 0} 个切片`)
    } else if (doc.state === 'failed') {
      ElMessage.error(`「${doc.name}」入库失败：${doc.errorMsg || '未知原因'}`)
    } else {
      ElMessage.warning(`「${doc.name}」已登记，等待解析`)
    }
    await reload()
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message
    ElMessage.error(`「${file.name}」上传失败：${msg || (e as Error)?.message || '后端异常'}`)
  } finally {
    setTimeout(() => {
      uploading.value = uploading.value.filter((u) => u !== item)
    }, 600)
  }
}

async function retry(row: KbDoc) {
  try {
    const doc = await retryKbDoc(row.id)
    ElMessage.success(doc.state === 'ok' ? `「${doc.name}」已重新入库，${doc.chunkCount ?? 0} 个切片` : `已重试：${doc.errorMsg || doc.state}`)
    await reload()
  } catch (e: unknown) {
    ElMessage.error('重试失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function changeScope(row: KbDoc, v: string) {
  try {
    await updateKbDoc(row.id, { scope: v as 'PERSONAL' | 'TENANT' })
    ElMessage.success(`「${row.name}」可见范围已更新为${v === 'TENANT' ? '租户共享' : '仅我个人'}`)
    await reload()
  } catch (e: unknown) {
    ElMessage.error('更新失败：' + ((e as Error)?.message || '后端异常'))
    await reload()
  }
}

async function rename(row: KbDoc) {
  try {
    const { value } = await ElMessageBox.prompt('修改资料显示名称', '重命名', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: row.name,
      inputValidator: (v: string) => !!v?.trim() || '名称不能为空',
    })
    await updateKbDoc(row.id, { name: value.trim() })
    ElMessage.success('已重命名')
    await reload()
  } catch (e: unknown) {
    if (e === 'cancel' || (e as { message?: string })?.message === 'cancel') return
    ElMessage.error('重命名失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function remove(row: KbDoc) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.name}」？其切片会一并移除，且不可恢复。`, '删除资料', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  try {
    await deleteKbDoc(row.id)
    ElMessage.success('已删除')
    await reload()
  } catch (e: unknown) {
    ElMessage.error('删除失败：' + ((e as Error)?.message || '后端异常'))
  }
}

async function doSearch() {
  const q = keyword.value.trim()
  if (!q) {
    ElMessage.warning('请输入检索关键词')
    return
  }
  searching.value = true
  searched.value = true
  try {
    hits.value = (await searchKb(q)) || []
  } catch (e: unknown) {
    hits.value = []
    ElMessage.error('检索失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    searching.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scope-label {
  font-size: 12px;
  color: #909399;
}

.upload-btn {
  display: inline-flex;
}

.flex-tabs {
  flex: 1;
}

.flex-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.7;
  margin-bottom: 12px;
}

.uploading {
  margin-bottom: 12px;
}

.up-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.up-name {
  width: 220px;
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.doc-icon {
  font-size: 16px;
}

.doc-title {
  word-break: break-all;
}

.err {
  margin-top: 4px;
  font-size: 12px;
  color: #f56c6c;
}

.sub {
  font-size: 12px;
  color: #909399;
}

.search-bar {
  display: flex;
  gap: 8px;
}

.search-bar :deep(.el-input) {
  max-width: 420px;
}

.hits {
  margin-top: 14px;
}

.hit {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fafafa;
}

.hit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.hit-idx {
  font-size: 12px;
  color: #909399;
}

.hit-doc {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.hit-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
