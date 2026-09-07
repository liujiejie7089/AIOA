<template>
  <el-container class="layout">
    <el-header class="layout-header" height="56px">
      <div class="brand">
        <el-icon class="brand-icon"><Platform /></el-icon>
        <span class="brand-text">AIOA 智能办公基座</span>
      </div>
      <div class="header-right">
        <el-tag size="small" type="info" effect="plain">{{ auth.tenantName }}</el-tag>
        <el-button type="primary" plain size="small" @click="assistant.openDrawer()">
          <el-icon><ChatDotRound /></el-icon>
          <span style="margin-left: 4px">AI 助手</span>
        </el-button>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-avatar :size="26">{{ initial }}</el-avatar>
            <span class="user-name">{{ auth.displayName }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人信息</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-container>
      <el-aside class="layout-aside" :width="collapsed ? '64px' : '200px'">
        <el-menu
          class="layout-menu"
          :default-active="route.path"
          :default-openeds="['apps']"
          :collapse="collapsed"
          router
        >
          <el-menu-item index="/home">
            <el-icon><HomeFilled /></el-icon>
            <template #title>首页</template>
          </el-menu-item>
          <el-sub-menu index="apps">
            <template #title>
              <el-icon><Grid /></el-icon>
              <span>我的应用</span>
            </template>
            <el-menu-item v-for="item in apps.menuItems" :key="item.appCode" :index="`/app/${item.appCode}`">
              <template #title>{{ item.appName }}</template>
            </el-menu-item>
            <el-menu-item v-if="!apps.menuItems.length" index="__empty_app" disabled>暂无应用</el-menu-item>
          </el-sub-menu>
          <el-menu-item index="/approvals">
            <el-icon><Tickets /></el-icon>
            <template #title>审批中心</template>
          </el-menu-item>
          <el-menu-item index="/kb">
            <el-icon><Collection /></el-icon>
            <template #title>知识库</template>
          </el-menu-item>
          <el-menu-item index="/admin">
            <el-icon><Setting /></el-icon>
            <template #title>系统管理</template>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <AssistantDrawer />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AssistantDrawer from '@/components/assistant/AssistantDrawer.vue'
import { useAppsStore } from '@/stores/apps'
import { useAuthStore } from '@/stores/auth'
import { useAssistantStore } from '@/stores/assistant'
import { initBridge } from '@/micro/bridge'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const apps = useAppsStore()
const assistant = useAssistantStore()

const collapsed = ref(false)

const initial = computed(() => auth.displayName.slice(0, 1).toUpperCase())

async function onCommand(command: string | number | object) {
  if (command === 'logout') {
    await auth.logout()
    ElMessage.success('已退出登录')
    router.replace('/login')
  } else if (command === 'profile') {
    ElMessage.info('M1 未实现个人信息页')
  }
}

onMounted(() => {
  initBridge()
  void apps.list()
})
</script>
