<template>
  <el-card shadow="never">
    <el-empty :description="desc">
      <template #description>
        <div class="ph-title">{{ title }}</div>
        <div class="ph-desc">{{ desc }}</div>
      </template>
      <el-tag type="info" effect="plain" size="small">M1 里程碑交付</el-tag>
    </el-empty>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  desc: string
}>()
</script>

<style scoped>
.ph-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--aioa-text);
  margin-bottom: 6px;
}

.ph-desc {
  font-size: 12px;
  color: var(--aioa-text-sub);
  margin-bottom: 8px;
}
</style>
