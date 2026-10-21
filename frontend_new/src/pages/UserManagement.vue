<template>
  <div class="page-stack">
    <div class="card card-pad">
      <div class="head-row">
        <div>
          <h2 class="h2 row gap-2">
            <el-icon :size="20"><User /></el-icon>
            用户管理
          </h2>
          <p class="text-muted desc">管理系统账号。集团管理员可查看所有数据，项目账号只能访问自己项目的页面。</p>
        </div>
        <div class="row-wrap gap-3">
          <button class="btn-secondary row gap-2" :disabled="loading" @click="loadUsers">
            <el-icon :size="16" :class="loading ? 'is-loading' : ''"><Refresh /></el-icon>
            刷新
          </button>
          <button class="btn-secondary row gap-2" :disabled="batching" @click="handleBatchCreate">
            <el-icon :size="16"><User /></el-icon>
            {{ batching ? '生成中...' : '批量生成项目账号' }}
          </button>
          <button class="btn-secondary row gap-2" :disabled="regenerating" @click="handleRegeneratePasswords">
            <el-icon :size="16"><Key /></el-icon>
            {{ regenerating ? '生成中...' : '查看所有项目账号密码' }}
          </button>
          <button class="btn-primary row gap-2" @click="showCreate = !showCreate">
            <el-icon :size="16"><Plus /></el-icon>
            新建用户
          </button>
        </div>
      </div>

      <div class="grid-3 mt-20">
        <div class="stat-box">
          <div class="stat-label">总账号数</div>
          <div class="stat-value">{{ users.length }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">集团管理员</div>
          <div class="stat-value">{{ users.filter((u) => u.role === true).length }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">项目账号</div>
          <div class="stat-value">{{ users.filter((u) => u.role === false).length }}</div>
        </div>
      </div>

      <div v-if="message" class="notice">{{ message }}</div>
    </div>

    <!-- 新建用户 -->
    <div v-if="showCreate" class="card p-6">
      <div class="row-between">
        <h3 class="h3">新建用户</h3>
        <button class="icon-btn" @click="showCreate = false">
          <el-icon :size="20"><Close /></el-icon>
        </button>
      </div>
      <div class="grid-2 mt-16">
        <label class="field">
          <span class="field-label">用户名</span>
          <input v-model="createForm.username" class="input field-input" placeholder="登录用户名" />
        </label>
        <label class="field">
          <span class="field-label">密码</span>
          <input v-model="createForm.password" class="input field-input" placeholder="至少 6 位" />
        </label>
        <label class="field">
          <span class="field-label">显示名称</span>
          <input v-model="createForm.display_name" class="input field-input" placeholder="留空则用用户名" />
        </label>
        <label class="field">
          <span class="field-label">角色</span>
          <el-select v-model="createForm.role" class="field-input">
            <el-option value="project_user" label="项目账号" />
            <el-option value="group_admin" label="集团管理员" />
          </el-select>
        </label>
        <label v-if="createForm.role === 'project_user'" class="field span-2">
          <span class="field-label">绑定项目</span>
          <el-select v-model="createForm.project_name" placeholder="请选择项目" class="field-input">
            <el-option v-for="p in projects" :key="p.project_name" :value="p.project_name" :label="p.project_name" />
          </el-select>
        </label>
      </div>
      <div class="row gap-3 mt-16">
        <button class="btn-primary" :disabled="creating" @click="handleCreate">{{ creating ? '创建中...' : '确认创建' }}</button>
        <button class="btn-secondary" @click="showCreate = false">取消</button>
      </div>
    </div>

    <!-- 批量账号结果 -->
    <div v-if="batchResult" class="card p-6">
      <div class="row-between">
        <h3 class="h3">项目账号密码（{{ batchResult.length }} 个）</h3>
        <div class="row gap-3">
          <button class="btn-secondary row gap-2" @click="copyAllAccounts">
            <el-icon :size="16"><component :is="copied === 'all' ? 'Check' : 'CopyDocument'" /></el-icon>
            {{ copied === 'all' ? '已复制' : '复制全部' }}
          </button>
          <button class="btn-secondary" @click="batchResult = null">关闭</button>
        </div>
      </div>
      <div class="table-wrap mt-16">
        <el-table :data="batchResult" border stripe style="width: 100%">
          <el-table-column label="项目名称" min-width="160">
            <template #default="{ row }"><span class="text-strong">{{ row.project_name }}</span></template>
          </el-table-column>
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column label="密码" min-width="120">
            <template #default="{ row }"><span class="mono">{{ row.password }}</span></template>
          </el-table-column>
          <el-table-column label="复制" align="center" width="80">
            <template #default="{ row }">
              <button class="icon-btn brand" @click="copyToClipboard(`${row.username}\t${row.password}`, row.username)">
                <el-icon :size="16"><component :is="copied === row.username ? 'Check' : 'CopyDocument'" /></el-icon>
              </button>
            </template>
          </el-table-column>
          <template #empty><span class="text-muted">所有项目已创建账号，无需新增</span></template>
        </el-table>
      </div>
    </div>

    <!-- 账号列表 -->
    <div class="card card-pad">
      <div class="row-between">
        <h3 class="h3">账号列表</h3>
        <span class="text-xs text-muted">共 {{ users.length }} 条</span>
      </div>
      <div class="table-wrap mt-16">
        <el-table :data="users" border stripe style="width: 100%">
          <el-table-column label="用户名" min-width="120">
            <template #default="{ row }"><span class="text-strong">{{ row.username }}</span></template>
          </el-table-column>
          <el-table-column label="显示名称" min-width="120">
            <template #default="{ row }">{{ row.display_name || row.username }}</template>
          </el-table-column>
          <el-table-column label="角色" width="110">
            <template #default="{ row }">
              <span class="badge" :class="row.role ? 'badge-purple' : 'badge-blue'">
                {{ row.role ? '集团管理员' : '项目账号' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="绑定项目" min-width="140">
            <template #default="{ row }">{{ row.project_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <span class="badge" :class="row.status === 'active' ? 'badge-green' : 'badge-slate'">
                {{ row.status === 'active' ? '正常' : '禁用' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="150">
            <template #default="{ row }"><span class="text-xs nowrap text-muted">{{ row.created_at || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="操作" align="center" width="100">
            <template #default="{ row }">
              <div class="row gap-2" style="justify-content: center">
                <button class="icon-btn brand" title="重置密码" @click="resetTarget = row; newPassword = ''">
                  <el-icon :size="16"><Key /></el-icon>
                </button>
                <button class="icon-btn danger" title="删除用户" @click="handleDelete(row)">
                  <el-icon :size="16"><Delete /></el-icon>
                </button>
              </div>
            </template>
          </el-table-column>
          <template #empty><span class="text-muted">暂无用户数据</span></template>
        </el-table>
      </div>
    </div>

    <!-- 重置密码弹层 -->
    <div v-if="resetTarget" class="modal-mask">
      <div class="card modal-card">
        <div class="row-between">
          <h3 class="h3">重置密码</h3>
          <button class="icon-btn" @click="resetTarget = null">
            <el-icon :size="20"><Close /></el-icon>
          </button>
        </div>
        <p class="text-muted mt-12">正在为用户「{{ resetTarget.display_name || resetTarget.username }}」重置密码</p>
        <label class="field mt-16">
          <span class="field-label">新密码</span>
          <input v-model="newPassword" class="input field-input" placeholder="至少 6 位" autofocus />
        </label>
        <div class="row gap-3 mt-16">
          <button class="btn-primary" :disabled="resetting" @click="handleReset">{{ resetting ? '重置中...' : '确认重置' }}</button>
          <button class="btn-secondary" @click="resetTarget = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Check, Close, CopyDocument, Delete, Key, Plus, Refresh, User } from '@element-plus/icons-vue'
import { request } from '../api'
import { fetchContracts } from '../api/configCache'

type UserRow = {
  id: number
  username: string
  role: boolean
  display_name: string
  project_name: string
  project_code: string
  status: string
  created_at: string
  updated_at: string
}

type Project = { project_name: string; project_code: string }
type CreatedAccount = { username: string; password: string; project_name: string }

const users = ref<UserRow[]>([])
const projects = ref<Project[]>([])
const loading = ref(false)
const message = ref('')

const showCreate = ref(false)
const createForm = ref({ username: '', password: '', display_name: '', role: 'project_user', project_name: '' })
const creating = ref(false)

const resetTarget = ref<UserRow | null>(null)
const newPassword = ref('')
const resetting = ref(false)

const batchResult = ref<CreatedAccount[] | null>(null)
const batching = ref(false)
const copied = ref<string | null>(null)
const regenerating = ref(false)

async function loadUsers() {
  loading.value = true
  try {
    const rows = await request<UserRow[]>('/api/v2/user/users')
    users.value = rows
    message.value = `共 ${rows.length} 个账号`
  } catch (err: any) {
    message.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadProjects() {
  try {
    const contracts = await fetchContracts<any[]>()
    const seen = new Set<string>()
    const list: Project[] = []
    for (const c of contracts) {
      if (c.project_name && !seen.has(c.project_name)) {
        seen.add(c.project_name)
        list.push({ project_name: c.project_name, project_code: c.project_code || '' })
      }
    }
    projects.value = list
  } catch {
    projects.value = []
  }
}

async function handleCreate() {
  if (!createForm.value.username.trim()) {
    message.value = '用户名不能为空'
    return
  }
  if (createForm.value.password.length < 6) {
    message.value = '密码至少 6 位'
    return
  }
  creating.value = true
  try {
    await request('/api/v1/auth/users', {
      method: 'POST',
      data: { ...createForm.value, role: createForm.value.role === 'group_admin' },
    })
    message.value = `用户 ${createForm.value.username} 创建成功`
    showCreate.value = false
    createForm.value = { username: '', password: '', display_name: '', role: 'project_user', project_name: '' }
    await loadUsers()
  } catch (err: any) {
    message.value = err.message || '创建失败'
  } finally {
    creating.value = false
  }
}

async function handleReset() {
  if (!resetTarget.value) return
  if (newPassword.value.length < 6) {
    message.value = '新密码至少 6 位'
    return
  }
  resetting.value = true
  try {
    await request(`/api/v1/auth/users/${resetTarget.value.id}/password`, {
      method: 'PUT',
      data: { new_password: newPassword.value },
    })
    message.value = `用户 ${resetTarget.value.username} 密码已重置`
    resetTarget.value = null
    newPassword.value = ''
  } catch (err: any) {
    message.value = err.message || '重置失败'
  } finally {
    resetting.value = false
  }
}

async function handleDelete(user: UserRow) {
  if (!confirm(`确认删除用户「${user.display_name || user.username}」？此操作不可撤销。`)) return
  try {
    await request(`/api/v1/auth/users/${user.id}`, { method: 'DELETE' })
    message.value = `用户 ${user.username} 已删除`
    await loadUsers()
  } catch (err: any) {
    message.value = err.message || '删除失败'
  }
}

async function handleBatchCreate() {
  if (!confirm('将为所有未创建账号的项目批量生成项目账号，确认继续？')) return
  batching.value = true
  try {
    const data = await request<{ created: CreatedAccount[]; count: number; message: string }>(
      '/api/v1/auth/users/batch-projects',
      { method: 'POST' },
    )
    batchResult.value = data.created
    message.value = data.message
    await loadUsers()
  } catch (err: any) {
    message.value = err.message || '批量创建失败'
  } finally {
    batching.value = false
  }
}

async function handleRegeneratePasswords() {
  if (!confirm('将重新生成所有项目账号的密码（旧密码失效），并在页面显示新密码。确认继续？')) return
  regenerating.value = true
  try {
    const data = await request<{ accounts: CreatedAccount[]; count: number; message: string }>(
      '/api/v1/auth/users/regenerate-passwords',
      { method: 'POST' },
    )
    batchResult.value = data.accounts
    message.value = data.message + '，请立即复制保存'
    await loadUsers()
  } catch (err: any) {
    message.value = err.message || '重新生成失败'
  } finally {
    regenerating.value = false
  }
}

async function copyToClipboard(text: string, key: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      ta.style.top = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (!ok) throw new Error('execCommand copy failed')
    }
    copied.value = key
    setTimeout(() => (copied.value = null), 1500)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.left = '0'
    ta.style.top = '0'
    ta.style.width = '500px'
    ta.style.height = '300px'
    ta.style.zIndex = '9999'
    ta.style.fontSize = '14px'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    message.value = '自动复制失败，请手动 Ctrl+C 复制文本框内容'
    setTimeout(() => document.body.removeChild(ta), 10000)
  }
}

function copyAllAccounts() {
  if (!batchResult.value) return
  const text = batchResult.value.map((a) => `${a.project_name}\t${a.username}\t${a.password}`).join('\n')
  copyToClipboard(text, 'all')
}

onMounted(() => {
  loadUsers()
  loadProjects()
})
</script>


<style scoped>
.h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--slate-900); }
.h3 { font-size: 16px; font-weight: 600; margin: 0; color: var(--slate-900); }
.head-row { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 16px; }
.desc { margin-top: 8px; }
.mt-12 { margin-top: 12px; }
.mt-16 { margin-top: 16px; }
.mt-20 { margin-top: 20px; }
.field { display: block; }
.field-label { font-size: 14px; font-weight: 500; color: var(--slate-700); }
.field-input { margin-top: 6px; width: 100%; }
.span-2 { grid-column: span 2; }
.nowrap { white-space: nowrap; }
.text-center { text-align: center; }
.mono { font-family: ui-monospace, monospace; color: var(--slate-600); }
.icon-btn { color: var(--slate-400); transition: color 0.15s; }
.icon-btn:hover { color: var(--slate-600); }
.icon-btn.brand:hover { color: var(--brand-600); }
.icon-btn.danger:hover { color: var(--red-600); }
.modal-mask {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.4);
}
.modal-card { width: 384px; padding: 24px; }
</style>
