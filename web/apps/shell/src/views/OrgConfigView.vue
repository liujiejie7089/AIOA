<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="机构参数配置（需求二 / docs/44 §2.4）"
      description="为本机构覆盖租户级运行参数；未覆盖的项自动继承租户值。机构管理员仅能配置本机构，平台 / 租户管理员可切换机构。所有变更写入操作审计留痕。"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-if="forbidden"
      type="warning"
      :closable="false"
      show-icon
      title="无权访问机构参数"
      description="当前账号没有机构参数管理权限（org:config:manage），如需授权请联系平台 / 租户管理员。"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-else-if="loaded && !canManage"
      type="info"
      :closable="false"
      show-icon
      title="仅可查看"
      description="当前账号无编辑权限，参数列表为只读展示。"
      style="margin-bottom: 12px"
    />

    <!-- 机构选择器：scopeLocked（机构管理员）时禁用，只读展示本机构 -->
    <el-card shadow="never" style="margin-bottom: 12px">
      <template #header>
        <div class="card-header">
          <span>选择机构</span>
          <el-button text type="primary" size="small" :loading="metaLoading" @click="reloadMeta">刷新机构列表</el-button>
        </div>
      </template>

      <el-select
        v-if="!scopeLocked"
        v-model="institutionId"
        filterable
        placeholder="请选择机构"
        style="width: 320px"
        :loading="metaLoading"
        @change="onInstitutionChange"
      >
        <el-option v-for="o in institutions" :key="o.id" :label="o.name" :value="o.id" />
      </el-select>
      <el-tag v-else size="medium" type="success" effect="plain">
        {{ currentInstitutionName || `机构 ${institutionId}` }}
      </el-tag>
      <div class="hint">
        <template v-if="scopeLocked">机构管理员权限已钉死本机构，不可切换。</template>
        <template v-else>切换机构后将加载该机构的参数覆盖情况。</template>
      </div>
    </el-card>

    <!-- 未选机构：不发参数列表 -->
    <el-empty
      v-if="!forbidden && institutionId == null"
      description="请选择机构以查看参数"
      :image-size="90"
    />

    <!-- 参数分组 -->
    <template v-else-if="!forbidden">
      <el-card
        v-for="(list, code) in grouped"
        :key="code"
        shadow="never"
        style="margin-bottom: 12px"
      >
        <template #header>
          <div class="card-header">
            <span>{{ groups[code] ?? code }}（{{ list.length }} 项）</span>
            <el-button text type="primary" size="small" :loading="loading" @click="reloadItems">刷新</el-button>
          </div>
        </template>

        <div v-for="c in list" :key="c.configKey" class="oc-row">
          <div class="oc-row-head">
            <span class="oc-name">{{ c.configName }}</span>
            <el-tooltip :content="c.configKey" placement="top">
              <span class="oc-key">{{ c.configKey }}</span>
            </el-tooltip>
            <el-tag v-if="c.overridden" type="warning" size="small" effect="light" round>本机构已覆盖</el-tag>
          </div>

          <div class="oc-inherit">
            <template v-if="c.overridden">
              <el-tag type="warning" size="small" effect="plain">本机构值（已覆盖租户值）</el-tag>
            </template>
            <template v-else>
              <el-tag type="info" size="small" effect="plain">继承租户值</el-tag>
            </template>
            <span class="oc-tenant">租户值（继承源）：{{ c.tenantValue || '—' }}</span>
            <span class="oc-effective">生效值：{{ c.effectiveValue || '—' }}</span>
          </div>

          <div class="oc-control">
            <el-input
              v-model="draft[c.configKey]"
              :disabled="!canManage"
              :type="c.valueType === 'INT' || c.valueType === 'DECIMAL' ? 'number' : 'text'"
              :class="{ 'oc-input--dirty': isDirty(c) }"
              style="max-width: 420px"
              placeholder="输入覆盖值"
            />
            <el-button
              type="primary"
              size="small"
              :loading="savingKeys.has(c.configKey)"
              :disabled="!canManage || !isDirty(c)"
              @click="saveOne(c)"
            >
              保存
            </el-button>
            <el-button
              v-if="c.overridden"
              type="warning"
              plain
              size="small"
              :loading="restoringKey === c.configKey"
              :disabled="!canManage"
              @click="restoreOne(c)"
            >
              恢复继承
            </el-button>
            <span v-if="isDirty(c)" class="oc-dirty-hint">未保存</span>
          </div>
        </div>

        <el-empty v-if="!list.length" description="该分组下没有参数" :image-size="56" />
      </el-card>

      <el-empty v-if="!loading && loaded && institutionId != null && !items.length" description="该机构暂无可配置参数" :image-size="80" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  deleteOrgConfig,
  getOrgConfigs,
  putOrgConfig,
  type OrgConfigItem,
  type OrgOption,
} from '@/api/config'

const metaLoading = ref(false)
const loading = ref(false)
const loaded = ref(false)
const forbidden = ref(false)
const savingKeys = reactive<Set<string>>(new Set())
const restoringKey = ref<string | null>(null)

const institutions = ref<OrgOption[]>([])
const scopeLocked = ref(false)
const canManage = ref(false)
const institutionId = ref<number | null>(null)
const items = ref<OrgConfigItem[]>([])
// 分组名取自后端 `groups`（与「系统参数」页同源，后端唯一一处定义）；前端不维护副本，避免第二份真相。
const groups = ref<Record<string, string>>({})

/** 编辑草稿：configKey → 用户输入值（字符串）。 */
const draft = reactive<Record<string, string>>({})

const currentInstitutionName = computed(
  () => institutions.value.find((o) => o.id === institutionId.value)?.name || ''
)

/** 按 groupCode 分组展示，保持与系统参数页一致的「分组 → 卡片」结构。 */
const grouped = computed<Record<string, OrgConfigItem[]>>(() => {
  const map: Record<string, OrgConfigItem[]> = {}
  for (const c of items.value) {
    ;(map[c.groupCode] ||= []).push(c)
  }
  return map
})

function isDirty(c: OrgConfigItem): boolean {
  return draft[c.configKey] !== undefined && draft[c.configKey] !== c.effectiveValue
}

function initDraft() {
  Object.keys(draft).forEach((k) => delete draft[k])
  items.value.forEach((c) => {
    draft[c.configKey] = c.effectiveValue
  })
}

/** 拉取机构列表 + 权限态（不传 institutionId：可切换机构时返回 institutionId=null、items=[]）。 */
async function reloadMeta() {
  metaLoading.value = true
  try {
    const res = await getOrgConfigs(null)
    institutions.value = res?.institutions || []
    scopeLocked.value = !!res?.scopeLocked
    canManage.value = !!res?.canManage
    groups.value = res?.groups || {}
    forbidden.value = false
    // 机构管理员：scopeLocked 且后端已钉死 institutionId，直接加载本机构参数
    if (res?.institutionId != null) {
      institutionId.value = res.institutionId
      items.value = res.items || []
      initDraft()
      loaded.value = true
    } else {
      institutionId.value = null
      items.value = []
    }
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    forbidden.value = status === 403
    if (!forbidden.value) ElMessage.error((e as { message?: string })?.message || '加载机构列表失败')
    institutions.value = []
  } finally {
    metaLoading.value = false
  }
}

/** 选择机构后加载该机构的参数列表。 */
async function onInstitutionChange(id: number) {
  institutionId.value = id
  await reloadItems()
}

/** 拉取指定机构的参数列表（institutionId 必传）。 */
async function reloadItems() {
  if (institutionId.value == null) return
  loading.value = true
  try {
    const res = await getOrgConfigs(institutionId.value)
    items.value = res?.items || []
    if (res?.groups) groups.value = res.groups
    // 后端可能顺带回传最新 scopeLocked / canManage，保持同步
    if (typeof res?.scopeLocked === 'boolean') scopeLocked.value = res.scopeLocked
    if (typeof res?.canManage === 'boolean') canManage.value = res.canManage
    initDraft()
    loaded.value = true
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    forbidden.value = status === 403
    if (!forbidden.value) ElMessage.error((e as { message?: string })?.message || '加载参数失败')
    items.value = []
  } finally {
    loading.value = false
  }
}

/** 保存单项覆盖：成功刷新；失败保留用户输入（不重置 draft）。 */
async function saveOne(c: OrgConfigItem) {
  if (institutionId.value == null) {
    ElMessage.warning('请先选择机构')
    return
  }
  savingKeys.add(c.configKey)
  try {
    await putOrgConfig({
      institutionId: institutionId.value,
      configKey: c.configKey,
      configValue: draft[c.configKey],
    })
    ElMessage.success(`「${c.configName}」已保存，立即生效`)
    await reloadItems()
  } catch (e) {
    // 保留草稿：不调用 initDraft，用户可修改后重试
    ElMessage.error((e as { message?: string })?.message || '保存失败')
  } finally {
    savingKeys.delete(c.configKey)
  }
}

/** 恢复继承：删除本机构覆盖，回退到租户值。 */
async function restoreOne(c: OrgConfigItem) {
  if (institutionId.value == null) {
    ElMessage.warning('请先选择机构')
    return
  }
  restoringKey.value = c.configKey
  try {
    await deleteOrgConfig(institutionId.value, c.configKey)
    ElMessage.success('已恢复继承（回退到租户值）')
    await reloadItems()
  } catch (e) {
    ElMessage.error((e as { message?: string })?.message || '恢复继承失败')
  } finally {
    restoringKey.value = null
  }
}

onMounted(reloadMeta)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 6px;
}

.oc-row {
  padding: 12px 4px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.oc-row:last-child {
  border-bottom: none;
}

.oc-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.oc-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.oc-key {
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #a7b3c6;
  background: var(--el-fill-color-light);
  padding: 1px 6px;
  border-radius: 5px;
  white-space: nowrap;
}

.oc-inherit {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.oc-tenant,
.oc-effective {
  font-variant-numeric: tabular-nums;
}

.oc-control {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.oc-input--dirty :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-warning) inset;
}
.oc-dirty-hint {
  font-size: 12px;
  color: var(--el-color-warning);
}
</style>
