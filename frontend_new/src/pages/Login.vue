<template>
  <div class="login-shell">
    <div class="login-box">
      <div class="login-head">
        <div class="login-icon"><el-icon :size="32"><Lock /></el-icon></div>
        <h1 class="login-title">物业集团保安保洁智能审核平台</h1>
        <p class="login-sub">请登录后使用</p>
      </div>
      <form class="card login-form" @submit.prevent="handleSubmit">
        <div class="field">
          <label>用户名</label>
          <input v-model="username" class="input" autocomplete="username" />
        </div>
        <div class="field">
          <label>密码</label>
          <input v-model="password" type="password" class="input" autocomplete="current-password" />
        </div>
        <p v-if="error" class="error-text">{{ error }}</p>
        <button type="submit" class="btn-primary login-btn" :disabled="loading">
          <el-icon v-if="loading" class="is-loading"><Loading /></el-icon>
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Lock, Loading } from '@element-plus/icons-vue'
import { request } from '../api'
import { useAuthStore } from '../stores/auth'
import { homePathOf } from '../router'
import type { LoginUser } from '../types'

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const auth = useAuthStore()
const router = useRouter()

async function handleSubmit() {
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await request<{ token: string; user: LoginUser }>('/api/v2/user/login', {
      method: 'POST',
      data: { username: username.value.trim(), password: password.value },
    })
    auth.login(data.token, data.user)
    router.replace(homePathOf(auth.role))
  } catch (err: any) {
    error.value = err.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-shell {
  display: flex;
  min-height: 100vh;
  align-items: center;
  justify-content: center;
  background: var(--slate-950);
  padding: 0 16px;
}
.login-box {
  width: 100%;
  max-width: 384px;
}
.login-head {
  margin-bottom: 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.login-icon {
  border-radius: 16px;
  background: var(--brand-600);
  padding: 16px;
  color: #fff;
  display: flex;
}
.login-title {
  margin-top: 20px;
  font-size: 20px;
  font-weight: 600;
  color: #fff;
}
.login-sub {
  margin-top: 8px;
  font-size: 14px;
  color: var(--slate-400);
}
.login-form {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field label {
  font-size: 14px;
  font-weight: 500;
  color: var(--slate-700);
}
.field .input {
  margin-top: 6px;
  width: 100%;
}
.error-text {
  font-size: 14px;
  color: var(--red-600);
  margin: 0;
}
.login-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
</style>
