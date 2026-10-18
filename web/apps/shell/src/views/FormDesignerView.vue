<template>
  <div class="form-designer">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="管理端表单设计器（最小可用）"
      description="配置每个功能的自定义表单：字段增删、类型、必填、选项与预览。保存时后端按「控件类型 + 必填 + 选项」自动生成标准 JSON Schema，并更新版本（编辑已有表单会自动升版）。导入/导出采用 { code, name, fields:[{name,label,type,required,options:[{value,label}]}] } 结构。"
      style="margin-bottom: 12px"
    />

    <el-row :gutter="12">
      <!-- 左：表单列表 -->
      <el-col :span="8">
        <el-card shadow="never" class="list-card">
          <template #header>
            <div class="card-header">
              <span>表单列表（共 {{ forms.length }} 条）</span>
              <el-button text type="primary" size="small" :loading="loading" @click="loadForms">刷新</el-button>
            </div>
            <div class="filter-row">
              <el-input
                v-model="filterModule"
                size="small"
                clearable
                placeholder="按模块码筛选（如 leave）"
                @keyup.enter="loadForms"
                @clear="loadForms"
              />
              <el-button size="small" @click="loadForms">筛选</el-button>
            </div>
          </template>

          <el-table
            v-loading="loading"
            :data="forms"
            stripe
            height="520"
            highlight-current-row
            :row-class-name="rowClass"
            @row-click="onSelect"
          >
            <el-table-column prop="code" label="表单码" min-width="150" show-overflow-tooltip />
            <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
            <el-table-column label="版本" width="70">
              <template #default="{ row }">v{{ row.version ?? '?' }}</template>
            </el-table-column>
            <el-table-column prop="moduleCode" label="模块" min-width="90" show-overflow-tooltip>
              <template #default="{ row }">{{ row.moduleCode || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="84">
              <template #default="{ row }">
                <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">
                  {{ row.status === 'ACTIVE' ? '启用' : (row.status || '未知') }}
                </el-tag>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无表单定义" :image-size="70" />
            </template>
          </el-table>
        </el-card>
      </el-col>

      <!-- 右：编辑区 -->
      <el-col :span="16">
        <template v-if="editing">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>{{ isNew ? '新建表单' : ('编辑：' + selectedCode) }}</span>
                <div>
                  <el-button size="small" @click="openIo">导入 / 导出 JSON</el-button>
                  <el-button size="small" @click="startNew">新建表单</el-button>
                  <el-button type="primary" size="small" :loading="saving" @click="save">保存</el-button>
                </div>
              </div>
            </template>

            <el-form :model="design" label-width="96px" class="head-form">
              <el-row :gutter="12">
                <el-col :span="12">
                  <el-form-item label="表单码" :required="isNew">
                    <el-input
                      v-model="design.code"
                      :disabled="!isNew"
                      placeholder="如 leave_request（英文键，自动作为引用码）"
                    />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="表单名称" required>
                    <el-input v-model="design.name" placeholder="如 请假申请" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="模块码">
                    <el-input v-model="design.moduleCode" placeholder="归属功能模块码，如 leave（可空）" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="业务类型">
                    <el-input v-model="design.bizType" placeholder="进审批的 bizType，如 LEAVE（可空=不走审批）" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="分流策略" required>
                    <el-select v-model="design.submitPolicy" style="width: 100%">
                      <el-option v-for="p in FORM_SUBMIT_POLICIES" :key="p.value" :label="p.label" :value="p.value" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>

            <div class="fields-toolbar">
              <span>字段定义（共 {{ design.fields.length }} 个）</span>
              <el-button size="small" type="primary" plain @click="addField">添加字段</el-button>
            </div>

            <el-table :data="design.fields" border stripe size="small">
              <el-table-column label="#" width="48">
                <template #default="{ $index }">{{ $index + 1 }}</template>
              </el-table-column>
              <el-table-column label="字段键(name)" min-width="170">
                <template #default="{ row, $index }">
                  <el-input v-model="row.name" size="small" placeholder="英文键" />
                  <div v-if="nameError(row.name, $index)" class="cell-error">{{ nameError(row.name, $index) }}</div>
                </template>
              </el-table-column>
              <el-table-column label="标签(label)" min-width="130">
                <template #default="{ row }">
                  <el-input v-model="row.label" size="small" placeholder="中文标签" />
                </template>
              </el-table-column>
              <el-table-column label="类型" width="130">
                <template #default="{ row }">
                  <el-select v-model="row.type" size="small" style="width: 100%">
                    <el-option v-for="t in FORM_FIELD_TYPES" :key="t.value" :label="t.label" :value="t.value" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="必填" width="64" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.required" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="选项(值=标签)" min-width="200">
                <template #default="{ row }">
                  <el-input
                    v-if="FORM_OPTION_TYPES.includes(row.type)"
                    v-model="row.optionsText"
                    type="textarea"
                    :rows="2"
                    size="small"
                    placeholder="每行一条：值=标签&#10;如&#10;A=选项一&#10;B=选项二"
                  />
                  <span v-else class="text-sub">—</span>
                </template>
              </el-table-column>
              <el-table-column label="占位/说明" min-width="130">
                <template #default="{ row }">
                  <el-input v-model="row.placeholder" size="small" placeholder="选填" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120" fixed="right">
                <template #default="{ $index }">
                  <el-button text size="small" :disabled="$index === 0" @click="moveUp($index)">上移</el-button>
                  <el-button text size="small" :disabled="$index === design.fields.length - 1" @click="moveDown($index)">下移</el-button>
                  <el-button text type="danger" size="small" @click="removeField($index)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 预览 -->
          <el-card shadow="never" style="margin-top: 12px">
            <template #header>
              <span>只读预览（按当前字段渲染）</span>
            </template>
            <el-form label-width="120px" class="preview-form">
              <el-form-item v-for="f in design.fields" :key="f.name || Math.random()" :required="f.required">
                <template #label>
                  <span>{{ f.label || f.name || '未命名' }}</span>
                </template>

                <el-input
                  v-if="f.type === 'text' || f.type === 'number' || f.type === 'amount' || f.type === 'file'"
                  :model-value="''"
                  disabled
                  :placeholder="f.placeholder || (f.type === 'file' ? '上传文件（预览态不可上传）' : '请输入')"
                  style="max-width: 360px"
                />
                <el-input
                  v-else-if="f.type === 'textarea'"
                  :model-value="''"
                  disabled
                  type="textarea"
                  :rows="2"
                  :placeholder="f.placeholder || '请输入'"
                  style="max-width: 360px"
                />
                <el-date-picker
                  v-else-if="f.type === 'date'"
                  :model-value="null"
                  type="date"
                  disabled
                  placeholder="选择日期"
                  style="max-width: 360px"
                />
                <el-date-picker
                  v-else-if="f.type === 'datetime'"
                  :model-value="null"
                  type="datetime"
                  disabled
                  placeholder="选择日期时间"
                  style="max-width: 360px"
                />
                <el-select
                  v-else-if="f.type === 'select'"
                  :model-value="null"
                  disabled
                  placeholder="请选择"
                  style="max-width: 360px"
                >
                  <el-option
                    v-for="o in parseOptionEntries(f.optionsText)"
                    :key="o.value"
                    :label="o.label"
                    :value="o.value"
                  />
                </el-select>
                <el-select
                  v-else-if="f.type === 'multiselect'"
                  :model-value="[]"
                  multiple
                  disabled
                  placeholder="请选择（可多选）"
                  style="max-width: 360px"
                >
                  <el-option
                    v-for="o in parseOptionEntries(f.optionsText)"
                    :key="o.value"
                    :label="o.label"
                    :value="o.value"
                  />
                </el-select>
                <el-switch v-else-if="f.type === 'boolean'" :model-value="false" disabled />
                <span v-else class="text-sub">未知类型：{{ f.type }}</span>
              </el-form-item>
              <el-empty v-if="!design.fields.length" description="暂无字段可预览" :image-size="60" />
            </el-form>
          </el-card>
        </template>

        <el-card v-else shadow="never">
          <el-empty description="请在左侧选择表单进行编辑，或点击「新建表单」" :image-size="90">
            <el-button type="primary" @click="startNew">新建表单</el-button>
          </el-empty>
        </el-card>
      </el-col>
    </el-row>

    <!-- 导入 / 导出 JSON -->
    <el-dialog v-model="ioVisible" title="导入 / 导出 JSON" width="720px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 10px"
        title="导入会覆盖当前字段表格"
        description="结构：{ code, name, moduleCode, bizType, submitPolicy, fields:[{ name, label, type, required, placeholder, options:[{value,label}] }] }。解析失败会给出中文提示，不会白屏。"
      />
      <el-input
        v-model="ioText"
        type="textarea"
        :rows="16"
        placeholder="点击「导出当前」生成，或粘贴一段表单 JSON 后点击「导入覆盖」"
      />
      <template #footer>
        <el-button @click="doExport">导出当前</el-button>
        <el-button @click="downloadJson">下载为文件</el-button>
        <el-button type="primary" @click="doImport">导入覆盖</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listForms,
  getForm,
  createForm,
  updateForm,
  renderToFields,
  designToExportJson,
  exportJsonToDesign,
  parseOptionEntries,
  type FormDesign,
  type FormFieldDraft,
  type FormTemplate
} from '@/api/forms'
import {
  FORM_FIELD_TYPES,
  FORM_OPTION_TYPES,
  FORM_SUBMIT_POLICIES
} from '@/constants/permissions'

const NAME_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/

function emptyField(): FormFieldDraft {
  return { name: '', label: '', type: 'text', required: false, optionsText: '', placeholder: '' }
}

function emptyDesign(): FormDesign {
  return { code: '', name: '', moduleCode: '', bizType: '', submitPolicy: 'LEDGER', fields: [emptyField()] }
}

const forms = ref<FormTemplate[]>([])
const loading = ref(false)
const saving = ref(false)
const filterModule = ref('')

const editing = ref(false)
const selectedCode = ref<string | null>(null)
const design = ref<FormDesign>(emptyDesign())
const isNew = computed(() => !selectedCode.value)

async function loadForms() {
  loading.value = true
  try {
    const r = await listForms({ moduleCode: filterModule.value || undefined, page: 1, size: 200 })
    forms.value = (r && r.records) || []
  } catch (e: unknown) {
    ElMessage.error('表单列表加载失败：' + ((e as Error)?.message || '后端异常'))
    forms.value = []
  } finally {
    loading.value = false
  }
}

async function onSelect(row: FormTemplate) {
  selectedCode.value = row.code
  design.value = {
    code: row.code,
    name: row.name,
    moduleCode: row.moduleCode || '',
    bizType: row.bizType || '',
    submitPolicy: row.submitPolicy || 'LEDGER',
    fields: []
  }
  editing.value = true
  // 字段明细来自渲染接口（GET /forms/{code}），其载荷不含 bizType，故头部以列表记录为准。
  try {
    const render = await getForm(row.code)
    design.value.fields = renderToFields(render)
    if (!design.value.fields.length) design.value.fields = [emptyField()]
  } catch (e: unknown) {
    ElMessage.error('字段加载失败：' + ((e as Error)?.message || '后端异常') + '（已保留头部信息）')
    design.value.fields = [emptyField()]
  }
}

function startNew() {
  selectedCode.value = null
  design.value = emptyDesign()
  editing.value = true
}

function addField() {
  design.value.fields.push(emptyField())
}

function removeField(i: number) {
  design.value.fields.splice(i, 1)
}

function moveUp(i: number) {
  if (i <= 0) return
  const arr = design.value.fields
  ;[arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]
}

function moveDown(i: number) {
  const arr = design.value.fields
  if (i >= arr.length - 1) return
  ;[arr[i + 1], arr[i]] = [arr[i], arr[i + 1]]
}

const dupNameSet = computed(() => {
  const counts = new Map<string, number>()
  design.value.fields.forEach((f) => {
    if (f.name) counts.set(f.name, (counts.get(f.name) || 0) + 1)
  })
  const dups = new Set<string>()
  counts.forEach((c, k) => {
    if (c > 1) dups.add(k)
  })
  return dups
})

function nameError(name: string, _idx: number): string {
  if (!name) return '字段键不能为空'
  if (!NAME_RE.test(name)) return '需以字母或下划线开头，仅含字母/数字/下划线'
  if (dupNameSet.value.has(name)) return '字段键重复'
  return ''
}

function validateBeforeSave(): string {
  if (isNew.value && !NAME_RE.test(design.value.code)) {
    return '表单码(code)需以字母或下划线开头，仅含字母/数字/下划线'
  }
  if (!design.value.name.trim()) return '表单名称不能为空'
  if (!design.value.fields.length) return '至少需要一个字段'
  for (let i = 0; i < design.value.fields.length; i++) {
    const f = design.value.fields[i]
    const e = nameError(f.name, i)
    if (e) return `第 ${i + 1} 个字段：${e}`
    if (!f.label.trim()) return `第 ${i + 1} 个字段：标签不能为空`
  }
  return ''
}

async function save() {
  const err = validateBeforeSave()
  if (err) {
    ElMessage.warning(err)
    return
  }
  saving.value = true
  try {
    if (isNew.value) {
      const res = await createForm(design.value)
      selectedCode.value = res.code
      ElMessage.success('已创建表单定义：' + res.code)
    } else {
      const res = await updateForm(selectedCode.value as string, design.value)
      ElMessage.success('已保存，表单已升到 v' + (res.version ?? '?'))
    }
    await loadForms()
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    saving.value = false
  }
}

const ioVisible = ref(false)
const ioText = ref('')

function openIo() {
  ioText.value = designToExportJson(design.value)
  ioVisible.value = true
}

function doExport() {
  ioText.value = designToExportJson(design.value)
  ElMessage.success('已生成当前表单的 JSON')
}

function downloadJson() {
  const text = ioText.value || designToExportJson(design.value)
  const blob = new Blob([text], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = (design.value.code || 'form-design') + '.json'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function doImport() {
  try {
    const d = exportJsonToDesign(ioText.value)
    if (selectedCode.value) {
      // 编辑态：code 以当前选中为准，避免误改 PUT 目标
      d.code = selectedCode.value
    }
    design.value = d
    ElMessage.success('导入成功，已覆盖字段表格')
    ioVisible.value = false
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '导入失败')
  }
}

function rowClass({ row }: { row: FormTemplate }): string {
  return row.code === selectedCode.value ? 'selected-row' : ''
}

onMounted(loadForms)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.filter-row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.list-card :deep(.selected-row) {
  background: var(--el-color-primary-light-9);
}

.text-sub {
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.fields-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 14px 0 8px;
}

.cell-error {
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.4;
  margin-top: 2px;
}

.preview-form {
  max-width: 560px;
}
</style>
