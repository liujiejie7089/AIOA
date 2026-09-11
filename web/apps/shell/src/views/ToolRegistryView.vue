<template>
  <div class="page">
    <div class="page-header">
      <h2>业务工具</h2>
      <p class="sub">智能体可调用的业务工具（工具权限 = 用户权限，越权数据不可达）。可在右侧直接测试执行。</p>
    </div>

    <div class="layout">
      <div class="left">
        <el-table :data="tools" v-loading="loading" stripe>
          <el-table-column label="工具" width="200">
            <template #default="{ row }">
              <b>{{ row.function?.name }}</b>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="260">
            <template #default="{ row }">{{ row.function?.description }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button size="small" @click="test(row)">测试</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="right">
        <el-card header="工具测试台">
          <el-form label-width="90px">
            <el-form-item label="工具">
              <el-select v-model="testName" placeholder="选择工具">
                <el-option v-for="t in tools" :key="t.function?.name" :label="t.function?.name" :value="t.function?.name" />
              </el-select>
            </el-form-item>
            <el-form-item label="入参 JSON">
              <el-input v-model="testArgs" type="textarea" :rows="6" placeholder='{"sql": "SELECT ..."}' />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="running" @click="run">执行</el-button>
            </el-form-item>
          </el-form>
          <div v-if="result !== null" class="result">
            <div class="result-head" :class="{ ok: resultOk }">
              {{ resultOk ? '执行成功' : '执行失败' }}
            </div>
            <pre>{{ resultText }}</pre>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listTools, invokeTool, type ToolDef } from '@/api/resource'

const loading = ref(false)
const running = ref(false)
const tools = ref<ToolDef[]>([])
const testName = ref('')
const testArgs = ref('{}')
const result = ref<unknown>(null)
const resultOk = ref(false)

const resultText = ref('')

async function reload() {
  loading.value = true
  try {
    tools.value = await listTools()
  } catch (e: any) {
    ElMessage.error('加载工具失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function test(row: ToolDef) {
  testName.value = row.function?.name || ''
  if (row.function?.name === 'sql_query') {
    testArgs.value = '{"sql": "SELECT category, COUNT(*) cnt, ROUND(SUM(amount),2) total FROM biz_sales_order o JOIN biz_product p ON o.product_id=p.id GROUP BY category ORDER BY total DESC LIMIT 5"}'
  } else if (row.function?.name === 'search_kb_documents') {
    testArgs.value = '{"keyword": "考勤"}'
  } else {
    testArgs.value = '{}'
  }
  result.value = null
}

async function run() {
  running.value = true
  result.value = null
  try {
    let args: Record<string, unknown> = {}
    try {
      args = JSON.parse(testArgs.value || '{}')
    } catch {
      ElMessage.error('入参不是合法 JSON')
      running.value = false
      return
    }
    const r = await invokeTool(testName.value, args)
    resultOk.value = !!r.ok
    result.value = r
    resultText.value = JSON.stringify(r.ok ? r.data : r.error, null, 2)
  } catch (e: any) {
    resultOk.value = false
    resultText.value = e?.message || String(e)
  } finally {
    running.value = false
  }
}

onMounted(reload)
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
.layout {
  display: grid;
  grid-template-columns: 1fr 420px;
  gap: 16px;
}
.result {
  margin-top: 12px;
}
.result-head {
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--el-color-danger);
}
.result-head.ok {
  color: var(--el-color-success);
}
.result pre {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 6px;
  overflow: auto;
  max-height: 320px;
  font-size: 12px;
  margin: 0;
}
</style>
