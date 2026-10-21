<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { getToken } from './api'
import { preloadConfigs } from './api/configCache'

const auth = useAuthStore()
const router = useRouter()

// 401 时 api 层会广播 auth:logout，这里统一回登录页
function onLogout() {
  auth.logout()
  router.replace('/login')
}

onMounted(() => {
  window.addEventListener('auth:logout', onLogout)
  // 已登录时预灌低频配置（业态映射、合同列表），页面挂载即命中缓存
  if (getToken()) preloadConfigs()
})
onUnmounted(() => window.removeEventListener('auth:logout', onLogout))
</script>
