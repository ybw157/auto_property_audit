<template>
  <el-table
    :data="rows"
    :empty-text="emptyText"
    border
    stripe
    style="width: 100%"
    :row-class-name="rowClassAdapter"
  >
    <el-table-column
      v-for="header in headers"
      :key="header"
      :prop="header"
      :label="labels[header] ?? header"
      :min-width="128"
      show-overflow-tooltip
    >
      <template #default="{ row }">
        <slot name="cell" :row="row" :field="header">{{ String(row[header] ?? '') }}</slot>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  rows: Record<string, unknown>[]
  emptyText?: string
  columns?: string[]
  labels?: Record<string, string>
  /** 行类名：返回 'row-danger' 等（样式在本组件内定义） */
  getRowClassName?: (row: Record<string, unknown>) => string
}>(), {
  emptyText: '暂无数据',
  columns: undefined,
  labels: () => ({}),
  getRowClassName: undefined,
})

const headers = computed(() =>
  (props.columns?.length ? props.columns : Object.keys(props.rows[0] || {}))
    .filter((key) => key in (props.rows[0] || {}))
    .slice(0, 12),
)

// el-table 的行回调签名是 ({ row })，适配外部按行数据判断的口径
function rowClassAdapter({ row }: { row: Record<string, unknown> }) {
  return props.getRowClassName?.(row) ?? ''
}
</script>

<style>
/* el-table 行级配色（非 scoped：行类名由 el-table 内部拼到 tr 上） */
.el-table .row-danger {
  --el-table-tr-bg-color: #fef2f2;
}
.el-table .row-danger td {
  color: #991b1b !important;
}
</style>
