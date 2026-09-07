<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <div class="login-brand">
        <el-icon class="login-icon"><Platform /></el-icon>
        <div>
          <div class="login-title">AIOA 智能办公基座</div>
          <div class="login-sub">统一身份登录</div>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="onSubmit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="admin" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="Admin@123" autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="auth.loading" @click="onSubmit">登 录</el-button>
      </el-form>

      <div class="login-tip">演示账号：admin / Admin@123（需先启动后端 aioa-server：8080）</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const rules: FormRules<typeof form> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  try {
    await auth.login({ username: form.username, password: form.password })
    ElMessage.success(`欢迎回来，${auth.displayName}`)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/home'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  background: linear-gradient(135deg, #eaf2fe 0%, #f5f7fa 60%, #eef3ff 100%);
}

.login-card {
  width: 380px;
  padding: 8px 8px 4px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.login-icon {
  font-size: 32px;
  color: var(--aioa-primary);
}

.login-title {
  font-size: 18px;
  font-weight: 600;
}

.login-sub {
  font-size: 12px;
  color: var(--aioa-text-sub);
}

.login-btn {
  width: 100%;
}

.login-tip {
  margin-top: 12px;
  font-size: 12px;
  color: var(--aioa-text-sub);
  text-align: center;
}
</style>
