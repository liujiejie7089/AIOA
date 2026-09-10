<template>
  <div class="cfg-page">
    <el-alert
      v-if="forbidden"
      type="warning"
      :closable="false"
      show-icon
      title="系统参数配置仅租户管理员可访问"
      description="当前账号没有 ROLE_ADMIN 角色，如需管理权限请联系租户管理员。"
    />

    <template v-else>
      <div class="cfg-hero">
        <div class="cfg-hero-main">
          <div class="cfg-hero-title">
            <el-icon><Setting /></el-icon>
            <span>系统参数配置</span>
          </div>
          <p class="cfg-hero-desc">
            运行期可调参数，保存后立即生效，无需重启服务。所有变更均写入操作审计留痕。
          </p>
        </div>
        <div class="cfg-hero-stats">
          <div class="cfg-stat">
            <span class="cfg-stat-num">{{ total }}</span>
            <span class="cfg-stat-label">参数项</span>
          </div>
          <div class="cfg-stat">
            <span class="cfg-stat-num cfg-stat-num--warn">{{ dirtyCount }}</span>
            <span class="cfg-stat-label">待保存</span>
          </div>
        </div>
      </div>

      <div class="cfg-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索参数键 / 名称 / 说明"
          clearable
          class="cfg-search"
          @keyup.enter="load"
          @clear="load"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="groupFilter" placeholder="全部分组" clearable class="cfg-group-select" @change="load">
          <el-option v-for="(name, code) in groups" :key="code" :label="name" :value="code" />
        </el-select>
        <div class="cfg-toolbar-right">
          <el-button :loading="loading" @click="load">
            <el-icon><Refresh /></el-icon><span style="margin-left: 4px">刷新</span>
          </el-button>
          <el-button type="primary" :loading="saving" :disabled="!dirtyCount" @click="saveAll">
            保存全部修改<template v-if="dirtyCount">（{{ dirtyCount }}）</template>
          </el-button>
          <el-button type="warning" plain @click="doResetAll">全部恢复默认</el-button>
        </div>
      </div>

      <el-empty v-if="!loading && !items.length" description="没有匹配的参数" :image-size="90" />

      <div v-for="(list, code) in grouped" :key="code" class="cfg-group">
        <div class="cfg-group-head">
          <span class="cfg-group-dot" :class="`cfg-group-dot--${String(code).toLowerCase()}`"></span>
          <span class="cfg-group-name">{{ groups[code] || code }}</span>
          <span class="cfg-group-count">{{ list.length }} 项</span>
        </div>

        <div class="cfg-grid">
          <div
            v-for="c in list"
            :key="c.configKey"
            class="cfg-card"
            :class="{ 'cfg-card--dirty': isDirty(c) }"
          >
            <div class="cfg-card-head">
              <span class="cfg-card-name">
                {{ c.configName }}
                <el-tag v-if="isDirty(c)" type="warning" size="small" effect="light" round>未保存</el-tag>
              </span>
              <el-tooltip :content="c.configKey" placement="top">
                <span class="cfg-card-key">{{ c.configKey }}</span>
              </el-tooltip>
            </div>

            <p class="cfg-card-desc">{{ c.description }}</p>

            <div class="cfg-card-control">
              <!-- 布尔：开关 -->
              <el-switch
                v-if="c.valueType === 'BOOL'"
                :model-value="draft[c.configKey] === 'true'"
                :disabled="!c.editable"
                active-text="开启"
                inactive-text="关闭"
                inline-prompt
                @update:model-value="(v: any) => (draft[c.configKey] = v ? 'true' : 'false')"
              />
              <!-- 枚举：默认模型路由 -->
              <el-select
                v-else-if="c.configKey === 'chat.default_model_route'"
                v-model="draft[c.configKey]"
                :disabled="!c.editable"
                size="default"
                style="width: 100%"
                filterable
                allow-create
                default-first-option
              >
                <el-option label="auto（平台智能路由）" value="auto" />
                <el-option v-for="m in models" :key="m.providerKey" :label="`${m.name}（${m.providerKey}）`" :value="m.providerKey" />
              </el-select>
              <!-- 数值 / 文本 -->
              <el-input
                v-else
                v-model="draft[c.configKey]"
                :disabled="!c.editable"
                :type="c.valueType === 'INT' || c.valueType === 'DECIMAL' ? 'number' : 'text'"
              >
                <template v-if="c.unit" #append>{{ c.unit }}</template>
              </el-input>
            </div>

            <div class="cfg-card-foot">
              <span class="cfg-card-range">
                <template v-if="c.minValue !== null || c.maxValue !== null">
                  取值 {{ c.minValue ?? '—' }} ~ {{ c.maxValue ?? '—' }}{{ c.unit || '' }}
                </template>
                <template v-else-if="c.valueType === 'BOOL'">布尔开关</template>
                <template v-else>自由文本（≤500 字符）</template>
              </span>
              <span class="cfg-card-actions">
                <span class="cfg-card-default">默认：{{ c.defaultValue }}</span>
                <el-button
                  link
                  type="warning"
                  size="small"
                  :disabled="!c.editable || c.configValue === c.defaultValue"
                  @click="doResetOne(c)"
                >
                  恢复默认
                </el-button>
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listConfigs,
  listModels,
  resetAllConfigs,
  resetConfig,
  updateConfig,
  type ModelItem,
  type SysConfigItem,
} from '@/api/resource'

const loading = ref(false)
const saving = ref(false)
const forbidden = ref(false)
const keyword = ref('')
const groupFilter = ref('')

const groups = ref<Record<string, string>>({})
const grouped = ref<Record<string, SysConfigItem[]>>({})
const items = ref<SysConfigItem[]>([])
const total = ref(0)
const models = ref<ModelItem[]>([])

/** 编辑草稿：key → value（字符串） */
const draft = reactive<Record<string, string>>({})

const dirtyCount = computed(() => items.value.filter((c) => isDirty(c)).length)

function isDirty(c: SysConfigItem) {
  return draft[c.configKey] !== undefined && draft[c.configKey] !== c.configValue
}

async function load() {
  loading.value = true
  try {
    const res = await listConfigs({ q: keyword.value || undefined, group: groupFilter.value || undefined })
    groups.value = res?.groups || {}
    grouped.value = res?.grouped || {}
    items.value = res?.items || []
    total.value = Number(res?.total || 0)
    forbidden.value = false
    // 重置草稿为服务端当前值
    Object.keys(draft).forEach((k) => delete draft[k])
    items.value.forEach((c) => {
      draft[c.configKey] = c.configValue
    })
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    forbidden.value = status === 403
    if (!forbidden.value) ElMessage.error((e as { message?: string })?.message || '加载失败')
    grouped.value = {}
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function saveAll() {
  const changed = items.value.filter((c) => isDirty(c))
  if (!changed.length) {
    ElMessage.info('没有需要保存的修改')
    return
  }
  saving.value = true
  try {
    // 逐项保存，便于精确定位失败项
    const failed: string[] = []
    for (const c of changed) {
      try {
        const updated = await updateConfig(c.configKey, draft[c.configKey])
        Object.assign(c, updated)
      } catch (e) {
        failed.push(`${c.configName}：${(e as { message?: string })?.message || '保存失败'}`)
      }
    }
    if (failed.length) {
      ElMessage.warning(`部分保存失败 → ${failed.join('；')}`)
    } else {
      ElMessage.success(`已保存 ${changed.length} 项参数，立即生效`)
    }
    await load()
  } finally {
    saving.value = false
  }
}

async function doResetOne(c: SysConfigItem) {
  try {
    await ElMessageBox.confirm(
      `确认将「${c.configName}」恢复为默认值 ${c.defaultValue}${c.unit || ''}？`,
      '恢复默认',
      { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' }
    )
    const updated = await resetConfig(c.configKey)
    Object.assign(c, updated)
    draft[c.configKey] = updated.configValue
    ElMessage.success(`「${c.configName}」已恢复默认`)
  } catch (e) {
    if ((e as string) !== 'cancel') ElMessage.error((e as { message?: string })?.message || '恢复失败')
  }
}

async function doResetAll() {
  try {
    await ElMessageBox.confirm('确认将全部参数恢复为出厂默认？该操作会写入审计留痕。', '全部恢复默认', {
      type: 'warning',
      confirmButtonText: '全部恢复',
      cancelButtonText: '取消',
    })
    const res = await resetAllConfigs()
    ElMessage.success(`已恢复 ${res?.reseted ?? 0} 项参数默认值`)
    await load()
  } catch (e) {
    if ((e as string) !== 'cancel') ElMessage.error((e as { message?: string })?.message || '操作失败')
  }
}

onMounted(async () => {
  await load()
  try {
    models.value = (await listModels()) || []
  } catch {
    models.value = []
  }
})
</script>

<style scoped>
.cfg-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ---------- 页头 ---------- */
.cfg-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
  border-radius: 14px;
  background: linear-gradient(120deg, #eef4ff 0%, #f6f9ff 45%, #f3fbf7 100%);
  border: 1px solid #e3ecfb;
}
.cfg-hero-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 650;
  color: #2b3a55;
}
.cfg-hero-title .el-icon {
  color: #5b8def;
  font-size: 20px;
}
.cfg-hero-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: #7b8aa3;
  line-height: 1.6;
}
.cfg-hero-stats {
  display: flex;
  gap: 12px;
}
.cfg-stat {
  min-width: 84px;
  padding: 10px 14px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e8eef8;
  text-align: center;
  box-shadow: 0 1px 3px rgba(91, 141, 239, 0.06);
}
.cfg-stat-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: #3b6fe0;
  line-height: 1.2;
}
.cfg-stat-num--warn {
  color: #e6a23c;
}
.cfg-stat-label {
  font-size: 12px;
  color: #8c9bb3;
}

/* ---------- 工具栏 ---------- */
.cfg-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #eaeff7;
}
.cfg-search {
  width: 280px;
}
.cfg-group-select {
  width: 160px;
}
.cfg-toolbar-right {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

/* ---------- 分组 ---------- */
.cfg-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cfg-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 2px;
}
.cfg-group-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #5b8def;
}
.cfg-group-dot--conversation { background: #5b8def; }
.cfg-group-dot--quota { background: #f0a020; }
.cfg-group-dot--knowledge { background: #37b98a; }
.cfg-group-dot--security { background: #e56b8c; }
.cfg-group-dot--common { background: #9aa7bd; }
.cfg-group-name {
  font-size: 15px;
  font-weight: 650;
  color: #2b3a55;
}
.cfg-group-count {
  font-size: 12px;
  color: #96a3b8;
}

/* ---------- 参数卡片 ---------- */
.cfg-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 12px;
}
.cfg-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #eaeff7;
  transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s;
}
.cfg-card:hover {
  border-color: #cfdff8;
  box-shadow: 0 4px 14px rgba(91, 141, 239, 0.09);
}
.cfg-card--dirty {
  border-color: #f5d99a;
  background: #fffdf6;
}
.cfg-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.cfg-card-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #2b3a55;
}
.cfg-card-key {
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #a7b3c6;
  background: #f5f7fb;
  padding: 1px 6px;
  border-radius: 5px;
  white-space: nowrap;
}
.cfg-card-desc {
  margin: 0;
  font-size: 12px;
  color: #8b98ad;
  line-height: 1.6;
  min-height: 32px;
}
.cfg-card-control {
  display: flex;
  align-items: center;
}
.cfg-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px dashed #eef2f8;
}
.cfg-card-range {
  font-size: 11px;
  color: #9aa7bd;
}
.cfg-card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cfg-card-default {
  font-size: 11px;
  color: #b0bccd;
}

@media (max-width: 720px) {
  .cfg-hero {
    flex-direction: column;
    align-items: flex-start;
  }
  .cfg-toolbar {
    flex-wrap: wrap;
  }
  .cfg-search,
  .cfg-group-select {
    width: 100%;
  }
  .cfg-toolbar-right {
    margin-left: 0;
    width: 100%;
  }
}
</style>
