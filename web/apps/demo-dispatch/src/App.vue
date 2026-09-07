<template>
  <div class="legacy">
    <div class="legacy-head">
      <h1>统一调度系统</h1>
      <span class="legacy-ver">v2.3.1（遗留系统 · 以 iframe 方式接入）</span>
    </div>

    <div class="legacy-bar">
      <span class="legacy-bar-title">调度任务列表</span>
      <button class="btn" type="button" @click="openDialog">新建任务</button>
    </div>

    <table class="grid">
      <thead>
        <tr>
          <th style="width: 130px">任务号</th>
          <th>任务名称</th>
          <th style="width: 130px">线路</th>
          <th style="width: 90px">状态</th>
          <th style="width: 160px">计划时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.id">
          <td>{{ task.id }}</td>
          <td>{{ task.name }}</td>
          <td>{{ task.line }}</td>
          <td>{{ task.status }}</td>
          <td>{{ task.plannedAt }}</td>
        </tr>
      </tbody>
    </table>

    <p class="legacy-note">
      本系统为遗留应用，未接入 @aioa/sdk，因此不会向工作台上报页面上下文（AI 助手上下文栏将显示「未在子应用中」）。
    </p>

    <div v-if="dialogVisible" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <div class="modal-title">新建调度任务</div>
        <form class="form" @submit.prevent="onSubmit">
          <label>
            任务名称
            <input v-model="form.name" type="text" placeholder="如：夜间巡检派车" />
          </label>
          <label>
            所属线路
            <select v-model="form.line">
              <option v-for="line in lines" :key="line" :value="line">{{ line }}</option>
            </select>
          </label>
          <label>
            计划时间
            <input v-model="form.plannedAt" type="text" placeholder="2026-09-10 08:00" />
          </label>
          <div class="form-actions">
            <button class="btn" type="submit">确定</button>
            <button class="btn btn-plain" type="button" @click="closeDialog">取消</button>
          </div>
        </form>
        <p class="modal-tip">表单为演示用途，不会真正提交。</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'

interface DispatchTask {
  id: string
  name: string
  line: string
  status: string
  plannedAt: string
}

const lines = ['1 号线', '2 号线', '3 号线', '环线']

const tasks = ref<DispatchTask[]>([
  { id: 'DS-1001', name: '早班运力补充', line: '1 号线', status: '待执行', plannedAt: '2026-09-08 06:30' },
  { id: 'DS-1002', name: '夜间巡检派车', line: '2 号线', status: '执行中', plannedAt: '2026-09-07 22:00' },
  { id: 'DS-1003', name: '节假日加班排班', line: '3 号线', status: '待审批', plannedAt: '2026-09-10 08:00' },
  { id: 'DS-1004', name: '车辆二级保养', line: '环线', status: '已完成', plannedAt: '2026-09-05 09:00' },
  { id: 'DS-1005', name: '应急物资转运', line: '1 号线', status: '已取消', plannedAt: '2026-09-06 14:00' }
])

const dialogVisible = ref(false)
const form = reactive({ name: '', line: lines[0], plannedAt: '' })

function openDialog() {
  form.name = ''
  form.plannedAt = ''
  dialogVisible.value = true
}

function closeDialog() {
  dialogVisible.value = false
}

function onSubmit() {
  // 演示用，不做真正提交
  console.log('[dispatch] 新建任务表单（未提交）', { ...form })
  closeDialog()
}
</script>

<style scoped>
.legacy {
  padding: 16px;
  background: #f2f2f2;
  min-height: 100%;
  font-family: Tahoma, 'Microsoft YaHei', SimSun, sans-serif;
  color: #333;
}

.legacy-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  border-bottom: 2px solid #7a7a7a;
  padding-bottom: 6px;
  margin-bottom: 12px;
}

.legacy-head h1 {
  font-size: 18px;
  margin: 0;
  color: #1a3a6b;
}

.legacy-ver {
  font-size: 12px;
  color: #888;
}

.legacy-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #dfe6ee;
  border: 1px solid #9aa8b8;
  padding: 6px 10px;
}

.legacy-bar-title {
  font-weight: bold;
}

.grid {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  font-size: 13px;
}

.grid th,
.grid td {
  border: 1px solid #9aa8b8;
  padding: 6px 8px;
  text-align: left;
}

.grid thead th {
  background: #e8eef5;
}

.grid tbody tr:nth-child(even) {
  background: #fafafa;
}

.legacy-note {
  margin-top: 12px;
  font-size: 12px;
  color: #666;
}

.btn {
  padding: 4px 14px;
  border: 1px solid #4a6fa5;
  background: #5b83bd;
  color: #fff;
  cursor: pointer;
  font-size: 13px;
}

.btn:hover {
  background: #4a6fa5;
}

.btn-plain {
  background: #f5f5f5;
  color: #333;
  border-color: #999;
}

.btn-plain:hover {
  background: #e8e8e8;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal {
  width: 360px;
  background: #fff;
  border: 1px solid #7a7a7a;
  padding: 12px 14px 10px;
}

.modal-title {
  font-weight: bold;
  border-bottom: 1px solid #ccc;
  padding-bottom: 6px;
  margin-bottom: 10px;
}

.form label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
}

.form input,
.form select {
  display: block;
  width: 100%;
  margin-top: 3px;
  padding: 4px 6px;
  border: 1px solid #9aa8b8;
  font-size: 13px;
}

.form-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 6px;
}

.modal-tip {
  margin: 8px 0 0;
  font-size: 12px;
  color: #999;
}
</style>
