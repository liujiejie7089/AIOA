<template>
  <div class="page">
    <div class="page-header">
      <h2>专家配置</h2>
      <p class="sub">
        配置通用专家并管理租户级开关、可见范围、知识库范围与运行参数（所有参数真实生效）。
        「默认 AI」是用户进入用户端后<strong>未选择任何功能</strong>时承接通用对话的专家；
        用户的问题一旦涉及具体业务，默认 AI 会引导其转往对应专家或创建数字员工。
      </p>
    </div>

    <div class="toolbar">
      <el-button type="primary" @click="showImport = true">
        <el-icon style="margin-right: 4px"><Download /></el-icon>从模板导入
      </el-button>
      <!-- 平台管理员专属：模板库的**产入口**。缺了它，全局模板只能由 seed 脚本写入，
           租户端的「从模板导入」面对的是一个冻结的模板库（能力事实上不可用）。 -->
      <el-button v-if="canPublishTemplate" @click="openCreate">
        <el-icon style="margin-right: 4px"><Plus /></el-icon>新建模板
      </el-button>
      <span v-else class="toolbar-hint">「新建模板」仅平台管理员可用；你可以从模板导入本租户副本后再自行调整。</span>
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
      <!-- 默认 AI：用户端「未选择任何功能」时的兜底对象。取值落 sys_config.chat.default_expert_key，
           全站只有这一个入口（系统参数页该项为只读，见 SystemConfigView.vue）。 -->
      <el-table-column label="默认 AI" width="110">
        <template #default="{ row }">
          <el-tag v-if="isDefault(row)" type="success" effect="plain" size="small">默认</el-tag>
          <el-button v-else text type="primary" size="small" @click="makeDefault(row)">设为默认</el-button>
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
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="edit(row)">配置</el-button>
          <el-button size="small" type="danger" text @click="importOne(row)">导入</el-button>
          <!-- 删除：租户副本归本租户管理员删；全局模板只有平台管理员能删。
               入口与能力同源，避免「按钮能点、点了必失败」；后端仍会再判一次。 -->
          <el-button v-if="canDelete(row)" size="small" type="danger" text @click="remove(row)">
            删除
          </el-button>
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

    <!-- 新建 / 更新全局模板：平台管理员的模板库产入口（后端 POST /expert-config/templates） -->
    <el-dialog v-model="showCreate" title="新建 / 更新全局模板" width="720px">
      <el-form label-width="110px">
        <el-form-item label="模板标识" required>
          <el-input v-model="tpl.key" placeholder="小写字母开头 2–32 位 a-z0-9_，如 legal / data_analyst" />
          <div class="tpl-tip">
            同一标识重复保存 = <b>更新</b>该模板（不会新建第二份）；标识也用于用户端深链
            <code>?expert=&lt;key&gt;</code>，创建后不建议再改。
          </div>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="tpl.name" placeholder="如：财税专家" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="tpl.icon" placeholder="一个 emoji，如 🧾" style="width: 140px" />
        </el-form-item>
        <el-form-item label="领域分类">
          <el-select v-model="tpl.category" style="width: 200px">
            <el-option v-for="c in EXPERT_CATEGORIES" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板版本">
          <el-input v-model="tpl.templateVersion" placeholder="1.0" style="width: 140px" />
        </el-form-item>
        <el-form-item label="一句话简介">
          <el-input v-model="tpl.summary" maxlength="60" show-word-limit placeholder="列表副标题" />
        </el-form-item>
        <el-form-item label="详细介绍">
          <el-input v-model="tpl.intro" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="tpl.tagsText" placeholder="逗号分隔，如 财税,申报,合规" />
        </el-form-item>
        <el-form-item label="推荐问题">
          <el-input
            v-model="tpl.recsText"
            type="textarea"
            :rows="3"
            placeholder="每行一条；展示在用户端该专家的推荐问法"
          />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="tpl.enabled" />
          <div class="tpl-tip">
            关闭则模板创建后<b>用户端看不到</b>；之后可在列表的「开关」列随时开启。
            （两处写的是同一层配置，口径同源。）
          </div>
        </el-form-item>

        <el-divider content-position="left">运行参数（写入 GLOBAL 层配置片段，租户导入副本后按继承生效）</el-divider>

        <el-form-item label="模型">
          <el-input v-model="tpl.model" placeholder="mock-default" />
        </el-form-item>
        <el-form-item label="温度">
          <el-slider v-model="tpl.temperature" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="召回条数">
          <el-input-number v-model="tpl.topK" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="相似度阈值">
          <el-slider v-model="tpl.threshold" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="检索模式">
          <el-radio-group v-model="tpl.retrievalMode">
            <el-radio-button value="hybrid">混合</el-radio-button>
            <el-radio-button value="vector">向量</el-radio-button>
            <el-radio-button value="bm25">关键词</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="tpl.systemPrompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="知识范围">
          <el-input v-model="tpl.knowledgeScope" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="savingTpl" @click="submitCreate">保存模板</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createTemplate,
  deleteExpert,
  EXPERT_CATEGORIES,
  importTemplate,
  listExperts,
  listTemplates,
  saveExpertConfig,
  type ExpertView
} from '@/api/expert'
import { listConfigs, updateConfig } from '@/api/resource'
import { useAuthStore } from '@/stores/auth'

/** 默认 AI 的参数键（与后端 SysConfig.KEY_DEFAULT_EXPERT、迁移 V62 同源） */
const DEFAULT_AI_KEY = 'chat.default_expert_key'

const loading = ref(false)
const saving = ref(false)
const experts = ref<ExpertView[]>([])
const templates = ref<ExpertView[]>([])
const drawer = ref(false)
const showImport = ref(false)
const current = ref<ExpertView | null>(null)
/** 当前生效的默认 AI（expert_key）；空串=未配置兜底 */
const defaultKey = ref('')

const form = reactive<Record<string, any>>({})

// ---------------------------------------------------------------- 全局模板产入口
const auth = useAuthStore()
/** 只有平台管理员能写全局模板（后端 PermissionCatalog.isPlatformAdmin 把关）。
 *  入口与能力同源，避免「按钮能点、点了必 403」。
 *  注：`isPlatformAdmin` 是 store 的 getter，这里用 computed 取值而非快照，
 *  因为用户信息是登录后异步写入 store 的。 */
const canPublishTemplate = computed(() => auth.isPlatformAdmin)

const showCreate = ref(false)
const savingTpl = ref(false)

/** 「新建 / 更新全局模板」表单。tags / recs 用文本录入，提交时按逗号或换行切分。 */
const TPL_DEFAULT = {
  key: '',
  name: '',
  icon: '🧠',
  category: 'GENERAL',
  templateVersion: '1.0',
  summary: '',
  intro: '',
  tagsText: '',
  recsText: '',
  /** 新建即上架？关闭则用户端看不到，之后可在列表的「开关」列随时开启。 */
  enabled: true,
  model: 'mock-default',
  temperature: 0.3,
  topK: 5,
  threshold: 0.35,
  retrievalMode: 'hybrid',
  systemPrompt: '',
  knowledgeScope: ''
}
const tpl = reactive({ ...TPL_DEFAULT })

/** 文本 → 列表：中英文逗号 / 换行都可作分隔，空项丢弃。 */
function splitList(text: string): string[] {
  return text
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function reload() {
  loading.value = true
  try {
    experts.value = await listExperts()
  } catch (e: any) {
    ElMessage.error('加载专家失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
  // 默认 AI 是参数而非专家字段，单独取；失败只影响「默认」标记，不阻塞专家列表
  try {
    const cfg = await listConfigs({ q: DEFAULT_AI_KEY })
    defaultKey.value = cfg.items.find((i) => i.configKey === DEFAULT_AI_KEY)?.configValue || ''
  } catch {
    defaultKey.value = ''
  }
}

function isDefault(row: ExpertView): boolean {
  return !!row.expertKey && row.expertKey === defaultKey.value
}

async function makeDefault(row: ExpertView) {
  if (!row.expertKey) return
  try {
    await updateConfig(DEFAULT_AI_KEY, row.expertKey)
    ElMessage.success(`默认 AI 已切换为「${row.name}」`)
    await reload()
  } catch (e: any) {
    ElMessage.error('切换默认 AI 失败：' + (e?.message || e))
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

/**
 * 该行能否删除。
 *
 * 口径与后端同源：后端按「调用者 tenantId 名下那一行」定位 ——
 * 租户 / 企业管理员删本租户副本，平台管理员删全局模板。因此：
 * - 租户副本（isTenantCopy）⇒ 本租户管理员可删；
 * - 全局模板 ⇒ 只有平台管理员可删（租户管理员删的是自己那份副本，不是模板）。
 */
function canDelete(row: ExpertView): boolean {
  return !!row.isTenantCopy || canPublishTemplate.value
}

/**
 * 删除专家（二次确认 + 级联清理）。
 *
 * 后端的两类拒绝在界面上要区别对待：默认 AI 不可删是**硬拒绝**（直接提示去改默认 AI）；
 * 全局模板已被租户导入是可 force 的**软拒绝**（code=409），此处升级为第二次确认后再重试 ——
 * 常规删除不被多余警告打扰，而影响面大的操作必须让人明确点头。
 */
async function remove(row: ExpertView) {
  if (!row.expertKey) return
  try {
    await ElMessageBox.confirm(
      `确定删除专家「${row.name}」？其配置片段与挂靠技能会被一并清理，且不可恢复。`,
      '删除专家',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }

  try {
    const r = await deleteExpert(row.expertKey)
    ElMessage.success(r.hint || `已删除「${row.name}」`)
    await reload()
  } catch (e: any) {
    if (e?.code === 409) {
      // 软拒绝：模板已被若干租户导入。展示后端给的原文（含副本数量）后要求再次确认。
      try {
        await ElMessageBox.confirm(e.message || '该模板已被租户导入', '该模板已被租户导入', {
          type: 'warning',
          confirmButtonText: '仍然删除',
          cancelButtonText: '取消'
        })
      } catch {
        return
      }
      try {
        const r = await deleteExpert(row.expertKey, true)
        ElMessage.success(r.hint || `已删除「${row.name}」`)
        await reload()
      } catch (e2: any) {
        ElMessage.error('删除失败：' + (e2?.message || e2))
      }
      return
    }
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

/** 打开「新建模板」表单（每次清空，避免上一次的残留被误当成本次输入）。 */
function openCreate() {
  Object.assign(tpl, TPL_DEFAULT)
  showCreate.value = true
}

/**
 * 保存全局模板。
 *
 * key 与 name 在前端先做一次必填校验只是为了少一次往返；**权威校验在后端**
 * （key 的格式、`*` 保留字、平台管理员身份），错误信息由后端返回并原样展示。
 */
async function submitCreate() {
  const key = tpl.key.trim().toLowerCase()
  const name = tpl.name.trim()
  if (!key || !name) {
    ElMessage.warning('「模板标识」与「名称」必填')
    return
  }
  savingTpl.value = true
  try {
    const r = await createTemplate({
      key,
      name,
      icon: tpl.icon.trim() || '🧠',
      summary: tpl.summary.trim(),
      intro: tpl.intro.trim(),
      tags: splitList(tpl.tagsText),
      recs: splitList(tpl.recsText),
      category: tpl.category,
      templateVersion: tpl.templateVersion.trim() || '1.0',
      visibleScope: 'ALL',
      kbScope: 'ALL',
      config: {
        // 唯一意图来源：此值同时决定 GLOBAL 层配置片段与 ai_expert.enabled，
        // 后端 saveTemplate 据此落库（此前硬编码 true ⇒ 建不出「未启用」的专家）。
        enabled: tpl.enabled,
        model: tpl.model,
        temperature: tpl.temperature,
        topK: tpl.topK,
        threshold: tpl.threshold,
        retrievalMode: tpl.retrievalMode,
        systemPrompt: tpl.systemPrompt,
        knowledgeScope: tpl.knowledgeScope
      }
    })
    ElMessage.success(r.hint || (r.created ? '模板已创建' : '模板已更新'))
    showCreate.value = false
    await loadTemplates()
    await reload()
  } catch (e: any) {
    ElMessage.error('保存模板失败：' + (e?.message || e))
  } finally {
    savingTpl.value = false
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
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tpl-tip {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.tool-toggles {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
