<template>
  <el-segmented
    v-if="options.length"
    :model-value="value"
    :options="options"
    class="svc-segmented"
    @update:model-value="onChange"
  >
    <template #default="{ item }">
      <span class="seg-item">
        <span>{{ item.label }}</span>
        <span class="dot" :class="item.hasResult ? 'dot-on' : 'dot-off'" :title="item.hasResult ? '已有审核结果' : '暂无审核结果'" />
      </span>
    </template>
  </el-segmented>
</template>

<script setup lang="ts">
import type { ServiceTypeOption } from '../composables/useServiceTypes'

const props = defineProps<{
  options: ServiceTypeOption[]
  value: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:value': [string]
  change: [string]
}>()

function onChange(v: string | number | boolean) {
  if (props.disabled) return
  const val = String(v)
  emit('update:value', val)
  emit('change', val)
}
</script>

<style scoped>
.svc-segmented {
  margin-top: 12px;
  --el-segmented-bg-color: var(--card-bg);
  --el-segmented-item-selected-bg-color: var(--accent);
  --el-segmented-item-selected-color: #fff;
  --el-segmented-item-hover-color: var(--accent);
}
.seg-item { display: inline-flex; align-items: center; gap: 6px; }
.dot { width: 6px; height: 6px; border-radius: 999px; }
.dot-on { background: var(--success); }
.dot-off { background: var(--slate-300); }
/* 选中项内圆点转白系 */
:deep(.el-segmented__item.is-selected) .dot-on { background: #fff; }
:deep(.el-segmented__item.is-selected) .dot-off { background: rgba(255, 255, 255, 0.5); }
</style>
