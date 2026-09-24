<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="资源授权"
      description="按机构授予专家、技能、模型、知识库、数字员工的可见与可用权限，未授权资源在成员端不可见。差异化计费倍率写入 extra（如 billing_ratio），会参与该机构的费用分摊计算。"
      style="margin-bottom: 12px"
    />

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>机构授权清单（{{ rows.length }}）</span>
          <div>
            <el-select v-model="instId" placeholder="全部机构" size="small" clearable style="width: 210px; margin-right: 8px" @change="loadGrants">
              <el-option v-for="i in institutions" :key="i.id" :label="i.name" :value="i.id" />
            </el-select>
            <el-button text type="primary" size="small" :loading="loading" @click="reloadAll">刷新</el-button>
            <el-button type="primary" size="small" @click="openDlg()">新增授权</el-button>
            <el-button type="primary" size="small" @click="batchDlg = true">批量授权</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="机构" min-width="170">
          <template #default="{ row }">{{ instName(row.institutionId) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ typeText(row.resType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="资源" min-width="150">
          <template #default="{ row }">
            {{ row.resName || row.resKey }}
            <div class="muted small">{{ row.resKey }}</div>
          </template>
        </el-table-column>
        <el-table-column label="计费倍率" width="100">
          <template #default="{ row }">{{ billingRatio(row.extra) ?? '1.0' }}×</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="isOn(row) ? 'success' : 'info'" effect="plain" size="small">
              {{ isOn(row) ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="toggle(row)">{{ isOn(row) ? '停用' : '启用' }}</el-button>
            <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="该机构暂无授权" :image-size="56" />
    </el-card>

    <!-- 可授权资源目录 -->
    <el-card shadow="never" style="margin-top: 12px">
      <template #header><span>可授权资源目录</span></template>
      <el-tabs v-model="catTab">
        <el-tab-pane v-for="g in groups" :key="g.key" :label="g.label + '（' + (g.items.length) + '）'" :name="g.key">
          <el-table :data="g.items" size="small" stripe>
            <el-table-column label="标识" prop="resKey" width="160" />
            <el-table-column label="名称" min-width="200">
              <template #default="{ row }">{{ row.name || row.resKey }}</template>
            </el-table-column>
            <el-table-column v-if="g.key === 'models'" label="供应商" prop="providerKey" width="120" />
            <el-table-column label="资源 ID" prop="id" width="90" />
          </el-table>
          <el-empty v-if="!g.items.length" description="暂无" :image-size="40" />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 新增授权 -->
    <el-dialog v-model="dlg" title="新增机构授权" width="520">
      <el-form :model="form" label-width="110px" size="small">
        <el-form-item label="机构" required>
          <el-select v-model="form.institutionId" style="width: 100%">
            <el-option v-for="i in institutions" :key="i.id" :label="i.name" :value="i.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资源类型" required>
          <el-select v-model="form.resType" style="width: 100%" @change="form.resId = undefined; form.resKey = ''; form.resName = ''">
            <el-option label="专家" value="EXPERT" />
            <el-option label="技能" value="SKILL" />
            <el-option label="模型" value="MODEL" />
            <el-option label="知识库" value="KB" />
            <el-option label="数字员工" value="WORKER" />
          </el-select>
        </el-form-item>
        <el-form-item label="资源" required>
          <el-select v-model="form.resId" style="width: 100%" @change="onPick">
            <el-option v-for="r in currentGroup" :key="r.id" :label="(r.name || r.resKey) + '（' + r.resKey + '）'" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="计费倍率">
          <el-input-number v-model="ratio" :min="0" :max="10" :step="0.1" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量授权 -->
    <el-dialog v-model="batchDlg" title="批量授权" width="560">
      <el-form label-width="110px" size="small">
        <el-form-item label="机构" required>
          <el-select v-model="batchInst" style="width: 100%">
            <el-option v-for="i in institutions" :key="i.id" :label="i.name" :value="i.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资源类型" required>
          <el-select v-model="batchType" style="width: 100%">
            <el-option label="专家" value="EXPERT" />
            <el-option label="技能" value="SKILL" />
            <el-option label="模型" value="MODEL" />
            <el-option label="知识库" value="KB" />
            <el-option label="数字员工" value="WORKER" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择资源">
          <el-select v-model="batchIds" multiple style="width: 100%">
            <el-option v-for="r in batchOptions" :key="r.id" :label="r.name || r.resKey" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="batchDlg = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="submitBatch">批量授予</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError } from '@/api'
import {
  getGrantCatalog, listGrants, createGrant, batchGrant, toggleGrant, deleteGrant, listInstitutions,
  type ResourceGrant, type GrantCatalog, type Institution
} from '@/api/org'

/** 当前是否已启用。后端下发的是 JSON 布尔，但历史数据里也可能是 1/0，两种都认。 */
function isOn(row: ResourceGrant) { return row.enabled === true || row.enabled === 1 }

/** 业务失败是 HTTP 200 + code≠0，异常体是 ApiError（只有 .message，没有 .response）。 */
function errText(e: unknown, fallback: string) {
  if (e instanceof ApiError) return e.message || fallback
  const d = (e as { response?: { data?: { message?: string } } })?.response?.data
  return d?.message || fallback
}

interface CatItem { id: number; resKey?: string; name?: string; providerKey?: string }

const TYPE_TEXT: Record<string, string> = {
  EXPERT: '专家', SKILL: '技能', MODEL: '模型', KB: '知识库', WORKER: '数字员工'
}
function typeText(v?: string) { return TYPE_TEXT[v || ''] || v || '—' }

const loading = ref(false)
const saving = ref(false)
const rows = ref<ResourceGrant[]>([])
const institutions = ref<Institution[]>([])
const catalog = ref<GrantCatalog>({})
const instId = ref<number | null>(null)
const catTab = ref('experts')

const groups = computed(() => [
  { key: 'experts', label: '专家', items: (catalog.value.experts || []) as CatItem[] },
  { key: 'skills', label: '技能', items: (catalog.value.skills || []) as CatItem[] },
  { key: 'models', label: '模型', items: (catalog.value.models || []) as CatItem[] },
  { key: 'kb', label: '知识库', items: (catalog.value.kb || []) as CatItem[] },
  { key: 'workers', label: '数字员工', items: (catalog.value.workers || []) as CatItem[] }
])

function instName(id?: number) {
  return institutions.value.find((i) => i.id === id)?.name || ('#' + id)
}

function billingRatio(extra?: string) {
  if (!extra) return null
  try {
    const o = JSON.parse(extra)
    return o?.billing_ratio ?? o?.billingRatio ?? null
  } catch { return null }
}

async function loadGrants() {
  loading.value = true
  try {
    rows.value = (await listGrants(instId.value ?? undefined)) || []
  } catch (e: unknown) {
    ElMessage.error('授权清单加载失败：' + ((e as Error)?.message || '后端异常'))
    rows.value = []
  } finally {
    loading.value = false
  }
}

async function reloadAll() {
  await Promise.all([
    loadGrants(),
    listInstitutions().then((r) => (institutions.value = r || [])).catch(() => {}),
    getGrantCatalog().then((r) => (catalog.value = r || {})).catch(() => {})
  ])
}
onMounted(reloadAll)

// ---------------------------------------------------------------- 新增授权
const dlg = ref(false)
const ratio = ref(1.0)
const form = ref<Partial<ResourceGrant> & { enabled?: boolean }>({})

const currentGroup = computed(() => {
  const key = ({ EXPERT: 'experts', SKILL: 'skills', MODEL: 'models', KB: 'kb', WORKER: 'workers' } as Record<string, string>)[form.value.resType || '']
  return (groups.value.find((g) => g.key === key)?.items) || []
})

function onPick(id: number) {
  const r = currentGroup.value.find((x) => x.id === id)
  if (r) { form.value.resKey = r.resKey; form.value.resName = r.name || r.resKey }
}

function openDlg() {
  form.value = { resType: 'MODEL', enabled: true }
  ratio.value = 1.0
  dlg.value = true
}

async function submit() {
  if (!form.value.institutionId || !form.value.resId) {
    ElMessage.warning('机构与资源必选')
    return
  }
  saving.value = true
  try {
    await createGrant({
      institutionId: form.value.institutionId,
      resType: form.value.resType,
      resId: form.value.resId,
      resKey: form.value.resKey,
      resName: form.value.resName,
      extra: JSON.stringify({ billing_ratio: ratio.value }),
      enabled: form.value.enabled
    })
    ElMessage.success('授权已添加')
    dlg.value = false
    await loadGrants()
  } catch (e: unknown) {
    ElMessage.error((e as { response?: { data?: { message?: string } } })?.response?.data?.message || '授权失败')
  } finally {
    saving.value = false
  }
}

async function toggle(row: ResourceGrant) {
  // 显式传目标状态（当前的反面）：不能依赖「不带 body 的后端默认值」——
  // 旧后端把缺省当成启用，于是点「停用」永远变成「启用」，表现为操作无效。
  const target = !isOn(row)
  try {
    await toggleGrant(row.id!, target)
    // 成功必须给回执：此前静默成功 + 状态没变，用户无法区分「生效了」和「没反应」。
    ElMessage.success(target ? '已启用' : '已停用')
    await loadGrants()
  } catch (e: unknown) {
    ElMessage.error(errText(e, target ? '启用失败' : '停用失败'))
  }
}

async function remove(row: ResourceGrant) {
  try {
    await deleteGrant(row.id!)
    ElMessage.success('已删除')
    await loadGrants()
  } catch (e: unknown) {
    ElMessage.error((e as { response?: { data?: { message?: string } } })?.response?.data?.message || '删除失败')
  }
}

// ---------------------------------------------------------------- 批量授权
const batchDlg = ref(false)
const batchInst = ref<number | null>(null)
const batchType = ref('MODEL')
const batchIds = ref<number[]>([])

const batchOptions = computed(() => {
  const key = ({ EXPERT: 'experts', SKILL: 'skills', MODEL: 'models', KB: 'kb', WORKER: 'workers' } as Record<string, string>)[batchType.value]
  return (groups.value.find((g) => g.key === key)?.items) || []
})

async function submitBatch() {
  if (!batchInst.value || !batchIds.value.length) {
    ElMessage.warning('请选择机构与资源')
    return
  }
  saving.value = true
  try {
    const r = await batchGrant({
      institutionId: batchInst.value,
      items: batchIds.value.map((id) => {
        const meta = batchOptions.value.find((x) => x.id === id)
        return { resType: batchType.value, resId: id, resName: meta?.name || meta?.resKey, enabled: true }
      })
    })
    ElMessage.success('已授予 ' + (r?.granted ?? batchIds.value.length) + ' 项')
    batchDlg.value = false
    await loadGrants()
  } catch (e: unknown) {
    ElMessage.error((e as { response?: { data?: { message?: string } } })?.response?.data?.message || '批量授权失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: flex-end; gap: 4px; }
.card-header > span:first-child { margin-right: auto; }
.muted { color: #909399; }
.small { font-size: 12px; }
</style>
