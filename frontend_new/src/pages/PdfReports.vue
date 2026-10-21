<template>
  <div v-if="!ctxStore.context" class="card empty-state">请先完成一次审核</div>
  <ReportDownloads v-else :audit-context="ctxStore.context" />
</template>

<script setup lang="ts">
import ReportDownloads from '../components/ReportDownloads.vue'
import { useAuditContextStore } from '../stores/auditContext'

const ctxStore = useAuditContextStore()
</script>
