<template>
  <div>
    <div class="row-between text-sm">
      <span class="label">{{ label }}</span>
      <span class="value">{{ formatMoney(value) }} 元 · {{ percent }}%</span>
    </div>
    <div class="track">
      <div class="fill" :class="color" :style="{ width: `${Math.max(percent, value > 0 ? 4 : 0)}%` }" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  label: string
  value: number
  total: number
  color: string
}>(), {})

const percent = computed(() => (props.total > 0 ? Math.round((props.value / props.total) * 100) : 0))

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<style scoped>
.text-sm { font-size: 14px; }
.label { color: var(--slate-600); }
.value { font-weight: 500; color: var(--slate-900); }
.track { margin-top: 8px; height: 12px; overflow: hidden; border-radius: 999px; background: var(--slate-100); }
.fill { height: 100%; border-radius: 999px; }
.bg-red-500 { background: #ef4444; }
.bg-orange-500 { background: #f97316; }
.bg-yellow-500 { background: #eab308; }
.bg-purple-500 { background: #a855f7; }
</style>
