<template>
  <!-- 布局参照 vue-pure-admin 经典竖向布局：
       侧边栏 = 顶部logo + 中间滚动菜单 + 底部固定折叠按钮；
       顶栏 = 左面包屑 + 右用户下拉 -->
  <el-container class="app-shell">
    <el-aside :width="collapsed ? '64px' : '224px'" class="app-aside">
      <div class="brand-row" :class="{ collapsed }">
        <div class="brand-icon"><el-icon :size="22"><Lock /></el-icon></div>
        <div v-show="!collapsed" class="brand-text">
          <div class="brand-title">智能审核平台</div>
          <div class="brand-sub">物业集团统一审核</div>
        </div>
      </div>
      <el-scrollbar class="menu-scroll">
        <el-menu class="sidebar-menu" :collapse="collapsed" :collapse-transition="false" :default-active="activeKey" @select="(key: string) => router.push(key)">
          <el-menu-item v-for="item in visibleMenus" :key="item.key" :index="item.key">
            <el-icon :size="18"><component :is="item.icon" /></el-icon>
            <template #title>{{ item.label }}</template>
          </el-menu-item>
        </el-menu>
      </el-scrollbar>
    </el-aside>
    <el-container direction="vertical">
      <el-header height="56px" class="app-header">
        <!-- 折叠按钮：顶栏最左（aside 与 header 交界处） -->
        <button class="fold-btn" :title="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="collapsed = !collapsed">
          <el-icon :size="18"><Expand v-if="collapsed" /><Fold v-else /></el-icon>
        </button>
        <el-breadcrumb separator="/">
<!--          <el-breadcrumb-item>{{ homeLabel }}</el-breadcrumb-item>-->
          <el-breadcrumb-item>{{ title }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="header-right">
          <span class="role-tag">{{ roleLabel }}</span>
          <el-dropdown @command="(cmd: string) => cmd === 'logout' && onLogout()">
            <span class="user-entry">
              {{ auth.user?.display_name }}
              <span v-if="auth.role === 'project_user' && auth.projectName" class="user-proj">（{{ auth.projectName }}）</span>
              <el-icon :size="12"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="app-main" :key="`${auth.role}-${auth.projectName}-${route.path}`">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Lock, SwitchButton, HomeFilled, List, Checked,
  Document, Notebook, OfficeBuilding, Upload, User, Expand, Fold, ArrowDown,
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import type { MenuItem } from '../types'

const menus: MenuItem[] = [
  { key: '/dashboard', label: '首页', icon: HomeFilled, roles: ['group_admin'] },
  // AI审核已并入审核结果页顶部；审核结果 / 异常确认 / PDF报告只对项目账号开放
  { key: '/results', label: '审核结果', icon: List, roles: ['project_user'] },
  { key: '/confirmation', label: '异常确认', icon: Checked, roles: ['project_user'] },
  { key: '/reports', label: 'PDF报告', icon: Document, roles: ['project_user'] },
  { key: '/contracts', label: '合同管理', icon: Notebook, roles: ['group_admin', 'project_user'] },
  { key: '/project-management', label: '项目管理', icon: OfficeBuilding, roles: ['group_admin'] },
  { key: '/bi-upload', label: 'BI考勤', icon: Upload, roles: ['group_admin'] },
  { key: '/user-management', label: '用户管理', icon: User, roles: ['group_admin'] },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const roleLabelMap: Record<string, string> = { group_admin: '集团管理员', project_user: '项目账号' }
const roleLabel = computed(() => roleLabelMap[auth.role] || auth.role)
const visibleMenus = computed(() => menus.filter((m) => m.roles.includes(auth.role)))
const activeKey = computed(() => route.path)
const title = computed(() => visibleMenus.value.find((m) => m.key === route.path)?.label || '智能审核平台')
// const homeLabel = computed(() => (auth.role === 'group_admin' ? '集团驾驶舱' : '项目工作台'))

function onLogout() {
  auth.logout()
  router.replace('/login')
}
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
}
.app-aside {
  background: var(--slate-950);
  color: #fff;
  transition: width 0.28s;
  overflow-x: hidden;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: sticky;
  top: 0;
}
.brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 20px;
  flex-shrink: 0;
}
.brand-row.collapsed {
  justify-content: center;
  padding: 18px 0;
}
.brand-icon {
  border-radius: 10px;
  background: var(--brand-600);
  padding: 8px;
  flex-shrink: 0;
  display: flex;
}
.brand-text {
  white-space: nowrap;
  overflow: hidden;
}
.brand-title {
  font-size: 15px;
  font-weight: 600;
}
.brand-sub {
  font-size: 11px;
  color: var(--slate-400);
}
.menu-scroll {
  flex: 1;
  padding: 8px;
}
.menu-scroll :deep(.el-menu) {
  background: transparent;
  border-right: none;
}
.fold-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  color: var(--slate-500);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
  flex-shrink: 0;
  margin-right: 12px;
}
.fold-btn:hover {
  color: var(--slate-900);
  background: var(--slate-100);
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--slate-200);
  background: #fff;
  padding: 0 24px;
  box-shadow: 0 1px 4px 0 rgb(0 0 0 / 0.06);
  position: relative;
  z-index: 10;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.role-tag {
  font-size: 12px;
  color: var(--slate-500);
  background: var(--slate-100);
  border-radius: 10px;
  padding: 3px 10px;
}
.user-entry {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  color: var(--slate-700);
  cursor: pointer;
  outline: none;
}
.user-proj {
  color: var(--slate-400);
}
.app-main {
  min-width: 0;
  padding: 24px;
  background: var(--slate-50);
}
</style>
