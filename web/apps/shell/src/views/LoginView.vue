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
        <el-form-item label="租户 / 机构名称" prop="tenantName">
          <el-input
            v-model="form.tenantName"
            placeholder="某某智能科技有限公司，或某某智能科技有限公司研发中心"
            autocomplete="organization"
          />
          <div class="field-tip">
            填所属<strong>租户全称</strong>即可；填<strong>租户编码</strong>或你所在的<strong>机构名称</strong>也可以。
            名称可以省略前面的「某某市某某区」等前缀，例如只填「大数据管理局」。平台管理员填「默认租户」。
          </div>
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="admin" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="Admin@123" autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="auth.loading" @click="onSubmit">登 录</el-button>
      </el-form>

      <div class="login-tip">
        演示账号（密码见括号）：<br />
        平台管理员 admin（Admin@123），租户名称填「默认租户」<br />
        租户管理员 znkj_admin（User@123），租户名称填「某某智能科技有限公司」<br />
        机构管理员 znkjyf_admin（User@123），租户名称填「研发中心」即可
      </div>
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
/** 上次登录成功的租户名称：同一个租户反复登录时不用每次重敲。 */
const LAST_TENANT_KEY = 'aioa.lastTenant'
const form = reactive({
  username: '',
  password: '',
  tenantName: localStorage.getItem(LAST_TENANT_KEY) || ''
})

const rules: FormRules<typeof form> = {
  tenantName: [
    { required: true, message: '请输入租户名称', trigger: 'blur' },
    {
      // Element Plus 的 required 把「   」当非空，这里补一条纯空白拦截
      validator: (_rule, value: string, callback) => {
        if (typeof value === 'string' && value.trim().length === 0) {
          callback(new Error('租户名称不能只包含空格'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  try {
    const tenantName = form.tenantName.trim()
    await auth.login({ username: form.username, password: form.password, tenantName })
    localStorage.setItem(LAST_TENANT_KEY, tenantName)
    ElMessage.success(`欢迎回来，${auth.displayName}`)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/home'
    try {
      await router.replace(redirect)
    } catch {
      // 若 Vue Router 导航失败（如 SSR/自动化环境），降级为整页跳转
      window.location.href = redirect
    }
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
  line-height: 1.7;
  color: var(--aioa-text-sub);
  text-align: center;
}

.field-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--aioa-text-sub);
}
</style>
