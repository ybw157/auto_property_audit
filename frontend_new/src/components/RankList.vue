<template>
  <div v-if="!items.length" class="empty">{{ emptyText }}</div>
  <div v-else class="rank-list">
    <div v-for="item in items" :key="item.name">
      <div class="row-between text-sm">
        <span class="name">{{ item.name }}</span>
        <span class="value">{{ item.value }}{{ suffix }}</span>
      </div>
      <div class="track">
        <div class="fill" :class="color" :style="{ width: `${Math.max((item.value / max) * 100, 6)}%` }" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  items: Array<{ name: string; value: number }>
  emptyText: string
  color: string
  suffix?: string
}>(), { suffix: '次' })

const max = computed(() => Math.max(...props.items.map((item) => item.value), 1))
</script>

<style scoped>
.empty { margin-top: 32px; text-align: center; font-size: 14px; color: var(--slate-500); }
.rank-list { margin-top: 16px; display: flex; flex-direction: column; gap: 12px; }
.text-sm { font-size: 14px; }
.name { max-width: 65%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--slate-700); }
.value { font-weight: 500; color: var(--slate-900); }
.track { margin-top: 8px; height: 8px; overflow: hidden; border-radius: 999px; background: var(--slate-100); }
.fill { height: 100%; border-radius: 999px; }
.bg-blue-500 { background: #3b82f6; }
.bg-amber-500 { background: #f59e0b; }
</style>
