<template>
  <div class="page">
    <div class="page-header">
      <h2>专家配置</h2>
      <p class="sub">配置通用专家并管理租户级开关、可见范围、知识库范围与运行参数（所有参数真实生效）。</p>
    </div>

    <div class="toolbar">
      <el-button type="primary" @click="showImport = true">
        <el-icon style="margin-right: 4px"><Download /></el-icon>从模板导入
      </el-button>
    </div>

    <el-table :data="experts" v-loading="loading" stripe>
      <el-table-column prop="name" label="专家" min-width="160">
        <template #default="{ row }">
          <span style="font-size: 18px; margin-right: 6px">{{ row.icon }}</span>
          <b>{{ row.name }}</b>
          <el-tag v-if="row.isTenantCopy" size="small" type="warning" style="margin-left: 6px">租户副本</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="领域" width="110" />
      <el-table-column prop="summary" label="简介" min-width="200" show-overflow-tooltip />
      <el-table-column label="开关" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="(v: boolean) => toggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="温度" width="80">
        <template #default="{ row }">{{ row.temperature }}</template>
      </el-table-column>
      <el-table-column label="召回" width="80">
        <template #default="{ row }">{{ row.topK }}</template>
      </el-table-column>
      <el-table-column label="检索模式" width="100">
        <template #default="{ row }">{{ row.retrievalMode }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="edit(row)">配置</el-button>
          <el-button size="small" type="danger" text @click="importOne(row)">导入</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 配置抽屉 -->
    <el-drawer v-model="drawer" :title="`配置 · ${current?.name || ''}`" size="520px">
      <el-form label-width="110px" v-if="current">
        <el-form-item label="专家开关">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="可见范围">
          <el-select v-model="form.visibleScope">
            <el-option label="全员可见" value="ALL" />
            <el-option label="仅本租户" value="TENANT" />
            <el-option label="指定机构" value="INSTITUTION" />
            <el-option label="指定部门" value="DEPT" />
            <el-option label="指定用户" value="USER" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认启用">
          <el-switch v-model="form.defaultEnabled" />
        </el-form-item>
        <el-form-item label="知识库范围">
          <el-input v-model="form.kbScope" placeholder="ALL 或逗号分隔文档ID（如 12,13）" />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="form.model" placeholder="mock-default" />
        </el-form-item>
        <el-form-item label="温度">
          <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="召回条数">
          <el-input-number v-model="form.topK" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="相似度阈值">
          <el-slider v-model="form.threshold" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="检索模式">
          <el-radio-group v-model="form.retrievalMode">
            <el-radio-button value="hybrid">混合</el-radio-button>
            <el-radio-button value="vector">向量</el-radio-button>
            <el-radio-button value="bm25">关键词</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="工具开关">
          <div class="tool-toggles">
            <el-checkbox v-model="form.tools.sql_query">sql_query（数据分析）</el-checkbox>
            <el-checkbox v-model="form.tools.python_script">python_script（脚本计算）</el-checkbox>
            <el-checkbox v-model="form.tools.kb_search">kb_search（知识库检索）</el-checkbox>
          </div>
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="form.systemPrompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="知识范围">
          <el-input v-model="form.knowledgeScope" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawer = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-drawer>

    <!-- 模板导入 -->
    <el-dialog v-model="showImport" title="从全局模板导入" width="640px">
      <el-table :data="templates" max-height="400" @row-click="importOne">
        <el-table-column prop="name" label="模板" min-width="150">
          <template #default="{ row }">
            <span style="margin-right: 6px">{{ row.icon }}</span>{{ row.name }}
          </template>
        </el-table-column>
        <el-table-column prop="category" label="领域" width="120" />
        <el-table-column prop="summary" label="简介" min-width="200" show-overflow-tooltip />
        <el-table-column label="" width="80">
          <template #default>
            <el-button size="small" type="primary" text>导入</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listExperts,
  listTemplates,
  importTemplate,
  saveExpertConfig,
  type ExpertView
} from '@/api/expert'

const loading = ref(false)
const saving = ref(false)
const experts = ref<ExpertView[]>([])
const templates = ref<ExpertView[]>([])
const drawer = ref(false)
const showImport = ref(false)
const current = ref<ExpertView | null>(null)

const form = reactive<Record<string, any>>({})

async function reload() {
  loading.value = true
  try {
    experts.value = await listExperts()
  } catch (e: any) {
    ElMessage.error('加载专家失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  try {
    templates.value = await listTemplates()
  } catch (e: any) {
    ElMessage.error('加载模板失败：' + (e?.message || e))
  }
}

async function toggle(row: ExpertView, v: boolean) {
  try {
    await saveExpertConfig(row.expertKey!, 'TENANT', { enabled: v })
    ElMessage.success(`${row.name} 已${v ? '启用' : '禁用'}`)
    await reload()
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || e))
  }
}

function edit(row: ExpertView) {
  current.value = row
  Object.assign(form, {
    enabled: row.enabled,
    visibleScope: row.visibleScope || 'ALL',
    defaultEnabled: row.defaultEnabled,
    kbScope: row.kbScope || 'ALL',
    model: row.model || 'mock-default',
    temperature: row.temperature ?? 0.3,
    topK: row.topK ?? 5,
    threshold: row.threshold ?? 0.35,
    retrievalMode: row.retrievalMode || 'hybrid',
    tools: { ...(row.tools || { sql_query: false, python_script: false, kb_search: true }) },
    systemPrompt: row.systemPrompt || '',
    knowledgeScope: row.knowledgeScope || ''
  })
  drawer.value = true
}

async function save() {
  saving.value = true
  try {
    const cfg: Record<string, unknown> = {
      enabled: form.enabled,
      visibleScope: form.visibleScope,
      defaultEnabled: form.defaultEnabled,
      kbScope: form.kbScope,
      model: form.model,
      temperature: form.temperature,
      topK: form.topK,
      threshold: form.threshold,
      retrievalMode: form.retrievalMode,
      tools: form.tools,
      systemPrompt: form.systemPrompt,
      knowledgeScope: form.knowledgeScope
    }
    await saveExpertConfig(current.value!.expertKey!, 'TENANT', cfg)
    ElMessage.success('配置已保存并即时生效')
    drawer.value = false
    await reload()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || e))
  } finally {
    saving.value = false
  }
}

async function importOne(row: ExpertView) {
  try {
    const r = await importTemplate(row.expertKey!)
    ElMessage.success(r.created ? `已导入「${row.name}」` : `已更新「${row.name}」`)
    showImport.value = false
    await reload()
  } catch (e: any) {
    ElMessage.error('导入失败：' + (e?.message || e))
  }
}

onMounted(() => {
  reload()
  loadTemplates()
})
</script>

<style scoped>
.page {
  padding: 20px 24px 96px;
}
.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.sub {
  margin: 0 0 16px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.toolbar {
  margin-bottom: 14px;
}
.tool-toggles {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
